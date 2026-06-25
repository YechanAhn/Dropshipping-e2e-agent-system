"""
DataLab-backed momentum provider for the discovery pipeline (S4).

Adapts ``NaverDataLabClient.get_keyword_trend`` (통합검색어 트렌드,
``/v1/datalab/search`` -- category-free) into the
``MomentumProvider = Callable[[str], Awaitable[list[float]]]`` contract that
``DiscoveryPipeline`` expects. Keeping the DataLab response-shape knowledge here
keeps ``pipeline/discovery.py`` decoupled from it.

The series is a relative 0-100 weekly ratio (``results[0].data[].ratio``).
``time_unit='week'`` is required because ``momentum_score`` is tuned for a weekly
cadence (RECENT_WINDOW/Z_WINDOW/YOY_PERIOD are all expressed in weeks).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from dropagent.clients.naver.datalab_api import NaverDataLabClient
from dropagent.clients.naver.models import NaverTrendResult

if TYPE_CHECKING:
    from dropagent.pipeline.discovery import MomentumProvider

# A 52-week YoY gate + a 4-week recent window need >= 56 weekly points to score
# fully (see ``core/discovery/momentum.py`` YOY_PERIOD + RECENT_WINDOW).
DATALAB_MOMENTUM_WEEKS = 56


def extract_ratios(result: NaverTrendResult) -> list[float]:
    """Flatten a single-keyword DataLab trend result into a ``list[float]``.

    A momentum query always sends exactly one keyword group, so only the first
    result group is read (never merge groups). Returns ``[]`` when the response
    has no groups or no data points, in which case the pipeline skips momentum
    scoring for that keyword.
    """
    if not result.results:
        return []
    return [item.ratio for item in result.results[0].data]


def make_datalab_momentum_provider(
    client: NaverDataLabClient,
    *,
    weeks: int = DATALAB_MOMENTUM_WEEKS,
    time_unit: str = "week",
    today: date | None = None,
) -> MomentumProvider:
    """Build a ``MomentumProvider`` closure backed by Naver DataLab.

    Args:
        client: DataLab client. Injected for testability; the caller owns its
            lifecycle (``close()``).
        weeks: Length of the trailing window to request (>= 56 for full
            momentum scoring).
        time_unit: DataLab aggregation unit. Must stay ``'week'`` to match
            ``momentum_score``'s weekly tuning; other units silently mis-scale
            every signal.
        today: Window end date (defaults to ``date.today()``; injectable for
            deterministic tests).

    Returns:
        An async ``keyword -> list[float]`` callable. Provider errors are
        deliberately propagated -- ``DiscoveryPipeline._attach_momentum``
        catches them and logs a warning, so one keyword's failure (e.g. a
        ``RateLimitError``) never kills the run while the real cause is kept.
    """

    async def _provider(keyword: str) -> list[float]:
        end = today or date.today()
        start = end - timedelta(weeks=weeks)
        result = await client.get_keyword_trend(
            [keyword],
            start.isoformat(),
            end.isoformat(),
            time_unit=time_unit,
        )
        return extract_ratios(result)

    return _provider
