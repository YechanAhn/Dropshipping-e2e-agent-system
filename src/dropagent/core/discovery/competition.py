"""
Competition intensity and opportunity scoring (demand-first discovery).

The Korean seller-tool consensus (ItemScout / PandaRank / SellerLife /
KeywordMaster / 셀러마스터 -- see ``docs/RESEARCH_discovery.md`` §2) defines
keyword competition as **supply ÷ demand**:

    경쟁강도 = 상품수(Naver Shopping total) ÷ 월간검색량(Search Ad)

Lower is better; ``< 1`` is a "golden keyword" (more searchers than sellers).
For multi-month windows the denominator is normalized to a per-month average.

``opportunity_score`` combines this with absolute demand, trend momentum,
margin potential, and a sourcing-risk penalty into a single 0..1 ranking score
that feeds the existing ``priority_scorer`` weighting/feedback loop.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

# --- Competition intensity grade bands (tunable) -----------------------------
# Thresholds on 경쟁강도 = product_count / monthly_volume. Lower = better.
GRADE_EXCELLENT_MAX = 0.5
GRADE_GOOD_MAX = 1.0
GRADE_FAIR_MAX = 3.0
GRADE_POOR_MAX = 10.0

# Monthly search volume that maps demand_score to ~1.0 (log scale).
DEMAND_VOLUME_REF = 100_000


class CompetitionGrade(StrEnum):
    """Ordinal competition grade (mirrors seller-tool 5-tier scales)."""

    EXCELLENT = "excellent"  # 아주좋음
    GOOD = "good"            # 좋음
    FAIR = "fair"            # 보통
    POOR = "poor"            # 나쁨
    SATURATED = "saturated"  # 아주나쁨

    @property
    def label_ko(self) -> str:
        return {
            CompetitionGrade.EXCELLENT: "아주좋음",
            CompetitionGrade.GOOD: "좋음",
            CompetitionGrade.FAIR: "보통",
            CompetitionGrade.POOR: "나쁨",
            CompetitionGrade.SATURATED: "아주나쁨",
        }[self]


def competition_intensity(
    product_count: int,
    monthly_volume: int,
    months: int = 1,
) -> float:
    """
    Compute 경쟁강도 = product_count ÷ (monthly_volume / months).

    Args:
        product_count: Number of competing products (Naver Shopping ``total``).
        monthly_volume: Total monthly search volume (PC + mobile) -- the demand.
        months: Lookup window in months; the volume is averaged per month
            (matches ItemScout's multi-month normalization).

    Returns:
        Competition intensity (lower is better). Returns ``inf`` when there is
        no measurable demand (``monthly_volume <= 0``).
    """
    if months < 1:
        raise ValueError("months must be >= 1")
    if monthly_volume <= 0:
        return math.inf
    avg_monthly = monthly_volume / months
    return product_count / avg_monthly


def grade_competition(intensity: float) -> CompetitionGrade:
    """Map a competition-intensity value onto an ordinal grade."""
    if intensity < GRADE_EXCELLENT_MAX:
        return CompetitionGrade.EXCELLENT
    if intensity < GRADE_GOOD_MAX:
        return CompetitionGrade.GOOD
    if intensity < GRADE_FAIR_MAX:
        return CompetitionGrade.FAIR
    if intensity < GRADE_POOR_MAX:
        return CompetitionGrade.POOR
    return CompetitionGrade.SATURATED


def demand_score(monthly_volume: int) -> float:
    """
    Map absolute monthly search volume to a 0..1 demand score (log-scaled).

    A keyword at ``DEMAND_VOLUME_REF`` searches/month scores ~1.0; smaller
    volumes scale down logarithmically. Non-positive volume scores 0.
    """
    if monthly_volume <= 0:
        return 0.0
    score = math.log10(monthly_volume + 1) / math.log10(DEMAND_VOLUME_REF)
    return max(0.0, min(1.0, score))


def competition_fit(intensity: float) -> float:
    """Map competition intensity (lower=better) to a 0..1 fit score (higher=better)."""
    if intensity == math.inf or intensity < 0:
        return 0.0
    return 1.0 / (1.0 + intensity)


@dataclass(frozen=True)
class OpportunityComponents:
    """Weights for the components of the opportunity score."""

    demand: float = 0.30
    competition: float = 0.30
    momentum: float = 0.20
    margin: float = 0.20
    # Penalty weight is applied on top (subtracted), not part of the convex sum.
    sourcing_penalty: float = 0.25


DEFAULT_WEIGHTS = OpportunityComponents()


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def opportunity_score(
    monthly_volume: int,
    intensity: float,
    *,
    momentum: float | None = None,
    margin_potential: float | None = None,
    sourcing_penalty: float = 0.0,
    weights: OpportunityComponents = DEFAULT_WEIGHTS,
) -> float:
    """
    Combine demand, competition, momentum, and margin into a 0..1 score.

    Components that are ``None`` (e.g. momentum before DataLab validation, or
    margin before source matching) are dropped and the remaining positive
    weights are renormalized, so a partial score is still comparable in range.
    ``sourcing_penalty`` (0..1, e.g. catalog-matched / brand / cert risk) is
    then subtracted with its own weight.

    Args:
        monthly_volume: Absolute monthly search volume (demand).
        intensity: Competition intensity (lower is better).
        momentum: Optional 0..1 trend-momentum score.
        margin_potential: Optional 0..1 margin-potential score.
        sourcing_penalty: Optional 0..1 sourcing-risk penalty.
        weights: Component weights.

    Returns:
        Opportunity score in ``[0, 1]``.
    """
    components: list[tuple[float, float]] = [
        (weights.demand, demand_score(monthly_volume)),
        (weights.competition, competition_fit(intensity)),
    ]
    if momentum is not None:
        components.append((weights.momentum, _clip01(momentum)))
    if margin_potential is not None:
        components.append((weights.margin, _clip01(margin_potential)))

    total_weight = sum(w for w, _ in components)
    if total_weight <= 0:
        return 0.0
    positive = sum(w * v for w, v in components) / total_weight

    penalty = weights.sourcing_penalty * _clip01(sourcing_penalty)
    return _clip01(positive - penalty)
