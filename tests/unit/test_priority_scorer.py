"""
Tests for PriorityScorer.

Covers:
    - Scoring with default weights
    - Scoring with custom weights
    - Rank label assignment (S/A/B/C/D thresholds)
    - Input clamping (values >1 or <0)
    - batch_calculate returns sorted results
    - normalize() static method
"""

import pytest

from dropagent.core.priority_scorer import (
    PriorityResult,
    PriorityScorer,
    ScoringWeights,
    _clamp,
    _determine_rank,
)

# =====================================================================
# ScoringWeights validation
# =====================================================================

class TestScoringWeights:
    """Tests for the ScoringWeights dataclass."""

    def test_default_weights_sum_to_one(self):
        """Default weights sum to 1.0."""
        w = ScoringWeights()
        total = w.w1_margin + w.w2_demand + w.w3_risk + w.w4_ops_cost + w.w5_supplier
        assert abs(total - 1.0) < 0.01

    def test_custom_valid_weights(self):
        """Custom weights that sum to 1.0 are accepted."""
        w = ScoringWeights(
            w1_margin=0.50,
            w2_demand=0.20,
            w3_risk=0.10,
            w4_ops_cost=0.10,
            w5_supplier=0.10,
        )
        assert w.w1_margin == 0.50

    def test_invalid_weights_sum_raises(self):
        """Weights that don't sum to ~1.0 raise ValueError."""
        with pytest.raises(ValueError, match="1.0"):
            ScoringWeights(
                w1_margin=0.5,
                w2_demand=0.5,
                w3_risk=0.5,
                w4_ops_cost=0.5,
                w5_supplier=0.5,
            )

    def test_negative_weight_raises(self):
        """Negative weights raise ValueError."""
        with pytest.raises(ValueError, match="음수"):
            ScoringWeights(
                w1_margin=-0.1,
                w2_demand=0.35,
                w3_risk=0.25,
                w4_ops_cost=0.25,
                w5_supplier=0.25,
            )


# =====================================================================
# Scoring with default weights
# =====================================================================

class TestCalculateDefaultWeights:
    """Tests for PriorityScorer.calculate() with default weights."""

    def test_perfect_scores_yield_high_priority(self, priority_scorer):
        """Best possible inputs produce a high score (S rank)."""
        result = priority_scorer.calculate(
            margin_score=1.0,
            demand_score=1.0,
            risk_score=0.0,
            ops_cost_score=0.0,
            supplier_reliability=1.0,
        )
        assert isinstance(result, PriorityResult)
        # w1*1 + w2*1 - w3*0 - w4*0 + w5*1 = 0.35+0.25+0.10 = 0.70
        assert result.score == pytest.approx(0.70, abs=0.01)
        assert result.rank_label == "A"

    def test_worst_scores_yield_low_priority(self, priority_scorer):
        """Worst possible inputs produce lowest score (D rank)."""
        result = priority_scorer.calculate(
            margin_score=0.0,
            demand_score=0.0,
            risk_score=1.0,
            ops_cost_score=1.0,
            supplier_reliability=0.0,
        )
        # 0 + 0 - 0.15 - 0.15 + 0 = -0.30 -> clamped to 0.0
        assert result.score == pytest.approx(0.0, abs=0.01)
        assert result.rank_label == "D"

    def test_docstring_example(self, priority_scorer):
        """Verifies expected score for the docstring example inputs.

        0.35*0.8 + 0.25*0.6 - 0.15*0.2 - 0.15*0.3 + 0.10*0.7 = 0.425 -> B rank.
        """
        result = priority_scorer.calculate(
            margin_score=0.8,
            demand_score=0.6,
            risk_score=0.2,
            ops_cost_score=0.3,
            supplier_reliability=0.7,
        )
        assert result.score == pytest.approx(0.425, abs=0.01)
        assert result.rank_label == "B"

    def test_result_has_breakdown(self, priority_scorer):
        """Result includes a breakdown dict with all expected keys."""
        result = priority_scorer.calculate(
            margin_score=0.5,
            demand_score=0.5,
            risk_score=0.5,
            ops_cost_score=0.5,
            supplier_reliability=0.5,
        )
        expected_keys = {
            "margin_score", "demand_score", "risk_score",
            "ops_cost_score", "supplier_reliability",
            "weighted_margin", "weighted_demand", "weighted_risk",
            "weighted_ops_cost", "weighted_supplier",
        }
        assert set(result.breakdown.keys()) == expected_keys

    def test_product_id_is_preserved(self, priority_scorer):
        """product_id passed to calculate() is returned in result."""
        result = priority_scorer.calculate(
            margin_score=0.5,
            demand_score=0.5,
            risk_score=0.5,
            ops_cost_score=0.5,
            supplier_reliability=0.5,
            product_id="PROD-001",
        )
        assert result.product_id == "PROD-001"


# =====================================================================
# Scoring with custom weights
# =====================================================================

class TestCalculateCustomWeights:
    """Tests for PriorityScorer.calculate() with custom weights."""

    def test_margin_heavy_weights(self):
        """Margin-heavy weighting boosts score when margin is high."""
        weights = ScoringWeights(
            w1_margin=0.60,
            w2_demand=0.10,
            w3_risk=0.10,
            w4_ops_cost=0.10,
            w5_supplier=0.10,
        )
        scorer = PriorityScorer(weights=weights)
        result = scorer.calculate(
            margin_score=1.0,
            demand_score=0.3,
            risk_score=0.3,
            ops_cost_score=0.3,
            supplier_reliability=0.3,
        )
        # 0.6*1 + 0.1*0.3 - 0.1*0.3 - 0.1*0.3 + 0.1*0.3 = 0.6
        assert result.score == pytest.approx(0.60, abs=0.01)

    def test_equal_weights(self):
        """Equal weights across all dimensions."""
        weights = ScoringWeights(
            w1_margin=0.20,
            w2_demand=0.20,
            w3_risk=0.20,
            w4_ops_cost=0.20,
            w5_supplier=0.20,
        )
        scorer = PriorityScorer(weights=weights)
        result = scorer.calculate(
            margin_score=0.5,
            demand_score=0.5,
            risk_score=0.5,
            ops_cost_score=0.5,
            supplier_reliability=0.5,
        )
        # 0.2*0.5 + 0.2*0.5 - 0.2*0.5 - 0.2*0.5 + 0.2*0.5 = 0.1
        assert result.score == pytest.approx(0.10, abs=0.01)


# =====================================================================
# Rank label assignment
# =====================================================================

class TestRankDetermination:
    """Tests for _determine_rank() and rank labels."""

    def test_s_rank(self):
        """Score > 0.8 yields S rank."""
        assert _determine_rank(0.85) == "S"
        assert _determine_rank(0.95) == "S"

    def test_a_rank(self):
        """Score > 0.6 and <= 0.8 yields A rank."""
        assert _determine_rank(0.65) == "A"
        assert _determine_rank(0.80) == "A"  # exactly 0.8 is not > 0.8

    def test_b_rank(self):
        """Score > 0.4 and <= 0.6 yields B rank."""
        assert _determine_rank(0.45) == "B"
        assert _determine_rank(0.60) == "B"

    def test_c_rank(self):
        """Score > 0.2 and <= 0.4 yields C rank."""
        assert _determine_rank(0.25) == "C"
        assert _determine_rank(0.40) == "C"

    def test_d_rank(self):
        """Score <= 0.2 yields D rank."""
        assert _determine_rank(0.20) == "D"
        assert _determine_rank(0.10) == "D"
        assert _determine_rank(0.0) == "D"

    def test_boundary_at_0_8(self):
        """0.8 exactly is A, not S (threshold is strict >)."""
        assert _determine_rank(0.8) == "A"

    def test_boundary_at_0_2(self):
        """0.2 exactly is D, not C (threshold is strict >)."""
        assert _determine_rank(0.2) == "D"


# =====================================================================
# Input clamping
# =====================================================================

class TestInputClamping:
    """Tests for input value clamping in PriorityScorer."""

    def test_values_above_one_are_clamped(self, priority_scorer):
        """Values > 1.0 are clamped to 1.0."""
        result = priority_scorer.calculate(
            margin_score=1.5,
            demand_score=2.0,
            risk_score=0.0,
            ops_cost_score=0.0,
            supplier_reliability=1.5,
        )
        assert result.breakdown["margin_score"] == 1.0
        assert result.breakdown["demand_score"] == 1.0
        assert result.breakdown["supplier_reliability"] == 1.0

    def test_values_below_zero_are_clamped(self, priority_scorer):
        """Values < 0.0 are clamped to 0.0."""
        result = priority_scorer.calculate(
            margin_score=-0.5,
            demand_score=-1.0,
            risk_score=0.0,
            ops_cost_score=0.0,
            supplier_reliability=-0.2,
        )
        assert result.breakdown["margin_score"] == 0.0
        assert result.breakdown["demand_score"] == 0.0
        assert result.breakdown["supplier_reliability"] == 0.0

    def test_clamp_helper(self):
        """_clamp() works as expected."""
        assert _clamp(1.5) == 1.0
        assert _clamp(-0.5) == 0.0
        assert _clamp(0.5) == 0.5
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0


# =====================================================================
# batch_calculate
# =====================================================================

class TestBatchCalculate:
    """Tests for PriorityScorer.batch_calculate()."""

    def test_results_sorted_descending(self, priority_scorer):
        """batch_calculate returns results sorted by score descending."""
        products = [
            {
                "margin_score": 0.4,
                "demand_score": 0.3,
                "risk_score": 0.6,
                "ops_cost_score": 0.7,
                "supplier_reliability": 0.5,
                "product_id": "LOW",
            },
            {
                "margin_score": 0.9,
                "demand_score": 0.7,
                "risk_score": 0.1,
                "ops_cost_score": 0.2,
                "supplier_reliability": 0.8,
                "product_id": "HIGH",
            },
            {
                "margin_score": 0.6,
                "demand_score": 0.5,
                "risk_score": 0.3,
                "ops_cost_score": 0.4,
                "supplier_reliability": 0.6,
                "product_id": "MID",
            },
        ]
        results = priority_scorer.batch_calculate(products)
        assert len(results) == 3
        assert results[0].product_id == "HIGH"
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_list_returns_empty(self, priority_scorer):
        """Empty product list returns empty results."""
        results = priority_scorer.batch_calculate([])
        assert results == []

    def test_single_product(self, priority_scorer):
        """Single product returns a list of one result."""
        products = [
            {
                "margin_score": 0.7,
                "demand_score": 0.5,
                "risk_score": 0.3,
                "ops_cost_score": 0.3,
                "supplier_reliability": 0.6,
                "product_id": "ONLY",
            },
        ]
        results = priority_scorer.batch_calculate(products)
        assert len(results) == 1
        assert results[0].product_id == "ONLY"

    def test_missing_keys_default_to_zero(self, priority_scorer):
        """Missing score keys default to 0.0 via dict.get()."""
        products = [{"product_id": "MINIMAL"}]
        results = priority_scorer.batch_calculate(products)
        assert len(results) == 1
        assert results[0].product_id == "MINIMAL"
        assert results[0].score >= 0.0


# =====================================================================
# normalize() static method
# =====================================================================

class TestNormalize:
    """Tests for PriorityScorer.normalize()."""

    def test_midpoint(self):
        """Midpoint of range normalizes to 0.5."""
        result = PriorityScorer.normalize(50, 0, 100)
        assert result == pytest.approx(0.5)

    def test_minimum(self):
        """Minimum value normalizes to 0.0."""
        result = PriorityScorer.normalize(0, 0, 100)
        assert result == pytest.approx(0.0)

    def test_maximum(self):
        """Maximum value normalizes to 1.0."""
        result = PriorityScorer.normalize(100, 0, 100)
        assert result == pytest.approx(1.0)

    def test_above_max_clamped(self):
        """Values above max_val are clamped to 1.0."""
        result = PriorityScorer.normalize(150, 0, 100)
        assert result == pytest.approx(1.0)

    def test_below_min_clamped(self):
        """Values below min_val are clamped to 0.0."""
        result = PriorityScorer.normalize(-50, 0, 100)
        assert result == pytest.approx(0.0)

    def test_equal_min_max_returns_half(self):
        """When min == max, returns 0.5 (avoids division by zero)."""
        result = PriorityScorer.normalize(10, 10, 10)
        assert result == pytest.approx(0.5)

    def test_custom_range(self):
        """Normalization with custom min/max range."""
        result = PriorityScorer.normalize(75, 50, 100)
        assert result == pytest.approx(0.5)

    def test_integer_inputs(self):
        """Handles integer inputs correctly."""
        result = PriorityScorer.normalize(3, 0, 10)
        assert result == pytest.approx(0.3)
