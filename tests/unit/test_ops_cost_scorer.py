"""
Tests for OpsCostScorer.

Covers:
    - Option complexity scoring at boundaries
    - Page difficulty with/without size chart
    - CS volume estimation by category
    - Return rate handling
    - Overall ops cost score
"""

import pytest

from dropagent.core.ops_cost_scorer import (
    DEFAULT_CS_RATE,
    DEFAULT_RETURN_RATE,
    OpsCostResult,
    OpsCostScorer,
)

# =====================================================================
# Option complexity
# =====================================================================

class TestOptionComplexity:
    """Tests for OpsCostScorer._option_complexity()."""

    def test_10_plus_options(self):
        """10+ options returns 0.9."""
        assert OpsCostScorer._option_complexity(10) == 0.9
        assert OpsCostScorer._option_complexity(20) == 0.9

    def test_5_to_9_options(self):
        """5-9 options returns 0.6."""
        assert OpsCostScorer._option_complexity(5) == 0.6
        assert OpsCostScorer._option_complexity(9) == 0.6

    def test_3_to_4_options(self):
        """3-4 options returns 0.3."""
        assert OpsCostScorer._option_complexity(3) == 0.3
        assert OpsCostScorer._option_complexity(4) == 0.3

    def test_under_3_options(self):
        """Under 3 options returns 0.1."""
        assert OpsCostScorer._option_complexity(2) == 0.1
        assert OpsCostScorer._option_complexity(1) == 0.1
        assert OpsCostScorer._option_complexity(0) == 0.1

    def test_boundary_10(self):
        """Exactly 10 is in highest tier."""
        assert OpsCostScorer._option_complexity(10) == 0.9

    def test_boundary_5(self):
        """Exactly 5 is in the second tier."""
        assert OpsCostScorer._option_complexity(5) == 0.6

    def test_boundary_3(self):
        """Exactly 3 is in the third tier."""
        assert OpsCostScorer._option_complexity(3) == 0.3


# =====================================================================
# Page difficulty
# =====================================================================

class TestPageDifficulty:
    """Tests for OpsCostScorer._page_difficulty()."""

    def test_with_size_chart(self):
        """Size chart required returns 0.5."""
        assert OpsCostScorer._page_difficulty(True) == 0.5

    def test_without_size_chart(self):
        """No size chart returns 0.1."""
        assert OpsCostScorer._page_difficulty(False) == 0.1


# =====================================================================
# CS volume estimation
# =====================================================================

class TestCSVolumeEstimate:
    """Tests for OpsCostScorer._cs_volume_estimate()."""

    def test_fashion_high_cs(self, ops_cost_scorer):
        """Fashion clothing has high CS rate (0.8)."""
        rate = ops_cost_scorer._cs_volume_estimate("패션의류")
        assert rate == 0.8

    def test_books_low_cs(self, ops_cost_scorer):
        """Books have low CS rate (0.2)."""
        rate = ops_cost_scorer._cs_volume_estimate("도서")
        assert rate == 0.2

    def test_unknown_category_uses_default(self, ops_cost_scorer):
        """Unknown category uses default CS rate."""
        rate = ops_cost_scorer._cs_volume_estimate("미지카테고리")
        assert rate == DEFAULT_CS_RATE

    def test_electronics_moderate_cs(self, ops_cost_scorer):
        """Electronics have moderate CS rate (0.6)."""
        rate = ops_cost_scorer._cs_volume_estimate("디지털/가전")
        assert rate == 0.6


# =====================================================================
# Return rate handling
# =====================================================================

class TestReturnRateScore:
    """Tests for OpsCostScorer._return_rate_score()."""

    def test_category_based_return_rate(self, ops_cost_scorer):
        """Category-based return rate when no estimate provided."""
        rate = ops_cost_scorer._return_rate_score("패션의류")
        assert rate == 0.8

    def test_explicit_return_rate(self, ops_cost_scorer):
        """Explicit return rate overrides category default."""
        rate = ops_cost_scorer._return_rate_score("패션의류", estimated_return_rate=0.3)
        assert rate == 0.3

    def test_explicit_return_rate_clamped_high(self, ops_cost_scorer):
        """Explicit return rate > 1.0 is clamped to 1.0."""
        rate = ops_cost_scorer._return_rate_score("패션의류", estimated_return_rate=1.5)
        assert rate == 1.0

    def test_explicit_return_rate_clamped_low(self, ops_cost_scorer):
        """Explicit return rate < 0.0 is clamped to 0.0."""
        rate = ops_cost_scorer._return_rate_score("패션의류", estimated_return_rate=-0.5)
        assert rate == 0.0

    def test_unknown_category_default_return_rate(self, ops_cost_scorer):
        """Unknown category uses default return rate."""
        rate = ops_cost_scorer._return_rate_score("미지카테고리")
        assert rate == DEFAULT_RETURN_RATE

    def test_books_low_return_rate(self, ops_cost_scorer):
        """Books have low return rate (0.1)."""
        rate = ops_cost_scorer._return_rate_score("도서")
        assert rate == 0.1


# =====================================================================
# Overall ops cost score
# =====================================================================

class TestCalculateOpsCost:
    """Tests for OpsCostScorer.calculate()."""

    def test_simple_product_low_ops(self, ops_cost_scorer):
        """Simple product with few options and no size chart has low ops cost."""
        result = ops_cost_scorer.calculate(
            option_count=2,
            has_size_chart=False,
            category="도서",
        )
        assert isinstance(result, OpsCostResult)
        assert result.score < 0.25
        assert result.get_ops_level() == "LOW"

    def test_complex_fashion_product_high_ops(self, ops_cost_scorer):
        """Fashion product with many options and size chart has high ops cost."""
        result = ops_cost_scorer.calculate(
            option_count=12,
            has_size_chart=True,
            category="패션의류",
        )
        assert result.score >= 0.5
        assert result.get_ops_level() in ("HIGH", "VERY_HIGH")

    def test_factors_dict_has_all_keys(self, ops_cost_scorer):
        """Result factors dict has all expected keys."""
        result = ops_cost_scorer.calculate(
            option_count=4,
            has_size_chart=False,
            category="디지털/가전",
        )
        expected_keys = {"option_complexity", "page_difficulty", "cs_volume", "return_rate"}
        assert set(result.factors.keys()) == expected_keys

    def test_result_score_between_zero_and_one(self, ops_cost_scorer):
        """Ops cost score is always between 0 and 1."""
        for opts in [0, 5, 10, 20]:
            for size_chart in [True, False]:
                result = ops_cost_scorer.calculate(
                    option_count=opts,
                    has_size_chart=size_chart,
                    category="패션의류",
                )
                assert 0.0 <= result.score <= 1.0

    def test_with_estimated_return_rate(self, ops_cost_scorer):
        """Explicit return rate is used when provided."""
        result = ops_cost_scorer.calculate(
            option_count=4,
            has_size_chart=False,
            category="패션의류",
            estimated_return_rate=0.1,
        )
        assert result.factors["return_rate"] == pytest.approx(0.1, abs=0.01)

    def test_ops_level_categories(self, ops_cost_scorer):
        """get_ops_level returns one of the expected strings."""
        valid_levels = {"LOW", "MEDIUM", "HIGH", "VERY_HIGH"}
        result = ops_cost_scorer.calculate(
            option_count=6,
            has_size_chart=True,
            category="패션의류",
        )
        assert result.get_ops_level() in valid_levels

    def test_docstring_example(self, ops_cost_scorer):
        """Reproduces the docstring example."""
        result = ops_cost_scorer.calculate(
            option_count=8,
            has_size_chart=True,
            category="패션의류",
        )
        assert result.get_ops_level() == "HIGH"


# =====================================================================
# Warnings
# =====================================================================

class TestOpsCostWarnings:
    """Tests for OpsCostScorer warning messages."""

    def test_high_option_count_warning(self, ops_cost_scorer):
        """10+ options generate a warning about complexity."""
        result = ops_cost_scorer.calculate(
            option_count=12,
            has_size_chart=False,
            category="도서",
        )
        assert any("12" in w or "옵션" in w for w in result.warnings)

    def test_medium_option_count_warning(self, ops_cost_scorer):
        """5-9 options generate a warning about registration complexity."""
        result = ops_cost_scorer.calculate(
            option_count=7,
            has_size_chart=False,
            category="도서",
        )
        assert any("7" in w or "옵션" in w for w in result.warnings)

    def test_size_chart_warning(self, ops_cost_scorer):
        """Size chart requirement generates a warning."""
        result = ops_cost_scorer.calculate(
            option_count=2,
            has_size_chart=True,
            category="도서",
        )
        assert any("사이즈" in w for w in result.warnings)

    def test_high_cs_rate_warning(self, ops_cost_scorer):
        """High CS rate category generates a warning."""
        result = ops_cost_scorer.calculate(
            option_count=2,
            has_size_chart=False,
            category="패션의류",
        )
        assert any("CS" in w for w in result.warnings)

    def test_high_return_rate_warning(self, ops_cost_scorer):
        """High return rate generates a warning."""
        result = ops_cost_scorer.calculate(
            option_count=2,
            has_size_chart=False,
            category="패션의류",
        )
        assert any("반품" in w for w in result.warnings)

    def test_no_warnings_for_simple_product(self, ops_cost_scorer):
        """Simple product with low-risk category generates no warnings."""
        result = ops_cost_scorer.calculate(
            option_count=1,
            has_size_chart=False,
            category="도서",
        )
        assert len(result.warnings) == 0


# =====================================================================
# Custom category registration
# =====================================================================

class TestAddCustomCategoryRates:
    """Tests for OpsCostScorer.add_custom_category_rates()."""

    def test_add_custom_cs_rate(self, ops_cost_scorer):
        """Custom CS rate is used in calculation."""
        ops_cost_scorer.add_custom_category_rates("커스텀", cs_rate=0.9)
        rate = ops_cost_scorer._cs_volume_estimate("커스텀")
        assert rate == 0.9

    def test_add_custom_return_rate(self, ops_cost_scorer):
        """Custom return rate is used in calculation."""
        ops_cost_scorer.add_custom_category_rates("커스텀", return_rate=0.95)
        rate = ops_cost_scorer._return_rate_score("커스텀")
        assert rate == 0.95

    def test_invalid_cs_rate_raises(self, ops_cost_scorer):
        """Out-of-range CS rate raises ValueError."""
        with pytest.raises(ValueError):
            ops_cost_scorer.add_custom_category_rates("bad", cs_rate=1.5)

    def test_invalid_return_rate_raises(self, ops_cost_scorer):
        """Out-of-range return rate raises ValueError."""
        with pytest.raises(ValueError):
            ops_cost_scorer.add_custom_category_rates("bad", return_rate=-0.1)
