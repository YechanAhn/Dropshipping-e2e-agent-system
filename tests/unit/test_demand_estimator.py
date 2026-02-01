"""
Tests for DemandEstimator.

Covers:
    - Estimation with all inputs
    - Estimation with missing inputs (weight redistribution)
    - Confidence scoring
    - Boundary conditions
"""

import pytest

from dropagent.core.demand_estimator import (
    DemandEstimator,
    DemandResult,
)

# =====================================================================
# Estimation with all inputs
# =====================================================================

class TestEstimateAllInputs:
    """Tests for DemandEstimator.estimate() with all inputs provided."""

    def test_basic_estimation(self, demand_estimator):
        """All inputs provided produces a valid result."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=150,
            review_growth_rate=0.5,
            click_trend_ratio=0.7,
        )
        assert isinstance(result, DemandResult)
        assert 0.0 <= result.score <= 1.0
        assert result.confidence == 0.9  # all inputs -> high confidence

    def test_high_demand_scores_high(self, demand_estimator):
        """High search volume, reviews, and clicks yield high demand."""
        result = demand_estimator.estimate(
            keyword_search_volume=100000,
            review_count=500,
            review_growth_rate=1.8,
            click_trend_ratio=0.95,
        )
        assert result.score >= 0.7
        assert result.get_demand_level() in ("HIGH", "VERY_HIGH")

    def test_low_demand_scores_low(self, demand_estimator):
        """Low search volume, reviews, and clicks yield low demand."""
        result = demand_estimator.estimate(
            keyword_search_volume=100,
            review_count=2,
            review_growth_rate=0.01,
            click_trend_ratio=0.05,
        )
        assert result.score < 0.25
        assert result.get_demand_level() == "LOW"

    def test_components_are_present(self, demand_estimator):
        """Result components dict has all expected keys."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=100,
            review_growth_rate=0.5,
            click_trend_ratio=0.6,
        )
        expected_keys = {
            "search_volume_score",
            "search_volume_raw",
            "review_growth_score",
            "review_growth_rate_raw",
            "review_count",
            "click_trend_score",
            "click_trend_ratio_raw",
        }
        assert set(result.components.keys()) == expected_keys

    def test_demand_levels(self, demand_estimator):
        """get_demand_level returns expected string."""
        valid_levels = {"LOW", "MEDIUM", "HIGH", "VERY_HIGH"}
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=100,
            review_growth_rate=0.5,
            click_trend_ratio=0.6,
        )
        assert result.get_demand_level() in valid_levels

    def test_docstring_example(self, demand_estimator):
        """Reproduces the docstring example."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=150,
            review_growth_rate=0.5,
            click_trend_ratio=0.7,
        )
        assert result.get_demand_level() == "MEDIUM"


# =====================================================================
# Missing inputs (weight redistribution)
# =====================================================================

class TestMissingInputs:
    """Tests for weight redistribution when inputs are missing."""

    def test_search_only(self, demand_estimator):
        """Search volume only yields low confidence."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
        )
        assert 0.0 <= result.score <= 1.0
        assert result.confidence == 0.35

    def test_search_and_review(self, demand_estimator):
        """Search + review yields medium confidence."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=100,
            review_growth_rate=0.5,
        )
        assert 0.0 <= result.score <= 1.0
        assert result.confidence == 0.6

    def test_search_and_click(self, demand_estimator):
        """Search + click yields 0.55 confidence."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            click_trend_ratio=0.7,
        )
        assert 0.0 <= result.score <= 1.0
        assert result.confidence == 0.55

    def test_no_review_count_but_has_growth_rate(self, demand_estimator):
        """If review_count is None, review is not used even if growth_rate is given."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=None,
            review_growth_rate=0.5,
        )
        # review_count is None so review is not considered
        assert result.components["review_growth_score"] == 0.0

    def test_missing_click_trend_uses_zero(self, demand_estimator):
        """Missing click_trend_ratio uses 0.0 in components."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=100,
            review_growth_rate=0.5,
        )
        assert result.components["click_trend_score"] == 0.0

    def test_weight_redistribution_search_only(self, demand_estimator):
        """Search-only: full weight goes to search (score = normalized search)."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
        )
        expected_search_score = 50000 / 100000  # 0.5
        assert result.score == pytest.approx(expected_search_score, abs=0.01)

    def test_estimate_from_search_only_convenience(self, demand_estimator):
        """estimate_from_search_only convenience method works."""
        result = demand_estimator.estimate_from_search_only(50000)
        assert isinstance(result, DemandResult)
        assert result.confidence == 0.35


# =====================================================================
# Confidence scoring
# =====================================================================

class TestConfidenceScoring:
    """Tests for _compute_confidence()."""

    def test_all_inputs_high_confidence(self):
        """All valid inputs yield 0.9 confidence."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=1000,
            review_count=50,
            review_growth_rate=0.3,
            click_trend_ratio=0.5,
        )
        assert conf == 0.9

    def test_search_and_review_medium_confidence(self):
        """Search + review (no click) yields 0.6 confidence."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=1000,
            review_count=50,
            review_growth_rate=0.3,
            click_trend_ratio=None,
        )
        assert conf == 0.6

    def test_search_and_click_confidence(self):
        """Search + click (no review) yields 0.55 confidence."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=1000,
            review_count=None,
            review_growth_rate=None,
            click_trend_ratio=0.5,
        )
        assert conf == 0.55

    def test_search_only_low_confidence(self):
        """Search only yields 0.35 confidence."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=1000,
            review_count=None,
            review_growth_rate=None,
            click_trend_ratio=None,
        )
        assert conf == 0.35

    def test_zero_search_volume_very_low_confidence(self):
        """Zero search volume yields 0.1 confidence."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=0,
            review_count=None,
            review_growth_rate=None,
            click_trend_ratio=None,
        )
        assert conf == 0.1

    def test_zero_search_but_other_inputs(self):
        """Zero search but valid review and click yields 0.1 confidence."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=0,
            review_count=100,
            review_growth_rate=0.5,
            click_trend_ratio=0.7,
        )
        assert conf == 0.1

    def test_review_count_zero_not_treated_as_valid(self):
        """Review count of 0 means review is not considered valid."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=1000,
            review_count=0,
            review_growth_rate=0.5,
            click_trend_ratio=None,
        )
        assert conf == 0.35  # search only

    def test_click_trend_zero_not_treated_as_valid(self):
        """Click trend ratio of 0 is not treated as valid."""
        conf = DemandEstimator._compute_confidence(
            keyword_search_volume=1000,
            review_count=None,
            review_growth_rate=None,
            click_trend_ratio=0.0,
        )
        assert conf == 0.35  # search only


# =====================================================================
# Boundary conditions
# =====================================================================

class TestBoundaryConditions:
    """Tests for boundary conditions."""

    def test_max_search_volume(self, demand_estimator):
        """Search volume at max threshold normalizes to 1.0."""
        result = demand_estimator.estimate(
            keyword_search_volume=100_000,
        )
        assert result.components["search_volume_score"] == pytest.approx(1.0)

    def test_over_max_search_volume_clamped(self, demand_estimator):
        """Search volume over max threshold is clamped to 1.0."""
        result = demand_estimator.estimate(
            keyword_search_volume=200_000,
        )
        assert result.components["search_volume_score"] == pytest.approx(1.0)

    def test_zero_search_volume(self, demand_estimator):
        """Zero search volume normalizes to 0.0."""
        result = demand_estimator.estimate(
            keyword_search_volume=0,
        )
        assert result.components["search_volume_score"] == pytest.approx(0.0)

    def test_max_review_growth_rate(self, demand_estimator):
        """Review growth at max threshold normalizes to 1.0."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=100,
            review_growth_rate=2.0,
        )
        assert result.components["review_growth_score"] == pytest.approx(1.0)

    def test_negative_review_growth_clamped(self, demand_estimator):
        """Negative review growth rate is clamped to 0.0."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            review_count=100,
            review_growth_rate=-0.5,
        )
        assert result.components["review_growth_score"] == pytest.approx(0.0)

    def test_click_trend_at_max(self, demand_estimator):
        """Click trend at max (1.0) normalizes to 1.0."""
        result = demand_estimator.estimate(
            keyword_search_volume=50000,
            click_trend_ratio=1.0,
        )
        assert result.components["click_trend_score"] == pytest.approx(1.0)

    def test_score_always_between_zero_and_one(self, demand_estimator):
        """Score is always between 0 and 1 regardless of inputs."""
        for sv in [0, 50000, 200000]:
            for rg in [None, -1.0, 0.5, 3.0]:
                for ct in [None, 0.0, 0.5, 2.0]:
                    result = demand_estimator.estimate(
                        keyword_search_volume=sv,
                        review_count=100 if rg is not None else None,
                        review_growth_rate=rg,
                        click_trend_ratio=ct,
                    )
                    assert 0.0 <= result.score <= 1.0


# =====================================================================
# Custom thresholds and weights
# =====================================================================

class TestCustomConfiguration:
    """Tests for custom weights and thresholds."""

    def test_invalid_weight_sum_raises(self):
        """Weights not summing to ~1.0 raises ValueError."""
        with pytest.raises(ValueError, match="1.0"):
            DemandEstimator(
                search_volume_weight=0.5,
                review_growth_weight=0.5,
                click_trend_weight=0.5,
            )

    def test_custom_thresholds(self):
        """Custom thresholds change normalization."""
        custom = DemandEstimator(
            thresholds={
                "search_volume": {"min": 0, "max": 50000},
                "review_growth_rate": {"min": 0.0, "max": 2.0},
                "click_trend_ratio": {"min": 0.0, "max": 1.0},
            }
        )
        result = custom.estimate(keyword_search_volume=50000)
        assert result.components["search_volume_score"] == pytest.approx(1.0)

    def test_estimate_monthly_sales(self, demand_estimator):
        """estimate_monthly_sales produces reasonable output."""
        sales = demand_estimator.estimate_monthly_sales(0.7)
        # 0.7 * 10000 * 0.02 * 0.10 = 14
        assert sales == 14

    def test_estimate_monthly_sales_zero_demand(self, demand_estimator):
        """Zero demand yields zero sales."""
        sales = demand_estimator.estimate_monthly_sales(0.0)
        assert sales == 0

    def test_estimate_monthly_sales_custom_rates(self, demand_estimator):
        """Custom conversion and market share change output."""
        sales = demand_estimator.estimate_monthly_sales(
            0.5,
            avg_conversion_rate=0.05,
            market_share=0.20,
        )
        # 0.5 * 10000 * 0.05 * 0.20 = 50
        assert sales == 50
