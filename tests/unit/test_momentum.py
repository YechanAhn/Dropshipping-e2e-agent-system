"""Unit tests for trend-momentum detection on a relative 0-100 series."""

from dropagent.core.discovery.momentum import (
    MomentumLabel,
    linreg_slope_r2,
    momentum_opportunity_bonus,
    momentum_score,
    rolling_zscore,
    window_ratio,
    yoy_ratio,
)

# --- low-level helpers -------------------------------------------------------

def test_window_ratio_doubling():
    series = [1.0] * 8 + [2.0] * 4
    assert window_ratio(series, recent=4, prior=8) == 2.0


def test_window_ratio_short_series_defaults_to_one():
    assert window_ratio([1.0, 2.0]) == 1.0


def test_linreg_perfect_line():
    slope, r2 = linreg_slope_r2([0.0, 1.0, 2.0, 3.0])
    assert slope == 1.0
    assert r2 == 1.0


def test_rolling_zscore_flags_spike():
    # Trailing window needs non-zero variance for z to be defined.
    series = [10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 40.0]
    assert rolling_zscore(series, window=12) > 3.0


def test_rolling_zscore_flat_is_zero():
    assert rolling_zscore([10.0] * 13, window=12) == 0.0


def test_yoy_none_when_too_short():
    assert yoy_ratio([1.0] * 10) is None


# --- momentum_score labels ---------------------------------------------------

def test_flat_series_is_flat_low_score():
    res = momentum_score([30.0] * 60)
    assert res.label == MomentumLabel.FLAT
    assert res.score < 5.0


def test_rising_durable_series():
    series = [20.0] * 52 + [26, 30, 34, 38, 42, 46, 48, 50]
    res = momentum_score([float(x) for x in series])
    assert res.label == MomentumLabel.RISING
    assert res.score > 0.0
    assert res.window_ratio > 1.2


def test_falling_series():
    series = [50.0] * 52 + [44, 38, 32, 26, 20, 16, 14, 12]
    res = momentum_score([float(x) for x in series])
    assert res.label == MomentumLabel.FALLING


def test_seasonal_spike_is_demoted():
    series = [20.0] * 60
    for i in (4, 5, 6, 7):  # same-period-last-year peak
        series[i] = 45.0
    series[52:60] = [22.0, 26.0, 32.0, 38.0, 44.0, 46.0, 47.0, 48.0]
    res = momentum_score(series)
    assert res.is_seasonal is True
    assert res.label == MomentumLabel.SEASONAL


def test_breakout_from_low_base_is_new():
    series = [3.0] * 52 + [10, 18, 26, 34, 42, 50, 58, 66]
    res = momentum_score([float(x) for x in series])
    assert res.is_breakout is True
    assert res.label == MomentumLabel.NEW


def test_empty_series_is_safe():
    res = momentum_score([])
    assert res.label == MomentumLabel.FLAT
    assert res.score == 0.0


def test_momentum_opportunity_bonus_promotes_emerging_and_demotes_falling():
    new = momentum_opportunity_bonus(MomentumLabel.NEW)
    rising = momentum_opportunity_bonus(MomentumLabel.RISING)
    assert new > rising > 0.0
    assert momentum_opportunity_bonus(MomentumLabel.FLAT) == 0.0
    assert momentum_opportunity_bonus(MomentumLabel.SEASONAL) == 0.0
    assert momentum_opportunity_bonus(MomentumLabel.FALLING) < 0.0
    assert momentum_opportunity_bonus(None) == 0.0
