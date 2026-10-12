"""
Pure calculations on a daily price series. No network, no database, so they're easy to test.

All functions take plain lists (oldest first) and return None when there isn't enough data, instead of guessing.
"""
import math
from statistics import mean, pstdev
from typing import Optional, Sequence

# z-scores of the standard normal distribution used for the scenario ranges
Z_25 = 0.674  # 25th / 75th percentile -> the middle 50% of outcomes ("base case")
Z_05 = 1.645  # 5th / 95th percentile -> the outer edge of the bull / bear cases


def pct_return(closes: Sequence[float], days: int) -> Optional[float]:
    """Return over the last `days` data points, as a fraction (0.12 = +12%)."""
    if len(closes) <= days or closes[-days - 1] <= 0:
        return None
    return closes[-1] / closes[-days - 1] - 1


def sma(values: Sequence[float], window: int) -> Optional[float]:
    """Simple moving average of the last `window` values."""
    if len(values) < window:
        return None
    return mean(values[-window:])


def rsi(closes: Sequence[float], period: int = 14) -> Optional[float]:
    """Wilder's Relative Strength Index (0-100)."""
    if len(closes) <= period:
        return None

    gains, losses = [], []
    for prev, cur in zip(closes[:-1], closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def log_returns(closes: Sequence[float]) -> list[float]:
    return [math.log(cur / prev) for prev, cur in zip(closes[:-1], closes[1:]) if prev > 0 and cur > 0]


def annualized_volatility(closes: Sequence[float], window: int, periods_per_year: int) -> Optional[float]:
    """Standard deviation of daily log returns over the last `window` days, scaled to a year (0.35 = 35%)."""
    returns = log_returns(closes[-(window + 1):])
    if len(returns) < max(20, window // 2):
        return None
    return pstdev(returns) * math.sqrt(periods_per_year)


def max_drawdown(closes: Sequence[float]) -> Optional[float]:
    """Largest peak-to-trough fall in the series, as a negative fraction (-0.25 = -25%)."""
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for price in closes:
        peak = max(peak, price)
        if peak > 0:
            worst = min(worst, price / peak - 1)
    return worst


def correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """Pearson correlation of two equally long series (used on daily returns)."""
    n = min(len(a), len(b))
    if n < 20:
        return None
    a, b = a[-n:], b[-n:]
    mean_a, mean_b = mean(a), mean(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a == 0 or var_b == 0:
        return None
    return cov / math.sqrt(var_a * var_b)


def volume_trend(volumes: Sequence[Optional[float]], recent: int = 20, baseline: int = 90) -> Optional[float]:
    """Average volume of the last `recent` days vs the `baseline` days before them (0.3 = 30% higher)."""
    clean = [v for v in volumes if v is not None and v > 0]
    if len(clean) < recent + 20:
        return None
    recent_avg = mean(clean[-recent:])
    base = clean[-(recent + baseline):-recent]
    if not base:
        return None
    base_avg = mean(base)
    return recent_avg / base_avg - 1 if base_avg > 0 else None


def scenario_ranges(price: float, annual_vol: float, days: int, periods_per_year: int) -> dict:
    """
    Price ranges for a horizon assuming log-normal returns with zero drift and the asset's recent volatility.
    Not a prediction: it only says how far the price has typically been able to move in that time.
      base = middle 50% of outcomes, bull = 75th-95th percentile, bear = 5th-25th percentile.
    """
    # trading days for stocks (~252/yr), calendar days for crypto (365/yr)
    steps = days if periods_per_year == 365 else round(days * 252 / 365)
    sigma = annual_vol * math.sqrt(steps / periods_per_year)

    def at(z: float) -> float:
        return price * math.exp(z * sigma)

    return {
        "bear": (at(-Z_05), at(-Z_25)),
        "base": (at(-Z_25), at(Z_25)),
        "bull": (at(Z_25), at(Z_05)),
    }
