"""
Demand-first opportunity discovery.

Implements the scoring core described in ``docs/RESEARCH_discovery.md``:

- ``competition``: 경쟁강도 = 상품수 ÷ 월간검색량 (lower = better), opportunity scoring.
- ``momentum``: rising/seasonality detection on a relative 0-100 trend series.
"""

from .competition import (
    CompetitionGrade,
    OpportunityComponents,
    competition_intensity,
    demand_score,
    grade_competition,
    opportunity_score,
)
from .datalab_momentum import (
    DATALAB_MOMENTUM_WEEKS,
    extract_ratios,
    make_datalab_momentum_provider,
)
from .momentum import MomentumLabel, MomentumResult, momentum_score

__all__ = [
    "CompetitionGrade",
    "OpportunityComponents",
    "competition_intensity",
    "demand_score",
    "grade_competition",
    "opportunity_score",
    "MomentumLabel",
    "MomentumResult",
    "momentum_score",
    "DATALAB_MOMENTUM_WEEKS",
    "extract_ratios",
    "make_datalab_momentum_provider",
]
