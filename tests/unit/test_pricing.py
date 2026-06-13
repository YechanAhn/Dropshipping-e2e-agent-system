"""
Tests for the optimal pricing engine (dropagent.core.pricing).

Covers:
    - charm_round: ceil rounding + ₩x,900 charm behavior, edge cases
    - optimal_price: margin floor respected, undercutting when feasible
    - Infeasibility flagged when competition sits below the margin floor
    - Empty competitor list handled gracefully
    - Target margin impossible given the fee structure
    - expected_margin_rate / expected_profit consistent at the recommended price
    - p25 / median percentile statistics

All functions under test are pure and synchronous.
"""

from decimal import Decimal

import pytest

from dropagent.core.pricing import (
    DEFAULT_MIN_PROFIT,
    DEFAULT_TARGET_MARGIN,
    SMARTSTORE_FEE_RATE,
    PricingResult,
    charm_round,
    optimal_price,
)

# =====================================================================
# Module constants
# =====================================================================


class TestConstants:
    """Default constants reflect the research findings (§5)."""

    def test_smartstore_fee_rate_is_six_percent(self):
        """SmartStore combined fee defaults to ~6% (not 10-11%)."""
        assert SMARTSTORE_FEE_RATE == Decimal("0.06")

    def test_default_target_margin(self):
        """Korean dropshippers target ~30% margin by default."""
        assert DEFAULT_TARGET_MARGIN == Decimal("0.30")

    def test_default_min_profit_floor(self):
        """Absolute per-order net-profit floor defaults to ₩5,000."""
        assert DEFAULT_MIN_PROFIT == 5000


# =====================================================================
# charm_round
# =====================================================================


class TestCharmRound:
    """Tests for charm_round()."""

    def test_rounds_up_to_charm_900(self):
        """10250 ceils to 10300, then charm rounds to 10900."""
        assert charm_round(10250) == 10900

    def test_already_charm_value_unchanged(self):
        """A value already ending in ...900 stays put."""
        assert charm_round(10900) == 10900

    def test_round_thousand_bumps_to_next_charm(self):
        """11000's own ...900 (10900) is below it, so bump to 11900."""
        assert charm_round(11000) == 11900

    def test_small_value_bumps_to_1900(self):
        """950 ceils to 1000; 900 < 1000 so charm bumps to 1900."""
        assert charm_round(950) == 1900

    def test_charm_disabled_only_ceils(self):
        """With charm=False only ceil rounding is applied."""
        assert charm_round(10250, charm=False) == 10300

    def test_custom_round_to_thousand(self):
        """round_to=1000 ceils 8001 to 9000, charm -> 9900."""
        assert charm_round(8001, round_to=1000) == 9900

    def test_below_1000_no_charm_applied(self):
        """Values under 1000 only get ceil rounding, no ...900 charm."""
        # 300 ceils to its own 100-bucket (already 300) and stays.
        assert charm_round(300) == 300

    def test_zero_and_negative_return_zero(self):
        """Non-positive prices collapse to 0."""
        assert charm_round(0) == 0
        assert charm_round(-500) == 0

    def test_charm_result_is_always_at_least_input(self):
        """Charm rounding never drops below the requested price (margin safety)."""
        for price in range(1000, 30001, 137):
            assert charm_round(price) >= price

    def test_charm_result_ends_in_900(self):
        """Every charm-rounded value >= 1000 ends in 900."""
        for price in range(1000, 30001, 211):
            assert charm_round(price) % 1000 == 900


# =====================================================================
# optimal_price — feasible / undercutting
# =====================================================================


class TestOptimalPriceFeasible:
    """optimal_price() when a competitive, margin-safe price exists."""

    def test_returns_pricing_result(self):
        """optimal_price returns a PricingResult dataclass."""
        result = optimal_price(Decimal("5000"), [12000, 13000, 14000, 15000, 16000])
        assert isinstance(result, PricingResult)

    def test_recommended_at_or_above_floor(self):
        """Recommended price is never below the margin floor."""
        result = optimal_price(Decimal("5000"), [12000, 13000, 14000, 15000, 16000])
        assert result.feasible is True
        assert result.recommended_price >= result.floor_price

    def test_undercuts_competition_when_feasible(self):
        """Recommended price undercuts the competitive median when feasible."""
        result = optimal_price(Decimal("3000"), [12000, 13000, 14000, 15000, 16000])
        assert result.feasible is True
        assert result.competitive_median is not None
        assert result.recommended_price < result.competitive_median

    def test_percentiles_computed(self):
        """p25 and median are populated from the competitor list."""
        result = optimal_price(Decimal("3000"), [10000, 12000, 14000, 16000, 18000])
        # Linear interpolation: sorted -> p25 = 12000, median = 14000.
        assert result.competitive_p25 == 12000
        assert result.competitive_median == 14000

    def test_recommended_is_charm_rounded(self):
        """A feasible recommended price ends in ...900 (charm default)."""
        result = optimal_price(Decimal("3000"), [12000, 13000, 14000, 15000, 16000])
        assert result.recommended_price % 1000 == 900

    def test_meets_target_margin_when_floor_binds(self):
        """When the margin floor binds, realised margin meets the target."""
        # Competitors sit just above the margin floor (~12,766 for this cost),
        # so the floor (target-margin driven) is what sets the price.
        result = optimal_price(Decimal("7000"), [12900, 13000, 13100])
        assert result.feasible is True
        # Margin must be at least the target (floor guarantees >= target_margin).
        assert result.expected_margin_rate >= float(DEFAULT_TARGET_MARGIN) - 1e-9


# =====================================================================
# optimal_price — infeasible
# =====================================================================


class TestOptimalPriceInfeasible:
    """optimal_price() when no margin-safe competitive price exists."""

    def test_cheap_competitors_high_cost_infeasible(self):
        """Competitors below the margin floor => feasible is False."""
        result = optimal_price(Decimal("10000"), [9000, 9500, 10000])
        assert result.feasible is False
        assert result.competitive_p25 is not None
        # The competitive p25 sits below the computed floor.
        assert result.competitive_p25 < result.floor_price
        assert result.reason  # non-empty explanation

    def test_empty_competitor_list_infeasible(self):
        """Empty competitor list => not feasible, percentiles are None."""
        result = optimal_price(Decimal("5000"), [])
        assert result.feasible is False
        assert result.competitive_p25 is None
        assert result.competitive_median is None
        # A reference floor price is still provided.
        assert result.floor_price > 0
        assert result.reason

    def test_target_margin_impossible_for_fee_structure(self):
        """target_margin + fee_rate >= 1 makes any margin impossible."""
        result = optimal_price(
            Decimal("5000"),
            [12000, 13000, 14000],
            target_margin=Decimal("0.95"),
            fee_rate=Decimal("0.06"),
        )
        assert result.feasible is False
        assert result.recommended_price == 0
        assert result.floor_price == 0
        assert result.reason


# =====================================================================
# optimal_price — expected profit / margin consistency
# =====================================================================


class TestOptimalPriceEconomics:
    """Recommended price implies the reported margin and profit."""

    def test_expected_profit_matches_formula(self):
        """expected_profit ≈ price*(1-fee) - landed_cost at recommended price."""
        landed = Decimal("5000")
        fee = SMARTSTORE_FEE_RATE
        result = optimal_price(landed, [12000, 13000, 14000, 15000, 16000])
        rec = Decimal(result.recommended_price)
        expected = rec * (Decimal("1") - fee) - landed
        # Allow ±1 KRW for rounding of the reported integer profit.
        assert abs(result.expected_profit - int(expected)) <= 1

    def test_expected_margin_rate_matches_formula(self):
        """expected_margin_rate ≈ profit / recommended_price."""
        landed = Decimal("5000")
        fee = SMARTSTORE_FEE_RATE
        result = optimal_price(landed, [12000, 13000, 14000, 15000, 16000])
        rec = Decimal(result.recommended_price)
        profit = rec * (Decimal("1") - fee) - landed
        expected_rate = float(profit / rec)
        assert result.expected_margin_rate == pytest.approx(expected_rate, abs=1e-3)

    def test_profit_meets_min_profit_floor(self):
        """A feasible recommendation clears the absolute min-profit floor."""
        result = optimal_price(Decimal("5000"), [12000, 13000, 14000, 15000, 16000])
        assert result.feasible is True
        assert result.expected_profit >= DEFAULT_MIN_PROFIT

    def test_min_profit_floor_drives_price_when_margin_low(self):
        """A high min_profit raises the floor even if % margin is satisfied."""
        low = optimal_price(Decimal("5000"), [], min_profit=5000)
        high = optimal_price(Decimal("5000"), [], min_profit=20000)
        assert high.floor_price > low.floor_price


# =====================================================================
# optimal_price — configuration knobs
# =====================================================================


class TestOptimalPriceConfig:
    """Optional keyword arguments behave as documented."""

    def test_undercut_zero_targets_p25(self):
        """undercut=0 with charm off targets p25 (ceiled), not below it."""
        result = optimal_price(
            Decimal("3000"),
            [12000, 13000, 14000, 15000, 16000],
            undercut=Decimal("0"),
            charm=False,
        )
        assert result.feasible is True
        assert result.competitive_p25 is not None
        # With no undercut the recommended price should not exceed p25 here
        # (floor is well below p25), and should be at least the floor.
        assert result.recommended_price <= result.competitive_p25
        assert result.recommended_price >= result.floor_price

    def test_no_charm_not_forced_to_900(self):
        """With charm=False the price need not end in ...900."""
        result = optimal_price(
            Decimal("3000"),
            [12340, 13000, 14000, 15000, 16000],
            charm=False,
            round_to=10,
        )
        # Just assert it is a clean multiple of round_to.
        assert result.recommended_price % 10 == 0

    def test_single_competitor_uses_that_price(self):
        """A single competitor yields p25 == median == that price."""
        result = optimal_price(Decimal("3000"), [14000])
        assert result.competitive_p25 == 14000
        assert result.competitive_median == 14000
