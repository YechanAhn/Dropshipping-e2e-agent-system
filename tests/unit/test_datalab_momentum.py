"""Unit tests for the DataLab-backed momentum provider (no network, no creds)."""

from datetime import date

import pytest

from dropagent.clients.naver.models import (
    NaverTrendGroup,
    NaverTrendItem,
    NaverTrendResult,
)
from dropagent.core.discovery.datalab_momentum import (
    DATALAB_MOMENTUM_WEEKS,
    extract_ratios,
    make_datalab_momentum_provider,
)
from dropagent.core.discovery.momentum import momentum_score
from dropagent.utils.exceptions import RateLimitError


def _trend(ratios: list[float], *, title: str = "kw") -> NaverTrendResult:
    return NaverTrendResult(
        results=[
            NaverTrendGroup(
                title=title,
                keywords=[title],
                data=[
                    NaverTrendItem(period=f"2026-W{i:02d}", ratio=r)
                    for i, r in enumerate(ratios, start=1)
                ],
            )
        ]
    )


class FakeDataLabClient:
    """Records ``get_keyword_trend`` calls and returns a prebuilt result."""

    def __init__(
        self,
        result: NaverTrendResult | None = None,
        *,
        raises: Exception | None = None,
    ) -> None:
        self._result = result if result is not None else _trend([10.0, 20.0, 30.0])
        self._raises = raises
        self.calls: list[dict] = []
        self.closed = False

    async def get_keyword_trend(
        self,
        keywords: list[str],
        start_date: str,
        end_date: str,
        time_unit: str = "month",
    ) -> NaverTrendResult:
        self.calls.append(
            {
                "keywords": keywords,
                "start_date": start_date,
                "end_date": end_date,
                "time_unit": time_unit,
            }
        )
        if self._raises is not None:
            raise self._raises
        return self._result

    async def close(self) -> None:
        self.closed = True


# ── extract_ratios (pure helper) ───────────────────────────────────────────


def test_extract_ratios_single_group():
    assert extract_ratios(_trend([20.0, 25.5, 31.0])) == [20.0, 25.5, 31.0]


def test_extract_ratios_empty_results():
    assert extract_ratios(NaverTrendResult(results=[])) == []


def test_extract_ratios_empty_data():
    result = NaverTrendResult(
        results=[NaverTrendGroup(title="kw", keywords=["kw"], data=[])]
    )
    assert extract_ratios(result) == []


# ── provider behaviour ─────────────────────────────────────────────────────


async def test_provider_calls_client_with_week_unit_and_56wk_window():
    client = FakeDataLabClient(_trend([1.0, 2.0, 3.0]))
    provider = make_datalab_momentum_provider(client, today=date(2026, 6, 13))

    series = await provider("무선이어폰")

    assert series == [1.0, 2.0, 3.0]
    assert DATALAB_MOMENTUM_WEEKS == 56
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["keywords"] == ["무선이어폰"]  # always a single-element list
    assert call["time_unit"] == "week"
    assert call["end_date"] == "2026-06-13"
    assert call["start_date"] == "2025-05-17"  # exactly 56 weeks earlier


async def test_provider_empty_result_yields_empty_series():
    client = FakeDataLabClient(NaverTrendResult(results=[]))
    provider = make_datalab_momentum_provider(client, today=date(2026, 6, 13))
    assert await provider("kw") == []


async def test_provider_output_feeds_momentum_score_rising():
    rising = [float(x) for x in ([20.0] * 52 + [26, 30, 34, 38, 42, 46, 48, 50])]
    client = FakeDataLabClient(_trend(rising))
    provider = make_datalab_momentum_provider(client, today=date(2026, 6, 13))

    series = await provider("rising_kw")
    result = momentum_score(series)

    assert result.label.value == "rising"


async def test_provider_propagates_rate_limit_error():
    client = FakeDataLabClient(
        raises=RateLimitError(message="429", api_name="naver_datalab", retry_after=1)
    )
    provider = make_datalab_momentum_provider(client, today=date(2026, 6, 13))

    with pytest.raises(RateLimitError):
        await provider("kw")
