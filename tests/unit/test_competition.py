"""Unit tests for the competition / opportunity scoring core."""

import math

from dropagent.core.discovery.competition import (
    CompetitionGrade,
    competition_fit,
    competition_intensity,
    demand_score,
    grade_competition,
    opportunity_score,
)

# --- competition_intensity ---------------------------------------------------

def test_competition_intensity_basic():
    # 5,000 products / 10,000 searches = 0.5
    assert competition_intensity(5000, 10000) == 0.5


def test_competition_intensity_zero_demand_is_inf():
    assert competition_intensity(100, 0) == math.inf


def test_competition_intensity_multi_month_normalizes():
    # 6,000 products over 3 months vs 12,000/mo avg -> 6000 / (12000) ... here
    # monthly_volume is the *total* over the window: 36,000 / 3 = 12,000 avg.
    assert competition_intensity(6000, 36000, months=3) == 0.5


# --- grade_competition -------------------------------------------------------

def test_grade_bands():
    assert grade_competition(0.3) == CompetitionGrade.EXCELLENT
    assert grade_competition(0.9) == CompetitionGrade.GOOD
    assert grade_competition(2.0) == CompetitionGrade.FAIR
    assert grade_competition(5.0) == CompetitionGrade.POOR
    assert grade_competition(50.0) == CompetitionGrade.SATURATED


def test_grade_has_korean_label():
    assert grade_competition(0.3).label_ko == "아주좋음"


# --- demand_score ------------------------------------------------------------

def test_demand_score_bounds_and_monotonic():
    assert demand_score(0) == 0.0
    assert demand_score(100) < demand_score(10_000) < demand_score(1_000_000)
    assert 0.0 <= demand_score(5_000_000) <= 1.0


def test_demand_score_reference_is_near_one():
    assert demand_score(100_000) == 1.0


# --- competition_fit ---------------------------------------------------------

def test_competition_fit():
    assert competition_fit(0.0) == 1.0
    assert competition_fit(1.0) == 0.5
    assert competition_fit(math.inf) == 0.0


# --- opportunity_score -------------------------------------------------------

def test_opportunity_score_in_unit_range():
    s = opportunity_score(10_000, 0.5)
    assert 0.0 <= s <= 1.0


def test_opportunity_increases_with_volume():
    low = opportunity_score(1_000, 0.5)
    high = opportunity_score(100_000, 0.5)
    assert high > low


def test_opportunity_decreases_with_competition():
    easy = opportunity_score(10_000, 0.1)
    hard = opportunity_score(10_000, 5.0)
    assert easy > hard


def test_opportunity_momentum_helps():
    weak = opportunity_score(10_000, 0.5, momentum=0.1)
    strong = opportunity_score(10_000, 0.5, momentum=0.9)
    assert strong > weak


def test_opportunity_sourcing_penalty_hurts():
    clean = opportunity_score(10_000, 0.5, sourcing_penalty=0.0)
    risky = opportunity_score(10_000, 0.5, sourcing_penalty=1.0)
    assert clean > risky


def test_opportunity_handles_missing_optional_components():
    # With momentum/margin omitted the score still ranks within range.
    s = opportunity_score(50_000, 0.2)
    assert 0.0 <= s <= 1.0
