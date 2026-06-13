"""Unit tests for the demand-first discovery pipeline (with mocked clients)."""

from datetime import date

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
from dropagent.pipeline.discovery import DiscoveryPipeline


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
    cands = await pipe.expand_demand(["seed"], min_monthly_volume=1_000)

    keywords = [c.keyword for c in cands]
    assert keywords == ["dup"]              # 'below' floored out, 'dup' deduped
    assert cands[0].monthly_volume == 20000  # keeps the higher-volume duplicate
