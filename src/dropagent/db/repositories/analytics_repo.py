"""
Analytics Repository - Database operations for PriceHistory, TrendData, and ProductPerformance.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models import PriceHistory, ProductPerformance, TrendData
from dropagent.utils.exceptions import DatabaseError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class AnalyticsRepository:
    """Repository for analytics data: price history, trends, and product performance."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ─── Price History ──────────────────────────────────────────────────

    async def add_price_record(
        self,
        product_id: int,
        price_ali,
        price_naver,
        exchange_rate,
    ) -> PriceHistory:
        """
        Add a new price history record.

        Args:
            product_id: The product's primary key.
            price_ali: Current AliExpress price.
            price_naver: Current Naver SmartStore price.
            exchange_rate: Exchange rate at the time of recording.

        Returns:
            The newly created PriceHistory instance.
        """
        try:
            record = PriceHistory(
                product_id=product_id,
                price_ali=price_ali,
                price_naver=price_naver,
                exchange_rate=exchange_rate,
            )
            self.session.add(record)
            await self.session.flush()
            await self.session.refresh(record)
            logger.info(
                "price_record_added",
                product_id=product_id,
                price_ali=str(price_ali),
                price_naver=str(price_naver),
            )
            return record
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "price_record_add_error",
                product_id=product_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to add price record",
                operation="add_price_record",
                table="price_history",
                details={"product_id": product_id},
                original_error=e,
            ) from e

    async def get_price_history(
        self,
        product_id: int,
        days: int = 30,
    ) -> list[PriceHistory]:
        """
        Get price history for a product over the specified number of days.

        Args:
            product_id: The product's primary key.
            days: Number of days to look back.

        Returns:
            List of PriceHistory instances ordered by recorded_at ascending.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            stmt = (
                select(PriceHistory)
                .where(PriceHistory.product_id == product_id)
                .where(PriceHistory.recorded_at >= cutoff)
                .order_by(PriceHistory.recorded_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "price_history_get_error",
                product_id=product_id,
                days=days,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get price history",
                operation="get_price_history",
                table="price_history",
                details={"product_id": product_id, "days": days},
                original_error=e,
            ) from e

    # ─── Trend Data ─────────────────────────────────────────────────────

    async def add_trend_data(self, data: dict) -> TrendData:
        """
        Add a new trend data record.

        Args:
            data: Dictionary with keyword, category, click_ratio, search_volume fields.

        Returns:
            The newly created TrendData instance.
        """
        try:
            record = TrendData(**data)
            self.session.add(record)
            await self.session.flush()
            await self.session.refresh(record)
            logger.info(
                "trend_data_added",
                keyword=record.keyword,
                category=record.category,
            )
            return record
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "trend_data_add_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to add trend data",
                operation="add_trend_data",
                table="trend_data",
                original_error=e,
            ) from e

    async def get_trend_data(
        self,
        keyword: str,
        days: int = 30,
    ) -> list[TrendData]:
        """
        Get trend data for a specific keyword over the specified days.

        Args:
            keyword: The search keyword.
            days: Number of days to look back.

        Returns:
            List of TrendData instances ordered by collected_at ascending.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            stmt = (
                select(TrendData)
                .where(TrendData.keyword == keyword)
                .where(TrendData.collected_at >= cutoff)
                .order_by(TrendData.collected_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "trend_data_get_error",
                keyword=keyword,
                days=days,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get trend data",
                operation="get_trend_data",
                table="trend_data",
                details={"keyword": keyword, "days": days},
                original_error=e,
            ) from e

    async def get_top_trending_keywords(self, limit: int = 20) -> list[dict]:
        """
        Get the top trending keywords by total search volume over the last 30 days.

        Args:
            limit: Maximum number of keywords to return.

        Returns:
            List of dicts with keyword, category, total_search_volume, avg_click_ratio,
            and record_count.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(days=30)
            stmt = (
                select(
                    TrendData.keyword,
                    TrendData.category,
                    func.sum(TrendData.search_volume).label("total_search_volume"),
                    func.avg(TrendData.click_ratio).label("avg_click_ratio"),
                    func.count(TrendData.id).label("record_count"),
                )
                .where(TrendData.collected_at >= cutoff)
                .group_by(TrendData.keyword, TrendData.category)
                .order_by(func.sum(TrendData.search_volume).desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            rows = result.all()
            return [
                {
                    "keyword": row.keyword,
                    "category": row.category,
                    "total_search_volume": int(row.total_search_volume),
                    "avg_click_ratio": float(row.avg_click_ratio),
                    "record_count": row.record_count,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(
                "top_trending_keywords_error",
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get top trending keywords",
                operation="get_top_trending_keywords",
                table="trend_data",
                original_error=e,
            ) from e

    # ─── Product Performance ────────────────────────────────────────────

    async def add_performance_record(self, data: dict) -> ProductPerformance:
        """
        Add a new product performance record.

        Args:
            data: Dictionary with product_id, impressions, clicks, conversions,
                  revenue, and recorded_at fields.

        Returns:
            The newly created ProductPerformance instance.

        Raises:
            DatabaseError: On duplicate (product_id, recorded_at) or other DB errors.
        """
        try:
            record = ProductPerformance(**data)
            self.session.add(record)
            await self.session.flush()
            await self.session.refresh(record)
            logger.info(
                "performance_record_added",
                product_id=record.product_id,
                recorded_at=str(record.recorded_at),
            )
            return record
        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(
                "performance_record_integrity_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Performance record for this product and date already exists",
                operation="add_performance_record",
                table="product_performance",
                details={"data": data},
                original_error=e,
            ) from e
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "performance_record_add_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to add performance record",
                operation="add_performance_record",
                table="product_performance",
                original_error=e,
            ) from e

    async def get_performance(
        self,
        product_id: int,
        days: int = 30,
    ) -> list[ProductPerformance]:
        """
        Get performance records for a product over the specified number of days.

        Args:
            product_id: The product's primary key.
            days: Number of days to look back.

        Returns:
            List of ProductPerformance instances ordered by recorded_at ascending.
        """
        try:
            cutoff = date.today() - timedelta(days=days)
            stmt = (
                select(ProductPerformance)
                .where(ProductPerformance.product_id == product_id)
                .where(ProductPerformance.recorded_at >= cutoff)
                .order_by(ProductPerformance.recorded_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "performance_get_error",
                product_id=product_id,
                days=days,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get product performance",
                operation="get_performance",
                table="product_performance",
                details={"product_id": product_id, "days": days},
                original_error=e,
            ) from e

    async def get_top_performing(
        self,
        metric: str = "revenue",
        limit: int = 20,
    ) -> list[ProductPerformance]:
        """
        Get top performing products by a specified metric over the last 30 days.

        Supported metrics: revenue, impressions, clicks, conversions.

        Args:
            metric: The metric to sort by (default: revenue).
            limit: Maximum number of records to return.

        Returns:
            List of ProductPerformance instances ordered by the chosen metric descending.

        Raises:
            DatabaseError: If the metric is invalid or the query fails.
        """
        allowed_metrics = {
            "revenue": ProductPerformance.revenue,
            "impressions": ProductPerformance.impressions,
            "clicks": ProductPerformance.clicks,
            "conversions": ProductPerformance.conversions,
        }
        if metric not in allowed_metrics:
            raise DatabaseError(
                message=f"Invalid metric '{metric}'. Must be one of: {', '.join(allowed_metrics)}",
                operation="get_top_performing",
                table="product_performance",
                details={"metric": metric},
            )
        try:
            cutoff = date.today() - timedelta(days=30)
            order_column = allowed_metrics[metric]
            stmt = (
                select(ProductPerformance)
                .where(ProductPerformance.recorded_at >= cutoff)
                .order_by(order_column.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "top_performing_get_error",
                metric=metric,
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get top performing products",
                operation="get_top_performing",
                table="product_performance",
                details={"metric": metric},
                original_error=e,
            ) from e
