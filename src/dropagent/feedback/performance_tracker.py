"""
Product performance tracking and scoring-weight feedback.

Monitors per-product KPIs (impressions, clicks, conversions, revenue),
calculates ROI, identifies underperformers, and suggests adjustments
to the priority-scoring weights based on observed outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models.product import Product
from dropagent.db.models.product_performance import ProductPerformance
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# Default scoring-weight keys mirroring PriorityScorer / ScoringWeights
_DEFAULT_WEIGHTS = {
    "w1_margin": 0.35,
    "w2_demand": 0.25,
    "w3_risk": 0.15,
    "w4_ops_cost": 0.15,
    "w5_supplier": 0.10,
}


class PerformanceTracker:
    """Tracks product performance and updates scoring weights.

    All public methods are async and require an ``AsyncSession`` that is
    injected at construction time.  The caller is responsible for
    committing / rolling back the session.

    Args:
        session: An active SQLAlchemy async session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Record performance
    # ------------------------------------------------------------------

    async def record_performance(
        self,
        product_id: int,
        impressions: int,
        clicks: int,
        conversions: int,
        revenue: float | Decimal,
        recorded_at: date | None = None,
    ) -> ProductPerformance:
        """Persist a daily performance snapshot for a product.

        If a record for the same ``(product_id, recorded_at)`` pair
        already exists, the existing row is updated (upsert semantics).

        Args:
            product_id: Primary-key ID of the product in the ``products``
                table.
            impressions: Number of impressions observed.
            clicks: Number of clicks observed.
            conversions: Number of conversions (orders).
            revenue: Total revenue in KRW.
            recorded_at: Date of the snapshot.  Defaults to today.

        Returns:
            The created or updated ``ProductPerformance`` row.
        """
        recorded_at = recorded_at or date.today()
        revenue_dec = Decimal(str(revenue))

        # Check for existing record (upsert)
        stmt = select(ProductPerformance).where(
            ProductPerformance.product_id == product_id,
            ProductPerformance.recorded_at == recorded_at,
        )
        result = await self._session.execute(stmt)
        existing: ProductPerformance | None = result.scalar_one_or_none()

        if existing is not None:
            existing.impressions = impressions
            existing.clicks = clicks
            existing.conversions = conversions
            existing.revenue = revenue_dec
            logger.info(
                "performance_record_updated",
                product_id=product_id,
                recorded_at=str(recorded_at),
            )
            return existing

        record = ProductPerformance(
            product_id=product_id,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            revenue=revenue_dec,
            recorded_at=recorded_at,
        )
        self._session.add(record)
        logger.info(
            "performance_record_created",
            product_id=product_id,
            recorded_at=str(recorded_at),
        )
        return record

    # ------------------------------------------------------------------
    # ROI calculation
    # ------------------------------------------------------------------

    async def calculate_roi(self, product_id: int) -> dict[str, Any]:
        """Compute cumulative ROI metrics for a product.

        The returned dictionary contains:

        * ``product_id`` -- the queried product ID.
        * ``total_impressions``, ``total_clicks``, ``total_conversions``,
          ``total_revenue`` -- lifetime aggregates.
        * ``ctr`` -- click-through rate (clicks / impressions).
        * ``conversion_rate`` -- conversions / clicks.
        * ``revenue_per_conversion`` -- average revenue per conversion.
        * ``days_tracked`` -- number of daily records found.

        Args:
            product_id: Primary-key ID of the product.

        Returns:
            A dict with the ROI breakdown described above.
        """
        stmt = select(
            func.coalesce(func.sum(ProductPerformance.impressions), 0).label(
                "total_impressions"
            ),
            func.coalesce(func.sum(ProductPerformance.clicks), 0).label(
                "total_clicks"
            ),
            func.coalesce(func.sum(ProductPerformance.conversions), 0).label(
                "total_conversions"
            ),
            func.coalesce(func.sum(ProductPerformance.revenue), Decimal("0")).label(
                "total_revenue"
            ),
            func.count(ProductPerformance.id).label("days_tracked"),
        ).where(ProductPerformance.product_id == product_id)

        result = await self._session.execute(stmt)
        row = result.one()

        total_impressions: int = int(row.total_impressions)
        total_clicks: int = int(row.total_clicks)
        total_conversions: int = int(row.total_conversions)
        total_revenue = Decimal(str(row.total_revenue))
        days_tracked: int = int(row.days_tracked)

        ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0.0
        conversion_rate = (
            (total_conversions / total_clicks) if total_clicks > 0 else 0.0
        )
        revenue_per_conversion = (
            float(total_revenue / total_conversions)
            if total_conversions > 0
            else 0.0
        )

        logger.debug(
            "roi_calculated",
            product_id=product_id,
            total_revenue=float(total_revenue),
            ctr=round(ctr, 4),
            conversion_rate=round(conversion_rate, 4),
        )

        return {
            "product_id": product_id,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_revenue": float(total_revenue),
            "ctr": round(ctr, 4),
            "conversion_rate": round(conversion_rate, 4),
            "revenue_per_conversion": round(revenue_per_conversion, 2),
            "days_tracked": days_tracked,
        }

    # ------------------------------------------------------------------
    # Underperformers
    # ------------------------------------------------------------------

    async def get_underperformers(
        self,
        days: int = 14,
        min_products: int = 10,
    ) -> list[dict[str, Any]]:
        """Return products with low performance over the recent window.

        A product is considered an *underperformer* if it has received
        impressions but its conversion rate is zero, or its
        revenue-per-click falls below the cohort median.

        Only products that have at least one performance record in the
        ``days`` window are evaluated.  If the total number of such
        products is less than ``min_products``, an empty list is returned
        (not enough data for meaningful comparison).

        Args:
            days: Look-back window in days (default 14).
            min_products: Minimum number of products needed for the
                comparison to be meaningful.

        Returns:
            A list of dicts, each containing ``product_id``,
            ``total_impressions``, ``total_clicks``, ``total_conversions``,
            ``total_revenue``, ``revenue_per_click``, and
            ``conversion_rate``.  Sorted by ``revenue_per_click``
            ascending (worst first).
        """
        cutoff = date.today() - timedelta(days=days)

        stmt = (
            select(
                ProductPerformance.product_id,
                func.sum(ProductPerformance.impressions).label("total_impressions"),
                func.sum(ProductPerformance.clicks).label("total_clicks"),
                func.sum(ProductPerformance.conversions).label("total_conversions"),
                func.sum(ProductPerformance.revenue).label("total_revenue"),
            )
            .where(ProductPerformance.recorded_at >= cutoff)
            .group_by(ProductPerformance.product_id)
        )

        result = await self._session.execute(stmt)
        rows = result.all()

        if len(rows) < min_products:
            logger.info(
                "underperformer_check_skipped",
                reason="not_enough_products",
                found=len(rows),
                required=min_products,
            )
            return []

        # Build per-product stats
        product_stats: list[dict[str, Any]] = []
        for row in rows:
            total_clicks = int(row.total_clicks)
            total_conversions = int(row.total_conversions)
            total_revenue = float(row.total_revenue)
            total_impressions = int(row.total_impressions)

            revenue_per_click = (
                (total_revenue / total_clicks) if total_clicks > 0 else 0.0
            )
            conversion_rate = (
                (total_conversions / total_clicks) if total_clicks > 0 else 0.0
            )

            product_stats.append(
                {
                    "product_id": int(row.product_id),
                    "total_impressions": total_impressions,
                    "total_clicks": total_clicks,
                    "total_conversions": total_conversions,
                    "total_revenue": round(total_revenue, 2),
                    "revenue_per_click": round(revenue_per_click, 4),
                    "conversion_rate": round(conversion_rate, 4),
                }
            )

        # Determine median revenue_per_click
        rpcs = sorted(s["revenue_per_click"] for s in product_stats)
        mid = len(rpcs) // 2
        median_rpc = (
            rpcs[mid]
            if len(rpcs) % 2 == 1
            else (rpcs[mid - 1] + rpcs[mid]) / 2
        )

        # Filter underperformers: below median revenue-per-click
        underperformers = [
            s for s in product_stats if s["revenue_per_click"] < median_rpc
        ]
        underperformers.sort(key=lambda s: s["revenue_per_click"])

        logger.info(
            "underperformers_identified",
            total_evaluated=len(product_stats),
            underperformer_count=len(underperformers),
            median_rpc=round(median_rpc, 4),
            days=days,
        )

        return underperformers

    # ------------------------------------------------------------------
    # Weight adjustments
    # ------------------------------------------------------------------

    async def suggest_weight_adjustments(self) -> dict[str, Any]:
        """Suggest scoring-weight adjustments based on recent performance.

        The heuristic compares the top-performing quartile (by total
        revenue) against the bottom quartile and checks which scoring
        dimensions diverge the most.  If high-revenue products tend to
        have substantially higher demand scores, for instance, the
        suggestion will nudge ``w2_demand`` upward.

        Returns:
            A dict with keys:

            * ``current_weights`` -- the baseline weights.
            * ``suggested_weights`` -- the proposed new weights
              (always sum to 1.0).
            * ``adjustments`` -- per-weight delta.
            * ``reasoning`` -- list of human-readable strings
              explaining each adjustment.
            * ``sample_size`` -- number of products analysed.
        """
        # Gather all-time per-product aggregates
        stmt = (
            select(
                ProductPerformance.product_id,
                func.sum(ProductPerformance.revenue).label("total_revenue"),
                func.sum(ProductPerformance.conversions).label("total_conversions"),
                func.sum(ProductPerformance.clicks).label("total_clicks"),
                func.sum(ProductPerformance.impressions).label("total_impressions"),
            )
            .group_by(ProductPerformance.product_id)
            .order_by(func.sum(ProductPerformance.revenue).desc())
        )

        result = await self._session.execute(stmt)
        rows = result.all()

        current_weights = dict(_DEFAULT_WEIGHTS)
        reasoning: list[str] = []

        if len(rows) < 8:
            reasoning.append(
                f"Insufficient data ({len(rows)} products) to suggest adjustments. "
                "At least 8 products with performance data are required."
            )
            return {
                "current_weights": current_weights,
                "suggested_weights": dict(current_weights),
                "adjustments": {k: 0.0 for k in current_weights},
                "reasoning": reasoning,
                "sample_size": len(rows),
            }

        # Split into quartiles
        q_size = max(len(rows) // 4, 1)
        top_ids = [int(r.product_id) for r in rows[:q_size]]
        bottom_ids = [int(r.product_id) for r in rows[-q_size:]]

        # Fetch product-level scores for the two cohorts
        top_scores = await self._fetch_product_scores(top_ids)
        bottom_scores = await self._fetch_product_scores(bottom_ids)

        if not top_scores or not bottom_scores:
            reasoning.append(
                "Could not load product scoring data for comparison."
            )
            return {
                "current_weights": current_weights,
                "suggested_weights": dict(current_weights),
                "adjustments": {k: 0.0 for k in current_weights},
                "reasoning": reasoning,
                "sample_size": len(rows),
            }

        # Compare averages: margin, demand, risk, ops_cost
        score_fields = {
            "w1_margin": "margin_rate",
            "w2_demand": "demand_score",
            "w3_risk": "risk_score",
            "w4_ops_cost": "ops_cost_score",
        }

        adjustments: dict[str, float] = {k: 0.0 for k in current_weights}
        step = 0.02  # nudge step per significant divergence

        for weight_key, db_col in score_fields.items():
            top_avg = _avg(top_scores, db_col)
            bot_avg = _avg(bottom_scores, db_col)

            if top_avg is None or bot_avg is None:
                continue

            diff = top_avg - bot_avg

            # Positive factors (margin, demand): if top > bottom, increase weight
            if weight_key in ("w1_margin", "w2_demand"):
                if diff > 0.10:
                    adjustments[weight_key] = step
                    reasoning.append(
                        f"Top performers have higher avg {db_col} "
                        f"({top_avg:.2f} vs {bot_avg:.2f}). "
                        f"Suggest increasing {weight_key} by {step}."
                    )
                elif diff < -0.10:
                    adjustments[weight_key] = -step
                    reasoning.append(
                        f"Top performers have lower avg {db_col} "
                        f"({top_avg:.2f} vs {bot_avg:.2f}). "
                        f"Suggest decreasing {weight_key} by {step}."
                    )
            # Negative factors (risk, ops_cost): if top < bottom, increase weight
            else:
                if diff < -0.10:
                    adjustments[weight_key] = step
                    reasoning.append(
                        f"Top performers have lower avg {db_col} "
                        f"({top_avg:.2f} vs {bot_avg:.2f}). "
                        f"Suggest increasing {weight_key} penalty by {step}."
                    )
                elif diff > 0.10:
                    adjustments[weight_key] = -step
                    reasoning.append(
                        f"Top performers have higher avg {db_col} "
                        f"({top_avg:.2f} vs {bot_avg:.2f}). "
                        f"Suggest decreasing {weight_key} penalty by {step}."
                    )

        # Apply adjustments and re-normalise to sum to 1.0
        suggested = {
            k: max(0.05, current_weights[k] + adjustments[k])
            for k in current_weights
        }
        total = sum(suggested.values())
        suggested = {k: round(v / total, 4) for k, v in suggested.items()}

        if not reasoning:
            reasoning.append(
                "No significant divergence detected between top and bottom "
                "quartiles. Current weights appear well-calibrated."
            )

        logger.info(
            "weight_adjustments_suggested",
            sample_size=len(rows),
            adjustments=adjustments,
        )

        return {
            "current_weights": current_weights,
            "suggested_weights": suggested,
            "adjustments": {k: round(v, 4) for k, v in adjustments.items()},
            "reasoning": reasoning,
            "sample_size": len(rows),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_product_scores(
        self, product_ids: Sequence[int]
    ) -> list[dict[str, Any]]:
        """Load scoring columns for a set of product IDs."""
        if not product_ids:
            return []

        stmt = select(
            Product.id,
            Product.margin_rate,
            Product.demand_score,
            Product.risk_score,
            Product.ops_cost_score,
            Product.priority_score,
        ).where(Product.id.in_(product_ids))

        result = await self._session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row.id,
                "margin_rate": float(row.margin_rate) if row.margin_rate else None,
                "demand_score": float(row.demand_score) if row.demand_score else None,
                "risk_score": float(row.risk_score) if row.risk_score else None,
                "ops_cost_score": (
                    float(row.ops_cost_score) if row.ops_cost_score else None
                ),
                "priority_score": (
                    float(row.priority_score) if row.priority_score else None
                ),
            }
            for row in rows
        ]


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _avg(records: list[dict[str, Any]], key: str) -> float | None:
    """Return the mean of *key* across *records*, skipping ``None`` values."""
    values = [r[key] for r in records if r.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)
