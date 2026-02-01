"""
Tests for RiskScorer.

Covers:
    - Shipping risk at different day thresholds
    - Breakage risk for fragile vs non-fragile
    - Customs risk for different categories
    - Weight risk at boundaries
    - Overall risk score calculation
    - Warnings generation
"""

import pytest

from dropagent.core.risk_scorer import (
    DEFAULT_CUSTOMS_RISK,
    DEFAULT_FRAGILE_RISK,
    RiskResult,
    RiskScorer,
)

# =====================================================================
# Shipping risk
# =====================================================================

class TestShippingRisk:
    """Tests for RiskScorer._shipping_risk()."""

    def test_30_plus_days(self):
        """30+ days returns 0.8."""
        assert RiskScorer._shipping_risk(30) == 0.8
        assert RiskScorer._shipping_risk(45) == 0.8

    def test_20_to_29_days(self):
        """20-29 days returns 0.4."""
        assert RiskScorer._shipping_risk(20) == 0.4
        assert RiskScorer._shipping_risk(29) == 0.4

    def test_10_to_19_days(self):
        """10-19 days returns 0.15."""
        assert RiskScorer._shipping_risk(10) == 0.15
        assert RiskScorer._shipping_risk(19) == 0.15

    def test_under_10_days(self):
        """Under 10 days returns 0.05."""
        assert RiskScorer._shipping_risk(9) == 0.05
        assert RiskScorer._shipping_risk(0) == 0.05
        assert RiskScorer._shipping_risk(5) == 0.05

    def test_boundary_30(self):
        """Exactly 30 days is in the highest tier."""
        assert RiskScorer._shipping_risk(30) == 0.8

    def test_boundary_20(self):
        """Exactly 20 days is in the second tier."""
        assert RiskScorer._shipping_risk(20) == 0.4

    def test_boundary_10(self):
        """Exactly 10 days is in the third tier."""
        assert RiskScorer._shipping_risk(10) == 0.15


# =====================================================================
# Breakage risk
# =====================================================================

class TestBreakageRisk:
    """Tests for RiskScorer._breakage_risk()."""

    def test_glass_ceramics_category(self, risk_scorer):
        """Glass/ceramics has the highest breakage risk."""
        risk = risk_scorer._breakage_risk("유리/도자기", is_fragile=False)
        assert risk == 0.9

    def test_fashion_category_low_risk(self, risk_scorer):
        """Fashion clothing has very low breakage risk."""
        risk = risk_scorer._breakage_risk("패션의류", is_fragile=False)
        assert risk == 0.1

    def test_unknown_category_uses_default(self, risk_scorer):
        """Unknown category uses default breakage risk."""
        risk = risk_scorer._breakage_risk("알수없는카테고리", is_fragile=False)
        assert risk == DEFAULT_FRAGILE_RISK

    def test_fragile_flag_adds_penalty(self, risk_scorer):
        """is_fragile=True adds 0.2 penalty."""
        base_risk = risk_scorer._breakage_risk("패션의류", is_fragile=False)
        fragile_risk = risk_scorer._breakage_risk("패션의류", is_fragile=True)
        assert fragile_risk == base_risk + 0.2

    def test_fragile_penalty_capped_at_one(self, risk_scorer):
        """Fragile penalty is capped at 1.0."""
        risk = risk_scorer._breakage_risk("유리/도자기", is_fragile=True)
        # 0.9 + 0.2 would be 1.1, capped at 1.0
        assert risk == 1.0

    def test_books_very_low_risk(self, risk_scorer):
        """Books have very low breakage risk."""
        risk = risk_scorer._breakage_risk("도서", is_fragile=False)
        assert risk == 0.05


# =====================================================================
# Customs risk
# =====================================================================

class TestCustomsRisk:
    """Tests for RiskScorer._customs_risk()."""

    def test_food_highest_customs_risk(self, risk_scorer):
        """Food has the highest customs risk (0.9)."""
        risk = risk_scorer._customs_risk("식품")
        assert risk == 0.9

    def test_cosmetics_high_customs_risk(self, risk_scorer):
        """Cosmetics have high customs risk (0.7)."""
        risk = risk_scorer._customs_risk("화장품/미용")
        assert risk == 0.7

    def test_electronics_moderate_customs_risk(self, risk_scorer):
        """Electronics have moderate customs risk (0.4)."""
        risk = risk_scorer._customs_risk("디지털/가전")
        assert risk == 0.4

    def test_fashion_low_customs_risk(self, risk_scorer):
        """Fashion clothing has low customs risk (0.1)."""
        risk = risk_scorer._customs_risk("패션의류")
        assert risk == 0.1

    def test_books_zero_customs_risk(self, risk_scorer):
        """Books have zero customs risk."""
        risk = risk_scorer._customs_risk("도서")
        assert risk == 0.0

    def test_unknown_category_uses_default(self, risk_scorer):
        """Unknown category uses default customs risk."""
        risk = risk_scorer._customs_risk("미지의카테고리")
        assert risk == DEFAULT_CUSTOMS_RISK


# =====================================================================
# Weight risk
# =====================================================================

class TestWeightRisk:
    """Tests for RiskScorer._weight_risk()."""

    def test_heavy_item(self):
        """2kg+ returns 0.5."""
        assert RiskScorer._weight_risk(2.0) == 0.5
        assert RiskScorer._weight_risk(5.0) == 0.5

    def test_medium_item(self):
        """1-2kg returns 0.2."""
        assert RiskScorer._weight_risk(1.0) == 0.2
        assert RiskScorer._weight_risk(1.5) == 0.2
        assert RiskScorer._weight_risk(1.99) == 0.2

    def test_light_item(self):
        """Under 1kg returns 0.0."""
        assert RiskScorer._weight_risk(0.5) == 0.0
        assert RiskScorer._weight_risk(0.0) == 0.0
        assert RiskScorer._weight_risk(0.99) == 0.0

    def test_boundary_2kg(self):
        """Exactly 2.0kg is in the heavy tier."""
        assert RiskScorer._weight_risk(2.0) == 0.5

    def test_boundary_1kg(self):
        """Exactly 1.0kg is in the medium tier."""
        assert RiskScorer._weight_risk(1.0) == 0.2


# =====================================================================
# Overall risk score calculation
# =====================================================================

class TestCalculateRiskScore:
    """Tests for RiskScorer.calculate()."""

    def test_low_risk_product(self, risk_scorer):
        """Light fashion item with fast shipping has low risk."""
        result = risk_scorer.calculate(
            shipping_days=7,
            product_category="패션의류",
            weight_kg=0.3,
            is_fragile=False,
        )
        assert isinstance(result, RiskResult)
        assert result.score < 0.25
        assert result.get_risk_level() == "LOW"

    def test_high_risk_product(self, risk_scorer):
        """Heavy fragile item with slow shipping has high risk."""
        result = risk_scorer.calculate(
            shipping_days=35,
            product_category="유리/도자기",
            weight_kg=3.0,
            is_fragile=True,
        )
        assert result.score >= 0.5
        assert result.get_risk_level() in ("HIGH", "VERY_HIGH")

    def test_factors_dict_has_all_keys(self, risk_scorer):
        """Result factors dict has shipping, breakage, customs, weight keys."""
        result = risk_scorer.calculate(
            shipping_days=15,
            product_category="디지털/가전",
            weight_kg=1.2,
        )
        assert set(result.factors.keys()) == {"shipping", "breakage", "customs", "weight"}

    def test_result_score_between_zero_and_one(self, risk_scorer):
        """Risk score is always between 0 and 1."""
        result = risk_scorer.calculate(
            shipping_days=45,
            product_category="식품",
            weight_kg=5.0,
            is_fragile=True,
        )
        assert 0.0 <= result.score <= 1.0

    def test_risk_level_categories(self, risk_scorer):
        """get_risk_level returns one of the expected strings."""
        valid_levels = {"LOW", "MEDIUM", "HIGH", "VERY_HIGH"}
        for days in [5, 15, 25, 40]:
            result = risk_scorer.calculate(
                shipping_days=days,
                product_category="패션의류",
                weight_kg=0.5,
            )
            assert result.get_risk_level() in valid_levels

    def test_custom_weights(self):
        """Custom weights change the overall score."""
        heavy_shipping_scorer = RiskScorer(
            weights={"shipping": 0.90, "breakage": 0.03, "customs": 0.03, "weight": 0.04}
        )
        result = heavy_shipping_scorer.calculate(
            shipping_days=35,
            product_category="패션의류",
            weight_kg=0.3,
        )
        # Shipping dominates: 0.8 * (0.9/1.0) = 0.72
        assert result.score >= 0.6

    def test_docstring_example(self, risk_scorer):
        """Verifies expected score for the docstring example inputs.

        shipping=25 -> 0.4, breakage=유리/도자기+fragile -> 1.0,
        customs=유리/도자기(default) -> 0.2, weight=1.5 -> 0.2
        weighted = 0.4*0.30 + 1.0*0.25 + 0.2*0.25 + 0.2*0.20 = 0.46 -> MEDIUM
        """
        result = risk_scorer.calculate(
            shipping_days=25,
            product_category="유리/도자기",
            weight_kg=1.5,
            is_fragile=True,
        )
        assert result.score == pytest.approx(0.46, abs=0.01)
        assert result.get_risk_level() == "MEDIUM"


# =====================================================================
# Warnings generation
# =====================================================================

class TestWarningsGeneration:
    """Tests for RiskScorer warning messages."""

    def test_shipping_30_plus_generates_warning(self, risk_scorer):
        """30+ day shipping generates CS surge warning."""
        result = risk_scorer.calculate(
            shipping_days=35,
            product_category="패션의류",
            weight_kg=0.5,
        )
        assert any("CS" in w or "35" in w for w in result.warnings)

    def test_shipping_20_to_29_generates_warning(self, risk_scorer):
        """20-29 day shipping generates customer complaint warning."""
        result = risk_scorer.calculate(
            shipping_days=25,
            product_category="패션의류",
            weight_kg=0.5,
        )
        assert any("25" in w for w in result.warnings)

    def test_fast_shipping_no_shipping_warning(self, risk_scorer):
        """Fast shipping generates no shipping warning."""
        result = risk_scorer.calculate(
            shipping_days=5,
            product_category="패션의류",
            weight_kg=0.5,
        )
        shipping_warnings = [w for w in result.warnings if "배송" in w]
        assert len(shipping_warnings) == 0

    def test_very_fragile_generates_warning(self, risk_scorer):
        """Very fragile items generate breakage warning."""
        result = risk_scorer.calculate(
            shipping_days=15,
            product_category="유리/도자기",
            weight_kg=0.5,
            is_fragile=True,
        )
        assert any("파손" in w for w in result.warnings)

    def test_high_customs_generates_warning(self, risk_scorer):
        """High customs risk category generates warning."""
        result = risk_scorer.calculate(
            shipping_days=15,
            product_category="식품",
            weight_kg=0.5,
        )
        assert any("통관" in w for w in result.warnings)

    def test_heavy_weight_generates_warning(self, risk_scorer):
        """Heavy item (2kg+) generates weight warning."""
        result = risk_scorer.calculate(
            shipping_days=15,
            product_category="패션의류",
            weight_kg=3.0,
        )
        assert any("3.0" in w or "무게" in w for w in result.warnings)

    def test_no_warnings_for_safe_product(self, risk_scorer):
        """Safe product generates no warnings."""
        result = risk_scorer.calculate(
            shipping_days=5,
            product_category="도서",
            weight_kg=0.3,
        )
        assert len(result.warnings) == 0


# =====================================================================
# Custom category registration
# =====================================================================

class TestAddCustomCategoryRisk:
    """Tests for RiskScorer.add_custom_category_risk()."""

    def test_add_custom_fragile_risk(self, risk_scorer):
        """Custom fragile risk is used in calculation."""
        risk_scorer.add_custom_category_risk("커스텀카테고리", fragile_risk=0.85)
        risk = risk_scorer._breakage_risk("커스텀카테고리", is_fragile=False)
        assert risk == 0.85

    def test_add_custom_customs_risk(self, risk_scorer):
        """Custom customs risk is used in calculation."""
        risk_scorer.add_custom_category_risk("커스텀카테고리", customs_risk=0.75)
        risk = risk_scorer._customs_risk("커스텀카테고리")
        assert risk == 0.75

    def test_invalid_fragile_risk_raises(self, risk_scorer):
        """Out-of-range fragile risk raises ValueError."""
        with pytest.raises(ValueError):
            risk_scorer.add_custom_category_risk("bad", fragile_risk=1.5)
        with pytest.raises(ValueError):
            risk_scorer.add_custom_category_risk("bad", fragile_risk=-0.1)

    def test_invalid_customs_risk_raises(self, risk_scorer):
        """Out-of-range customs risk raises ValueError."""
        with pytest.raises(ValueError):
            risk_scorer.add_custom_category_risk("bad", customs_risk=1.5)
        with pytest.raises(ValueError):
            risk_scorer.add_custom_category_risk("bad", customs_risk=-0.1)
