"""Unit tests for the sourcing orchestrator (match -> price -> content chain)."""

from decimal import Decimal
from types import SimpleNamespace

from dropagent.core.content_generator import GeneratedContent
from dropagent.core.matching.models import (
    MatchCandidate,
    MatchResult,
    MatchStatus,
    NaverProductRef,
)
from dropagent.pipeline.sourcing import SourcingOrchestrator, estimate_landed_cost


def _ali(sale_usd: str, ship_usd: str = "2"):
    return SimpleNamespace(
        product_id="ALI1",
        title="wireless earbuds",
        image_url="http://img/1.jpg",
        price=SimpleNamespace(sale_price=Decimal(sale_usd)),
        shipping_info=SimpleNamespace(cost=Decimal(ship_usd)),
    )


class FakeMatcher:
    def __init__(self, result: MatchResult):
        self._result = result

    async def match(self, naver, **_):
        return self._result


class FakeContent:
    async def generate(self, ali_product, *, target_keyword=None):
        return GeneratedContent(
            title_ko="무선 이어폰 블루투스",
            description_html="<p>설명</p>",
            keywords=["무선이어폰", "블루투스이어폰"],
            naver_category_id="50000204",
            naver_category_name="디지털/가전",
            source_image_urls=["http://img/1.jpg"],
            warnings=[],
        )

    def build_register_payload(self, content, price, *, stock=999, **extra):
        return {"originProduct": {"name": content.title_ko, "salePrice": price, "stockQuantity": stock}}


def _match(status: MatchStatus, ali=None) -> MatchResult:
    best = None if ali is None else MatchCandidate(
        ali_product=ali, title_similarity=0.9, price_ratio=0.3, confidence=0.9, reason="ok"
    )
    return MatchResult(status=status, query_en="wireless earbuds", best=best, candidates=[] if best is None else [best])


REF = NaverProductRef(title_ko="무선이어폰", price=30000)


def test_estimate_landed_cost():
    # (5 + 2) * 1350 * 1.10 = 10395
    assert estimate_landed_cost(_ali("5", "2")) == Decimal("10395")


async def test_ready_path_produces_payload():
    orch = SourcingOrchestrator(FakeMatcher(_match(MatchStatus.AUTO, _ali("5"))), FakeContent())
    res = await orch.evaluate(REF, competitor_prices=[28000, 30000, 32000])
    assert res.status == "ready"
    assert res.pricing is not None and res.pricing.feasible
    assert res.register_payload["originProduct"]["salePrice"] == res.pricing.recommended_price
    assert res.content is not None


async def test_review_status_when_match_is_review():
    orch = SourcingOrchestrator(FakeMatcher(_match(MatchStatus.REVIEW, _ali("5"))), FakeContent())
    res = await orch.evaluate(REF, competitor_prices=[28000, 30000, 32000])
    assert res.status == "review"
    assert res.register_payload is not None


async def test_rejected_when_no_match():
    orch = SourcingOrchestrator(FakeMatcher(_match(MatchStatus.REJECT, None)), FakeContent())
    res = await orch.evaluate(REF, competitor_prices=[28000, 30000])
    assert res.status == "rejected"
    assert res.pricing is None
    assert res.register_payload is None


async def test_infeasible_when_competition_below_floor():
    # cheap competitors vs ~10,395 landed -> margin floor unreachable
    orch = SourcingOrchestrator(FakeMatcher(_match(MatchStatus.AUTO, _ali("5"))), FakeContent())
    res = await orch.evaluate(REF, competitor_prices=[8000, 9000])
    assert res.status == "infeasible"
    assert res.pricing is not None and res.pricing.feasible is False
    assert res.register_payload is None


async def test_evaluate_candidate_threads_image_url():
    """evaluate_candidate carries the discovery image into NaverProductRef."""
    from dropagent.pipeline.discovery import DiscoveryCandidate

    captured: dict = {}

    class CapturingMatcher:
        async def match(self, naver, **_):
            captured["ref"] = naver
            return _match(MatchStatus.REJECT, None)

    orch = SourcingOrchestrator(CapturingMatcher(), FakeContent())
    cand = DiscoveryCandidate(
        keyword="골전도 러닝 이어폰",
        monthly_volume=10_000,
        price_median=29_000,
        image_url="http://img/naver.jpg",
    )

    await orch.evaluate_candidate(cand)

    assert captured["ref"].title_ko == "골전도 러닝 이어폰"
    assert captured["ref"].image_url == "http://img/naver.jpg"
    assert captured["ref"].price == 29_000
