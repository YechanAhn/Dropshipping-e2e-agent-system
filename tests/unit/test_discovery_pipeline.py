"""Unit tests for the demand-first discovery pipeline (with mocked clients)."""

from datetime import date

import pytest

from dropagent.clients.naver.models import (
    NaverShoppingItem,
    NaverShoppingResult,
    NaverTrendGroup,
    NaverTrendItem,
    NaverTrendResult,
)
from dropagent.clients.naver.searchad_api import KeywordStat
from dropagent.core.discovery.competition import CompetitionGrade
from dropagent.core.discovery.datalab_momentum import make_datalab_momentum_provider
from dropagent.pipeline.discovery import DiscoveryCandidate, DiscoveryPipeline


class FakeSearchAd:
    """Returns a fixed related-keyword expansion regardless of the hint batch."""

    def __init__(self, stats: list[KeywordStat]):
        self._stats = stats

    async def get_keyword_stats(self, hint_keywords, include_hint_keywords=True):
        return self._stats


class FakeShopping:
    """Returns per-keyword (total, items) supply data from a lookup table."""

    def __init__(self, table: dict[str, NaverShoppingResult]):
        self._table = table

    async def search(self, query: str, display: int = 40, **_):
        return self._table.get(query, NaverShoppingResult(items=[], total=0))


def _result(total: int, product_type: int, price: int, n: int = 10) -> NaverShoppingResult:
    items = [
        NaverShoppingItem(lowest_price=price, product_type=product_type) for _ in range(n)
    ]
    return NaverShoppingResult(items=items, total=total, start=1, display=n)


async def test_discover_filters_and_ranks():
    stats = [
        KeywordStat(keyword="A_low_comp", monthly_pc=20000, monthly_mobile=30000),   # 50k
        KeywordStat(keyword="B_mid_comp", monthly_pc=20000, monthly_mobile=30000),   # 50k
        KeywordStat(keyword="C_saturated", monthly_pc=10000, monthly_mobile=20000),  # 30k
        KeywordStat(keyword="D_tiny", monthly_pc=100, monthly_mobile=100),           # 200 (dropped)
    ]
    table = {
        # A: 25k products / 50k searches = 0.5 (GOOD), standalone -> low penalty
        "A_low_comp": _result(25_000, product_type=2, price=19_900),
        # B: 140k / 50k = 2.8 (FAIR, survives), catalog-matched -> high penalty
        "B_mid_comp": _result(140_000, product_type=1, price=22_000),
        # C: 600k / 30k = 20 (SATURATED, filtered out by max_competition)
        "C_saturated": _result(600_000, product_type=1, price=15_000),
    }
    pipe = DiscoveryPipeline(FakeSearchAd(stats), FakeShopping(table))

    results = await pipe.discover(["seed"], min_monthly_volume=1_000, max_competition=3.0)

    keywords = [r.keyword for r in results]
    assert "A_low_comp" in keywords
    assert "B_mid_comp" in keywords
    assert "C_saturated" not in keywords  # competition too high
    assert "D_tiny" not in keywords       # below volume floor

    # Lower competition + cleaner sourcing should rank A above B.
    assert results[0].keyword == "A_low_comp"
    assert results[0].opportunity > results[1].opportunity

    top = results[0]
    assert top.product_count == 25_000
    assert top.grade == CompetitionGrade.GOOD
    assert top.price_median == 19_900
    assert top.evidence["grade"] == "좋음"


async def test_discover_uses_momentum_provider():
    stats = [KeywordStat(keyword="rising_kw", monthly_pc=20000, monthly_mobile=30000)]
    table = {"rising_kw": _result(25_000, product_type=2, price=10_000)}

    rising_series = [float(x) for x in ([20.0] * 52 + [26, 30, 34, 38, 42, 46, 48, 50])]

    async def provider(keyword: str) -> list[float]:
        return rising_series

    pipe = DiscoveryPipeline(FakeSearchAd(stats), FakeShopping(table), momentum_provider=provider)
    results = await pipe.discover(["seed"], min_monthly_volume=1_000)

    assert results[0].momentum is not None
    assert results[0].evidence["momentum"] == "rising"


async def test_discover_with_real_datalab_adapter():
    """The real ``make_datalab_momentum_provider`` plugs into the pipeline E2E."""
    stats = [KeywordStat(keyword="rising_kw", monthly_pc=20000, monthly_mobile=30000)]
    table = {"rising_kw": _result(25_000, product_type=2, price=10_000)}
    rising = [float(x) for x in ([20.0] * 52 + [26, 30, 34, 38, 42, 46, 48, 50])]

    class FakeDataLab:
        async def get_keyword_trend(self, keywords, start_date, end_date, time_unit="month"):
            return NaverTrendResult(
                results=[
                    NaverTrendGroup(
                        title=keywords[0],
                        keywords=keywords,
                        data=[
                            NaverTrendItem(period=str(i), ratio=r)
                            for i, r in enumerate(rising)
                        ],
                    )
                ]
            )

        async def close(self):
            return None

    provider = make_datalab_momentum_provider(FakeDataLab(), today=date(2026, 6, 13))
    pipe = DiscoveryPipeline(
        FakeSearchAd(stats), FakeShopping(table), momentum_provider=provider
    )
    results = await pipe.discover(["seed"], min_monthly_volume=1_000)

    assert results[0].momentum is not None
    assert results[0].evidence["momentum"] == "rising"


async def test_expand_demand_dedupes_and_floors():
    stats = [
        KeywordStat(keyword="dup", monthly_pc=10000, monthly_mobile=10000),
        KeywordStat(keyword="dup", monthly_pc=5000, monthly_mobile=5000),
        KeywordStat(keyword="below", monthly_pc=100, monthly_mobile=100),
    ]
    pipe = DiscoveryPipeline(FakeSearchAd(stats), FakeShopping({}))
    # exclude_head_terms=False to keep this test focused on dedup/floor behavior
    # (the short ASCII keywords would otherwise be dropped by the specificity gate).
    cands = await pipe.expand_demand(
        ["seed"], min_monthly_volume=1_000, exclude_head_terms=False
    )

    keywords = [c.keyword for c in cands]
    assert keywords == ["dup"]              # 'below' floored out, 'dup' deduped
    assert cands[0].monthly_volume == 20000  # keeps the higher-volume duplicate


async def test_discover_excludes_head_terms_keeps_longtail():
    """The default specificity gate drops seed/head terms and keeps long-tail."""
    stats = [
        # head term == seed -> dropped
        KeywordStat(keyword="무선 이어폰", monthly_pc=40000, monthly_mobile=60000),
        # bare single-token short head term -> dropped
        KeywordStat(keyword="이어폰", monthly_pc=40000, monthly_mobile=60000),
        # branded -> dropped
        KeywordStat(keyword="에어팟 케이스", monthly_pc=10000, monthly_mobile=10000),
        # long-tail child -> kept
        KeywordStat(keyword="골전도 러닝 이어폰", monthly_pc=8000, monthly_mobile=12000),
    ]
    table = {"골전도 러닝 이어폰": _result(5_000, product_type=2, price=29_000)}
    pipe = DiscoveryPipeline(FakeSearchAd(stats), FakeShopping(table))

    results = await pipe.discover(["무선 이어폰"], min_monthly_volume=1_000)

    keywords = [r.keyword for r in results]
    assert keywords == ["골전도 러닝 이어폰"]


async def test_discover_goldilocks_ceiling_drops_high_volume():
    """max_monthly_volume drops keywords above the band even if specific."""
    stats = [
        KeywordStat(keyword="골전도 러닝 이어폰", monthly_pc=3000, monthly_mobile=2000),   # 5k
        KeywordStat(keyword="유아용 식판 세트", monthly_pc=40000, monthly_mobile=60000),  # 100k
    ]
    table = {
        "골전도 러닝 이어폰": _result(2_000, product_type=2, price=29_000),
        "유아용 식판 세트": _result(20_000, product_type=2, price=12_000),
    }
    pipe = DiscoveryPipeline(FakeSearchAd(stats), FakeShopping(table))

    results = await pipe.discover(["seed"], min_monthly_volume=1_000, max_monthly_volume=10_000)

    keywords = [r.keyword for r in results]
    assert "골전도 러닝 이어폰" in keywords
    assert "유아용 식판 세트" not in keywords  # 100k > 10k ceiling


async def test_measure_competition_captures_representative_image():
    """measure_competition records a representative photo, preferring 비매칭 단독."""
    items = [
        NaverShoppingItem(lowest_price=12000, product_type=1, image="https://x/catalog.jpg"),
        NaverShoppingItem(lowest_price=9000, product_type=2, image="https://x/standalone.jpg"),
    ]
    table = {"골전도 이어폰": NaverShoppingResult(items=items, total=5_000)}
    pipe = DiscoveryPipeline(FakeSearchAd([]), FakeShopping(table))
    cand = DiscoveryCandidate(keyword="골전도 이어폰", monthly_volume=10_000)

    await pipe.measure_competition(cand)

    assert cand.image_url == "https://x/standalone.jpg"  # standalone preferred over catalog


async def test_rising_momentum_applies_opportunity_bonus():
    """A RISING candidate's opportunity gets the label bonus on top of the score."""
    from dropagent.core.discovery.competition import DEFAULT_WEIGHTS, opportunity_score
    from dropagent.core.discovery.momentum import momentum_opportunity_bonus

    stats = [KeywordStat(keyword="떠오르는 신상 키워드", monthly_pc=20000, monthly_mobile=30000)]
    table = {"떠오르는 신상 키워드": _result(25_000, product_type=2, price=10_000)}
    rising = [float(x) for x in ([20.0] * 52 + [26, 30, 34, 38, 42, 46, 48, 50])]

    async def provider(keyword: str) -> list[float]:
        return rising

    pipe = DiscoveryPipeline(FakeSearchAd(stats), FakeShopping(table), momentum_provider=provider)
    results = await pipe.discover(["seed"], min_monthly_volume=1_000)
    cand = results[0]
    assert cand.momentum is not None and cand.momentum.label.value == "rising"

    base = opportunity_score(
        cand.monthly_volume,
        cand.competition,
        momentum=cand.momentum.score / 100.0,
        margin_potential=None,
        sourcing_penalty=cand.catalog_ratio,
        weights=DEFAULT_WEIGHTS,
    )
    expected = max(0.0, min(1.0, base + momentum_opportunity_bonus(cand.momentum.label)))
    assert cand.opportunity == pytest.approx(expected)
    assert cand.opportunity > base  # rising was promoted
