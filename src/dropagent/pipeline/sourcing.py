"""
Sourcing orchestrator: turn a demand-first opportunity into a listing.

Chains the leaf modules end-to-end (proving the value chain connects):

    NaverProductRef (from discovery)
      -> ProductMatcher.match           (find the same item on AliExpress)
      -> landed-cost estimate           (source price + shipping, FX, buffer)
      -> optimal_price                  (undercut competitors, keep margin)
      -> ContentGenerator.generate      (SEO title/description/keywords/category)
      -> build_register_payload         (Naver Commerce-ready payload)

Every external is injected so this is fully unit-testable without network.
Registration itself stays gated by HITL approval (status 'ready'/'review').
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from dropagent.core.content_generator import ContentGenerator, GeneratedContent
from dropagent.core.matching import MatchResult, MatchStatus, NaverProductRef, ProductMatcher
from dropagent.core.pricing import (
    DEFAULT_TARGET_MARGIN,
    PricingResult,
    lowest_for_exposure,
    optimal_price,
)
from dropagent.pipeline.discovery import DiscoveryCandidate
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# Extra multiplier over (price+shipping) for FX spread / CS / return reserve.
DEFAULT_IMPORT_BUFFER = Decimal("0.10")


@dataclass
class SourcingResult:
    """Outcome of evaluating one opportunity into a (near) listing."""

    naver_ref: NaverProductRef
    status: str  # ready | review | rejected | infeasible
    match: MatchResult | None = None
    landed_cost: Decimal | None = None
    pricing: PricingResult | None = None
    pricing_strategy: str | None = None  # catalog_match | standalone
    content: GeneratedContent | None = None
    register_payload: dict | None = None
    notes: list[str] = field(default_factory=list)


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Best-effort attribute/key lookup across object or dict, nested by name."""
    cur = obj
    for name in names:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(name)
        else:
            cur = getattr(cur, name, None)
    return cur if cur is not None else default


def estimate_landed_cost(
    ali_product: Any,
    *,
    fx_rate: Decimal | None = None,
    import_buffer: Decimal = DEFAULT_IMPORT_BUFFER,
) -> Decimal:
    """
    Estimate the all-in source cost in KRW for an AliExpress product.

    Currency-aware. When the product is already priced in KRW (AliExpress
    ``target_currency=KRW``) no FX is applied::

        landed = (sale + shipping) * (1 + import_buffer)

    Otherwise the price is treated as USD and converted with ``fx_rate`` (the
    live USD->KRW rate the caller resolved); a non-KRW price with no ``fx_rate``
    is a programming error::

        landed = (sale_usd + shipping_usd) * fx_rate * (1 + import_buffer)
    """
    sale = _attr(ali_product, "price", "sale_price", default=None)
    if sale is None:
        sale = _attr(ali_product, "sale_price", default=0)
    ship = _attr(ali_product, "shipping_info", "cost", default=0)
    sale_d = Decimal(str(sale or 0))
    ship_d = Decimal(str(ship or 0))
    base = sale_d + ship_d

    currency = (_attr(ali_product, "currency", default="USD") or "USD").upper()
    if currency != "KRW":
        if fx_rate is None:
            raise ValueError(
                "fx_rate is required to convert a non-KRW AliExpress price to KRW"
            )
        base = base * Decimal(str(fx_rate))

    return (base * (Decimal("1") + import_buffer)).quantize(Decimal("1"))


class SourcingOrchestrator:
    """Evaluate opportunities into registration-ready listings (HITL-gated)."""

    def __init__(
        self,
        matcher: ProductMatcher,
        content_generator: ContentGenerator,
        *,
        fx_rate: Decimal | None = None,
        import_buffer: Decimal = DEFAULT_IMPORT_BUFFER,
        target_margin: Decimal = DEFAULT_TARGET_MARGIN,
    ) -> None:
        self._matcher = matcher
        self._content = content_generator
        # ``None`` -> resolve the live USD->KRW rate lazily on first non-KRW use.
        self._fx_rate = fx_rate
        self._resolved_fx: Decimal | None = None
        self._import_buffer = import_buffer
        self._target_margin = target_margin

    async def _get_fx_rate(self) -> Decimal:
        """Return the USD->KRW rate, resolving it live on first use (cached)."""
        if self._resolved_fx is not None:
            return self._resolved_fx
        if self._fx_rate is not None:
            self._resolved_fx = Decimal(str(self._fx_rate))
            return self._resolved_fx

        from dropagent.clients.exchange_rate import ExchangeRateClient

        client = ExchangeRateClient()
        try:
            self._resolved_fx = await client.get_rate("USD", "KRW")
        finally:
            await client.close()
        return self._resolved_fx

    async def evaluate(
        self,
        naver_ref: NaverProductRef,
        competitor_prices: list[int],
        *,
        catalog_lowest: int = 0,
        market_floor: int | None = None,
    ) -> SourcingResult:
        """Run match -> price -> content for a single opportunity.

        Pricing strategy is chosen from the competitive shape:
          - ``catalog_lowest > 0`` (가격비교 카탈로그가 지배적) -> ``catalog_match``:
            target the catalog 최저가 for exposure via :func:`lowest_for_exposure`
            (a new seller must match 최저가 to be shown), never below the margin floor.
          - otherwise -> ``standalone``: keep our own SEO 상품명 and undercut p25 via
            :func:`optimal_price`.
        """
        result = SourcingResult(naver_ref=naver_ref, status="rejected")

        match = await self._matcher.match(naver_ref)
        result.match = match
        if match.status == MatchStatus.REJECT or match.best is None:
            result.notes.append("no plausible AliExpress match")
            return result

        ali = match.best.ali_product
        currency = (getattr(ali, "currency", "USD") or "USD").upper()
        fx = None if currency == "KRW" else await self._get_fx_rate()
        landed = estimate_landed_cost(ali, fx_rate=fx, import_buffer=self._import_buffer)
        result.landed_cost = landed

        if catalog_lowest and catalog_lowest > 0:
            result.pricing_strategy = "catalog_match"
            pricing = lowest_for_exposure(
                landed,
                catalog_lowest,
                market_floor=market_floor,
                target_margin=self._target_margin,
            )
        else:
            result.pricing_strategy = "standalone"
            pricing = optimal_price(landed, competitor_prices, target_margin=self._target_margin)
        result.pricing = pricing
        if not pricing.feasible:
            result.status = "infeasible"
            result.notes.append(f"pricing infeasible: {pricing.reason}")
            return result

        content = await self._content.generate(ali, target_keyword=naver_ref.title_ko)
        result.content = content
        result.register_payload = self._content.build_register_payload(
            content, pricing.recommended_price
        )

        result.status = "ready" if match.status == MatchStatus.AUTO else "review"
        if content.warnings:
            result.notes.extend(content.warnings)
        return result

    async def evaluate_candidate(
        self,
        candidate: DiscoveryCandidate,
        competitor_prices: list[int] | None = None,
    ) -> SourcingResult:
        """Adapt a discovery candidate (keyword + median price) and evaluate it."""
        naver_ref = NaverProductRef(
            title_ko=candidate.keyword,
            price=candidate.price_median or 0,
            image_url=candidate.image_url,
            category=candidate.evidence.get("grade", "") if candidate.evidence else "",
        )
        prices = competitor_prices if competitor_prices is not None else (
            [candidate.price_median] if candidate.price_median else []
        )
        # 카탈로그가 있으면 최저가 매칭(노출) 전략, 없으면 단독 언더컷.
        return await self.evaluate(
            naver_ref,
            prices,
            catalog_lowest=candidate.catalog_lowest,
            market_floor=candidate.price_min or None,
        )
