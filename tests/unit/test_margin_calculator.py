"""
Tests for MarginCalculator.

Covers:
    - Commission rate lookup for known categories
    - Default commission rate for unknown category
    - Total cost calculation with known inputs
    - Margin rate calculation (positive, zero, negative margins)
    - Naver price estimation (median calculation)
    - Full calculate() workflow
    - Edge cases: zero prices, missing data
"""

from decimal import Decimal

import pytest

from dropagent.core.margin_calculator import (
    DEFAULT_COMMISSION_RATE,
    NAVER_COMMISSION_RATES,
    CostBreakdown,
    MarginCalculator,
    MarginResult,
)

# =====================================================================
# Commission rate lookup
# =====================================================================

class TestGetCommissionRate:
    """Tests for MarginCalculator.get_commission_rate()."""

    def test_known_category_fashion(self, margin_calculator):
        """Commission rate for a known fashion category returns expected value."""
        rate = margin_calculator.get_commission_rate("패션의류")
        assert rate == Decimal("7.0") / Decimal("100")
        assert rate == Decimal("0.07")

    def test_known_category_digital(self, margin_calculator):
        """Commission rate for digital/electronics is 5.5%."""
        rate = margin_calculator.get_commission_rate("디지털/가전")
        assert rate == Decimal("0.055")

    def test_known_category_food(self, margin_calculator):
        """Commission rate for food is the highest at 11%."""
        rate = margin_calculator.get_commission_rate("식품")
        assert rate == Decimal("0.11")

    def test_default_commission_for_unknown_category(self, margin_calculator):
        """Unknown category falls back to DEFAULT_COMMISSION_RATE (8%)."""
        rate = margin_calculator.get_commission_rate("알 수 없는 카테고리")
        expected = DEFAULT_COMMISSION_RATE / Decimal("100")
        assert rate == expected

    def test_custom_commission_rates(self):
        """Custom commission rates override default table."""
        custom_rates = {"커스텀": Decimal("12.0")}
        calc = MarginCalculator(commission_rates=custom_rates)
        rate = calc.get_commission_rate("커스텀")
        assert rate == Decimal("0.12")

    def test_all_known_categories_have_positive_rates(self, margin_calculator):
        """Every known category should have a positive commission rate."""
        for category in NAVER_COMMISSION_RATES:
            rate = margin_calculator.get_commission_rate(category)
            assert rate > 0, f"Category {category} has non-positive rate: {rate}"


# =====================================================================
# Total cost calculation
# =====================================================================

class TestCalculateTotalCost:
    """Tests for MarginCalculator.calculate_total_cost()."""

    def test_basic_cost_with_naver_price(self, margin_calculator):
        """Total cost with all known inputs yields expected breakdown."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=100,
            shipping=10,
            exchange_rate=190,
            category="패션의류",
            naver_estimated_price=30000,
        )
        assert isinstance(breakdown, CostBreakdown)

        # ali_price_krw = 100 * 190 = 19000
        assert breakdown.ali_price == Decimal("19000.00")
        # ali_shipping_krw = 10 * 190 = 1900
        assert breakdown.ali_shipping == Decimal("1900.00")
        # exchange_margin = (19000 + 1900) * 0.05 = 1045
        assert breakdown.exchange_margin == Decimal("1045.00")
        # naver_commission = 30000 * 0.07 = 2100
        assert breakdown.naver_commission == Decimal("2100.00")
        # cs_risk = 30000 * 0.03 = 900
        assert breakdown.cs_risk == Decimal("900.00")
        # refund_return = 30000 * 0.02 = 600
        assert breakdown.refund_return == Decimal("600.00")

    def test_total_cost_sum(self, margin_calculator):
        """CostBreakdown.total() equals sum of all components."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=50,
            shipping=5,
            exchange_rate=190,
            category="디지털/가전",
            naver_estimated_price=15000,
        )
        expected_total = (
            breakdown.ali_price
            + breakdown.ali_shipping
            + breakdown.exchange_margin
            + breakdown.naver_commission
            + breakdown.cs_risk
            + breakdown.refund_return
        )
        assert breakdown.total() == expected_total

    def test_cost_without_naver_price_uses_base_fallback(self, margin_calculator):
        """When naver_estimated_price is None, cost-based estimation is used."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=100,
            shipping=10,
            exchange_rate=190,
            category="패션의류",
            naver_estimated_price=None,
        )
        # base_cost = 20900
        # naver_commission fallback = 20900 * 0.08 = 1672
        assert breakdown.naver_commission == Decimal("1672.00")
        # cs_risk fallback = 20900 * 0.03 = 627
        assert breakdown.cs_risk == Decimal("627.00")
        # refund_return fallback = 20900 * 0.02 = 418
        assert breakdown.refund_return == Decimal("418.00")

    def test_zero_shipping_cost(self, margin_calculator):
        """Zero shipping produces zero shipping line item."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=100,
            shipping=0,
            exchange_rate=190,
            category="패션의류",
            naver_estimated_price=25000,
        )
        assert breakdown.ali_shipping == Decimal("0.00")

    def test_decimal_inputs(self, margin_calculator):
        """Handles Decimal inputs without error."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=Decimal("99.99"),
            shipping=Decimal("5.50"),
            exchange_rate=Decimal("189.5"),
            category="화장품/미용",
            naver_estimated_price=Decimal("25000"),
        )
        assert breakdown.total() > 0


# =====================================================================
# Margin rate calculation
# =====================================================================

class TestCalculateMarginRate:
    """Tests for MarginCalculator.calculate_margin_rate()."""

    def test_positive_margin(self, margin_calculator):
        """Positive margin when naver_price exceeds total_cost."""
        rate = margin_calculator.calculate_margin_rate(10000, 7000)
        assert rate == Decimal("30.00")

    def test_zero_margin(self, margin_calculator):
        """Zero margin when price equals cost."""
        rate = margin_calculator.calculate_margin_rate(10000, 10000)
        assert rate == Decimal("0.00")

    def test_negative_margin(self, margin_calculator):
        """Negative margin when cost exceeds price."""
        rate = margin_calculator.calculate_margin_rate(10000, 13000)
        assert rate == Decimal("-30.00")

    def test_zero_naver_price_returns_zero(self, margin_calculator):
        """Zero naver price returns 0.00 (avoids division by zero)."""
        rate = margin_calculator.calculate_margin_rate(0, 5000)
        assert rate == Decimal("0.00")

    def test_high_margin(self, margin_calculator):
        """High margin calculation."""
        rate = margin_calculator.calculate_margin_rate(10000, 1000)
        assert rate == Decimal("90.00")

    def test_rounding(self, margin_calculator):
        """Result is rounded to 2 decimal places."""
        rate = margin_calculator.calculate_margin_rate(10000, 6667)
        # (10000 - 6667) / 10000 * 100 = 33.33
        assert rate == Decimal("33.33")


# =====================================================================
# Naver price estimation
# =====================================================================

class TestEstimateNaverPrice:
    """Tests for MarginCalculator.estimate_naver_price()."""

    def test_median_with_odd_number_of_prices(self, margin_calculator):
        """Median of an odd-length list."""
        prices = [10000, 12000, 11000, 15000, 10500]
        result = margin_calculator.estimate_naver_price(prices)
        # Sorted: [10000, 10500, 11000, 12000, 15000] -> median = 11000
        assert result == Decimal("11000.00")

    def test_median_with_even_number_of_prices(self, margin_calculator):
        """Median of an even-length list (average of two middle values)."""
        prices = [10000, 12000, 11000, 15000]
        result = margin_calculator.estimate_naver_price(prices)
        # Sorted: [10000, 11000, 12000, 15000] -> median = (11000+12000)/2 = 11500
        assert result == Decimal("11500.00")

    def test_single_price(self, margin_calculator):
        """Single price returns that price."""
        result = margin_calculator.estimate_naver_price([25000])
        assert result == Decimal("25000.00")

    def test_empty_prices_returns_zero(self, margin_calculator):
        """Empty list returns 0.00."""
        result = margin_calculator.estimate_naver_price([])
        assert result == Decimal("0.00")

    def test_sample_prices_fixture(self, margin_calculator, sample_naver_prices):
        """Works correctly with sample fixture data."""
        result = margin_calculator.estimate_naver_price(sample_naver_prices)
        assert result > 0


# =====================================================================
# Full calculate() workflow
# =====================================================================

class TestCalculateWorkflow:
    """Tests for MarginCalculator.calculate()."""

    def test_full_calculation_with_naver_prices(self, margin_calculator):
        """Full workflow with naver competitor prices."""
        result = margin_calculator.calculate(
            ali_price=100,
            shipping=10,
            exchange_rate=190,
            category="패션의류",
            naver_prices=[30000, 32000, 31000],
        )
        assert isinstance(result, MarginResult)
        assert result.naver_estimated_price == Decimal("31000.00")
        assert result.total_cost > 0
        assert isinstance(result.margin_rate, Decimal)
        assert isinstance(result.breakdown, CostBreakdown)

    def test_full_calculation_with_explicit_naver_price(self, margin_calculator):
        """naver_estimated_price takes precedence over naver_prices."""
        result = margin_calculator.calculate(
            ali_price=100,
            shipping=10,
            exchange_rate=190,
            category="패션의류",
            naver_prices=[30000, 32000, 31000],
            naver_estimated_price=35000,
        )
        assert result.naver_estimated_price == Decimal("35000.00")

    def test_expected_profit(self, margin_calculator):
        """expected_profit() matches naver_price - total_cost."""
        result = margin_calculator.calculate(
            ali_price=100,
            shipping=10,
            exchange_rate=190,
            category="디지털/가전",
            naver_estimated_price=30000,
        )
        expected_profit = result.naver_estimated_price - result.total_cost
        assert result.expected_profit() == expected_profit

    def test_raises_without_any_price_input(self, margin_calculator):
        """Raises ValueError when neither naver_prices nor naver_estimated_price given."""
        with pytest.raises(ValueError, match="naver_prices or naver_estimated_price"):
            margin_calculator.calculate(
                ali_price=100,
                shipping=10,
                exchange_rate=190,
                category="패션의류",
            )

    def test_margin_with_sample_product(self, margin_calculator, sample_product, sample_naver_prices):
        """End-to-end test with sample fixture data."""
        result = margin_calculator.calculate(
            ali_price=float(sample_product["price_cny"]),
            shipping=float(sample_product["shipping_cny"]),
            exchange_rate=float(sample_product["exchange_rate"]),
            category="디지털/가전",
            naver_prices=sample_naver_prices,
        )
        assert isinstance(result.margin_rate, Decimal)
        assert result.total_cost > 0
        assert result.naver_estimated_price > 0


# =====================================================================
# Edge cases
# =====================================================================

class TestEdgeCases:
    """Edge case tests for MarginCalculator."""

    def test_zero_ali_price(self, margin_calculator):
        """Zero AliExpress price produces zero ali_price line."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=0,
            shipping=10,
            exchange_rate=190,
            category="패션의류",
            naver_estimated_price=20000,
        )
        assert breakdown.ali_price == Decimal("0.00")

    def test_zero_exchange_rate_produces_zero_base(self, margin_calculator):
        """Zero exchange rate effectively makes all CNY-based costs zero."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=100,
            shipping=10,
            exchange_rate=0,
            category="패션의류",
            naver_estimated_price=20000,
        )
        assert breakdown.ali_price == Decimal("0.00")
        assert breakdown.ali_shipping == Decimal("0.00")
        assert breakdown.exchange_margin == Decimal("0.00")

    def test_very_large_prices(self, margin_calculator):
        """Handles very large price values without errors."""
        result = margin_calculator.calculate(
            ali_price=999999,
            shipping=99999,
            exchange_rate=200,
            category="디지털/가전",
            naver_estimated_price=500000000,
        )
        assert result.total_cost > 0
        assert isinstance(result.margin_rate, Decimal)

    def test_float_exchange_rate(self, margin_calculator):
        """Float exchange rate is handled correctly."""
        breakdown = margin_calculator.calculate_total_cost(
            ali_price=100,
            shipping=10,
            exchange_rate=189.75,
            category="패션의류",
            naver_estimated_price=30000,
        )
        assert breakdown.ali_price > 0
