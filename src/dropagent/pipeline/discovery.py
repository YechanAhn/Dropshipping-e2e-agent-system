"""
Demand-first discovery pipeline (stages S1-S7 of ``docs/RESEARCH_discovery.md``).

Flow:

    seed keywords
      -> S1 demand expansion   (Search Ad keyword tool: related kw + abs volume)
      -> S2 supply measurement (Shopping Search: total product count, productType)
      -> S3 competition filter  (경쟁강도 = product_count / monthly_volume)
      -> S4 momentum (optional)  (DataLab relative series via injected provider)
      -> S7 OpportunityScore -> ranked Top N

The clients are injected so the whole pipeline is unit-testable with mocks and
so live API calls (which need credentials + network) stay at the edges. Momentum
is supplied as a pluggable async provider rather than hard-wired to DataLab, to
keep this module decoupled from DataLab's response shape.
"""

import asyncio
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from dropagent.clients.naver.searchad_api import NaverSearchAdClient
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.core.discovery.competition import (
    DEFAULT_WEIGHTS,
    CompetitionGrade,
    OpportunityComponents,
    competition_intensity,
    grade_competition,
    opportunity_score,
)
from dropagent.core.discovery.momentum import MomentumResult, momentum_score
from dropagent.utils.exceptions import APIError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# Search Ad accepts at most 5 hint keywords per call.
SEED_BATCH_SIZE = 5

# Naver Shopping productType codes for "가격비교 비매칭 일반상품" (standalone, not
# matched into a price-comparison catalog) -- the dropshipping-friendly kind.
# Everything else (대표/매칭) means catalog price-war exposure.
STANDALONE_PRODUCT_TYPES = frozenset({2, 5, 8, 11})

# Defaults
DEFAULT_MIN_MONTHLY_VOLUME = 1_000
DEFAULT_MAX_COMPETITION = 3.0
DEFAULT_MAX_CANDIDATES = 200
DEFAULT_TOP_N = 30
DEFAULT_SHOPPING_DISPLAY = 40

MomentumProvider = Callable[[str], Awaitable[list[float]]]


@dataclass
class DiscoveryCandidate:
    """A scored opportunity keyword produced by the pipeline."""

    keyword: str
    monthly_volume: int
    monthly_pc: int = 0
    monthly_mobile: int = 0
    product_count: int = 0
    competition: float = 0.0
    grade: CompetitionGrade = CompetitionGrade.SATURATED
    catalog_ratio: float = 0.0
    price_median: int = 0
    comp_idx: str = ""
    volume_masked: bool = False
    momentum: MomentumResult | None = None
    opportunity: float = 0.0
    evidence: dict = field(default_factory=dict)

    @property
    def grade_ko(self) -> str:
        return self.grade.label_ko


class DiscoveryPipeline:
    """Orchestrates the demand-first discovery stages."""

    def __init__(
        self,
        searchad_client: NaverSearchAdClient,
        shopping_client: NaverShoppingClient,
        *,
        momentum_provider: MomentumProvider | None = None,
        weights: OpportunityComponents = DEFAULT_WEIGHTS,
    ) -> None:
        """
        Args:
            searchad_client: Search Ad keyword-tool client (S1 demand).
            shopping_client: Shopping Search client (S2 supply).
            momentum_provider: Optional async ``keyword -> [ratio,...]`` provider
                (e.g. backed by DataLab) used to score trend momentum for the
                competition-filtered shortlist (S4).
            weights: Opportunity-score component weights.
        """
        self._searchad = searchad_client
        self._shopping = shopping_client
        self._momentum_provider = momentum_provider
        self._weights = weights

    # -- S1: demand expansion -------------------------------------------------

    async def expand_demand(
        self,
        seed_keywords: list[str],
        *,
        min_monthly_volume: int = DEFAULT_MIN_MONTHLY_VOLUME,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> list[DiscoveryCandidate]:
        """Expand seeds into related keywords with absolute monthly volume."""
        by_keyword: dict[str, DiscoveryCandidate] = {}

        for i in range(0, len(seed_keywords), SEED_BATCH_SIZE):
            batch = seed_keywords[i : i + SEED_BATCH_SIZE]
            try:
                stats = await self._searchad.get_keyword_stats(batch)
            except APIError as exc:
                logger.warning("discovery_expand_failed", batch=batch, error=str(exc))
                continue

            for s in stats:
                if not s.keyword or s.monthly_total < min_monthly_volume:
                    continue
                existing = by_keyword.get(s.keyword)
                if existing is None or s.monthly_total > existing.monthly_volume:
                    by_keyword[s.keyword] = DiscoveryCandidate(
                        keyword=s.keyword,
                        monthly_volume=s.monthly_total,
                        monthly_pc=s.monthly_pc,
                        monthly_mobile=s.monthly_mobile,
                        comp_idx=s.comp_idx,
                        volume_masked=s.is_masked,
                    )

        candidates = sorted(by_keyword.values(), key=lambda c: c.monthly_volume, reverse=True)
        return candidates[:max_candidates]

    # -- S2 + S3: supply + competition ----------------------------------------

    async def measure_competition(
        self,
        candidate: DiscoveryCandidate,
        *,
        display: int = DEFAULT_SHOPPING_DISPLAY,
    ) -> DiscoveryCandidate:
        """Fill in product count, competition intensity, catalog ratio, price."""
        result = await self._shopping.search(query=candidate.keyword, display=display)
        candidate.product_count = result.total

        candidate.competition = competition_intensity(result.total, candidate.monthly_volume)
        candidate.grade = grade_competition(candidate.competition)

        if result.items:
            standalone = sum(
                1 for it in result.items if it.product_type in STANDALONE_PRODUCT_TYPES
            )
            candidate.catalog_ratio = round(1.0 - standalone / len(result.items), 4)
            prices = [it.lowest_price for it in result.items if it.lowest_price > 0]
            candidate.price_median = int(statistics.median(prices)) if prices else 0

        return candidate

    # -- S7: orchestrate ------------------------------------------------------

    async def discover(
        self,
        seed_keywords: list[str],
        *,
        min_monthly_volume: int = DEFAULT_MIN_MONTHLY_VOLUME,
        max_competition: float = DEFAULT_MAX_COMPETITION,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        top_n: int = DEFAULT_TOP_N,
    ) -> list[DiscoveryCandidate]:
        """
        Run the full demand-first discovery and return the Top-N opportunities.

        Args:
            seed_keywords: Seed keywords/categories to expand from.
            min_monthly_volume: Drop keywords below this absolute monthly volume.
            max_competition: Drop keywords whose 경쟁강도 exceeds this.
            max_candidates: Cap on expanded candidates carried into S2.
            top_n: Number of ranked opportunities to return.

        Returns:
            ``DiscoveryCandidate`` list sorted by opportunity score (desc).
        """
        candidates = await self.expand_demand(
            seed_keywords,
            min_monthly_volume=min_monthly_volume,
            max_candidates=max_candidates,
        )
        logger.info("discovery_expanded", count=len(candidates))

        survivors: list[DiscoveryCandidate] = []
        for cand in candidates:
            try:
                await self.measure_competition(cand)
            except APIError as exc:
                logger.warning("discovery_measure_failed", keyword=cand.keyword, error=str(exc))
                continue
            if cand.competition <= max_competition:
                survivors.append(cand)

        logger.info("discovery_filtered", survivors=len(survivors))

        # S4: momentum for the shortlist only (quota-friendly).
        if self._momentum_provider is not None:
            await asyncio.gather(*(self._attach_momentum(c) for c in survivors))

        # S7: score and rank.
        for cand in survivors:
            cand.opportunity = opportunity_score(
                cand.monthly_volume,
                cand.competition,
                momentum=(cand.momentum.score / 100.0 if cand.momentum else None),
                margin_potential=None,  # filled after source matching (PLAN_v3 §3.1)
                sourcing_penalty=cand.catalog_ratio,
                weights=self._weights,
            )
            cand.evidence = {
                "monthly_volume": cand.monthly_volume,
                "product_count": cand.product_count,
                "competition": round(cand.competition, 4),
                "grade": cand.grade_ko,
                "catalog_ratio": cand.catalog_ratio,
                "price_median": cand.price_median,
                "momentum": cand.momentum.label.value if cand.momentum else None,
            }

        survivors.sort(key=lambda c: c.opportunity, reverse=True)
        return survivors[:top_n]

    async def _attach_momentum(self, candidate: DiscoveryCandidate) -> None:
        assert self._momentum_provider is not None
        try:
            series = await self._momentum_provider(candidate.keyword)
        except Exception as exc:  # noqa: BLE001 - provider failures must not kill the run
            logger.warning("discovery_momentum_failed", keyword=candidate.keyword, error=str(exc))
            return
        if series:
            candidate.momentum = momentum_score(series)
