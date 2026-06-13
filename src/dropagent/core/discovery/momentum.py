"""
Trend momentum detection on a relative 0-100 series (Naver DataLab).

DataLab returns only a relative index (period max = 100), never absolute
counts, so momentum must be measured from the *shape* of the series. This
implements the recipe from ``docs/RESEARCH_discovery.md`` §3.2, all standard
time-series practice:

1. window-ratio momentum  M = mean(recent) / mean(prior)
2. normalized regression slope (+ R²) over the recent window
3. rolling z-score of the latest point (spike detection)
4. YoY gate (this period vs same period last year) to demote seasonal spikes
5. composite ``MomentumResult`` + an ItemScout-style label
   (rising / new / falling / seasonal / flat)

Pure-Python (``statistics`` + manual OLS); no numpy dependency.
"""

import statistics
from dataclasses import dataclass
from enum import StrEnum

# --- Tunables ----------------------------------------------------------------
RECENT_WINDOW = 4          # weeks
PRIOR_WINDOW = 8           # weeks
SLOPE_WINDOW = 8           # weeks
Z_WINDOW = 12              # weeks
YOY_PERIOD = 52            # weeks in a year

RISING_RATIO = 1.2         # M threshold for "rising"
FALLING_RATIO = 0.8        # M threshold for "falling"
MIN_R2 = 0.4               # regression must explain enough variance
SEASONAL_YOY_MAX = 1.1     # M>RISING but YoY<=this => seasonal, demote
DURABLE_YOY_MIN = 1.2      # durable rise needs YoY above this
SLOPE_SCALE = 10.0         # scales normalized slope into ~[0,1] before clipping

BREAKOUT_BASE_MAX = 8.0    # "from a near-zero base" threshold on the 0-100 scale
BREAKOUT_MULTIPLE = 3.0    # recent mean >= base * this => breakout/new

SEASONAL_DEMOTION = 0.4    # multiply score when flagged seasonal


class MomentumLabel(StrEnum):
    """ItemScout-style trend bucket for a keyword."""

    RISING = "rising"      # 급상승
    NEW = "new"            # 신규 / breakout from a low base
    FALLING = "falling"    # 급하락
    SEASONAL = "seasonal"  # 계절성 (recurring, not durable)
    FLAT = "flat"          # 트렌드 없음


@dataclass(frozen=True)
class MomentumResult:
    """Outcome of momentum analysis on a trend series."""

    score: float            # 0..100 composite momentum
    label: MomentumLabel
    window_ratio: float     # M = mean(recent)/mean(prior)
    slope_norm: float       # regression slope / mean(window)
    r2: float               # regression goodness of fit
    zscore: float           # rolling z of the latest point
    yoy: float | None       # this period / same period last year (None if N/A)
    is_seasonal: bool
    is_breakout: bool


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def window_ratio(series: list[float], recent: int = RECENT_WINDOW, prior: int = PRIOR_WINDOW) -> float:
    """``mean(last `recent`) / mean(the `prior` before that)``; 1.0 if undefined."""
    if len(series) < recent + 1:
        return 1.0
    recent_vals = series[-recent:]
    prior_vals = series[-(recent + prior):-recent] or series[:-recent]
    prior_mean = _mean(prior_vals)
    if prior_mean <= 0:
        # Rising from a zero baseline: treat as strongly rising but finite.
        return float(BREAKOUT_MULTIPLE) if _mean(recent_vals) > 0 else 1.0
    return _mean(recent_vals) / prior_mean


def linreg_slope_r2(values: list[float]) -> tuple[float, float]:
    """Ordinary-least-squares slope and R² of ``values`` against index 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0, 0.0
    xs = list(range(n))
    mean_x = _mean([float(x) for x in xs])
    mean_y = _mean(values)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    if sxx == 0:
        return 0.0, 0.0
    slope = sxy / sxx
    syy = sum((y - mean_y) ** 2 for y in values)
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    return slope, r2


def normalized_slope(series: list[float], window: int = SLOPE_WINDOW) -> tuple[float, float]:
    """Regression slope normalized by the window mean (scale-free), plus R²."""
    vals = series[-window:]
    slope, r2 = linreg_slope_r2(vals)
    mean_v = _mean(vals)
    slope_n = slope / mean_v if mean_v > 0 else 0.0
    return slope_n, r2


def rolling_zscore(series: list[float], window: int = Z_WINDOW) -> float:
    """Z-score of the latest point vs the trailing ``window`` points before it."""
    if len(series) < window + 1:
        return 0.0
    trailing = series[-(window + 1):-1]
    mu = _mean(trailing)
    try:
        sigma = statistics.stdev(trailing)
    except statistics.StatisticsError:
        return 0.0
    if sigma == 0:
        return 0.0
    return (series[-1] - mu) / sigma


def yoy_ratio(
    series: list[float],
    period: int = YOY_PERIOD,
    recent: int = RECENT_WINDOW,
) -> float | None:
    """
    Year-over-year ratio: ``mean(last `recent`) / mean(same `recent` a year ago)``.

    Returns ``None`` when the series is too short to look back a full year.
    """
    if len(series) < period + recent:
        return None
    recent_vals = series[-recent:]
    ago_vals = series[-(period + recent):-period]
    ago_mean = _mean(ago_vals)
    if ago_mean <= 0:
        return None
    return _mean(recent_vals) / ago_mean


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def momentum_score(series: list[float]) -> MomentumResult:
    """
    Analyze a weekly relative 0-100 trend series and return a momentum result.

    For best results pass >= ``YOY_PERIOD + RECENT_WINDOW`` weeks in one request
    so the 100-anchor is fixed and YoY is comparable (see research §3.2).
    """
    if not series:
        return MomentumResult(0.0, MomentumLabel.FLAT, 1.0, 0.0, 0.0, 0.0, None, False, False)

    m = window_ratio(series)
    slope_n, r2 = normalized_slope(series)
    z = rolling_zscore(series)
    yoy = yoy_ratio(series)

    # Breakout / "new": emerging from a near-zero base.
    base = _mean(series[: max(1, len(series) // 2)])
    recent_mean = _mean(series[-RECENT_WINDOW:])
    is_breakout = base <= BREAKOUT_BASE_MAX and recent_mean >= base * BREAKOUT_MULTIPLE

    # Seasonal: rising vs last month but flat/down vs same period last year.
    is_seasonal = yoy is not None and m > RISING_RATIO and yoy <= SEASONAL_YOY_MAX

    # Composite score (convex combination, renormalized when YoY is missing).
    terms: list[tuple[float, float]] = [
        (0.35, _clip01(m - 1.0)),
        (0.30, _clip01(slope_n * SLOPE_SCALE) if r2 >= MIN_R2 else 0.0),
        (0.20, _clip01(z / 3.0)),
    ]
    if yoy is not None:
        terms.append((0.15, _clip01(yoy - 1.0)))
    total_w = sum(w for w, _ in terms)
    raw = sum(w * v for w, v in terms) / total_w if total_w else 0.0
    score = raw * 100.0

    # Label + seasonal demotion.
    durable = (yoy is None) or (yoy > DURABLE_YOY_MIN)
    if is_seasonal:
        label = MomentumLabel.SEASONAL
        score *= SEASONAL_DEMOTION
    elif is_breakout and m >= RISING_RATIO:
        label = MomentumLabel.NEW
    elif m >= RISING_RATIO and slope_n > 0 and durable:
        label = MomentumLabel.RISING
    elif m <= FALLING_RATIO and slope_n < 0:
        label = MomentumLabel.FALLING
    else:
        label = MomentumLabel.FLAT

    return MomentumResult(
        score=round(score, 2),
        label=label,
        window_ratio=round(m, 4),
        slope_norm=round(slope_n, 6),
        r2=round(r2, 4),
        zscore=round(z, 4),
        yoy=round(yoy, 4) if yoy is not None else None,
        is_seasonal=is_seasonal,
        is_breakout=is_breakout,
    )
