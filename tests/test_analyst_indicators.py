"""
Market Analyst: the pure maths in backend/analyst/indicators.py.
"""
import math

import pytest

from backend.analyst import indicators as ind


# --------------------------------------------------------------------------- returns and averages
def test_pct_return():
    closes = [100, 110, 120, 150]
    assert ind.pct_return(closes, 1) == pytest.approx(0.25)
    assert ind.pct_return(closes, 3) == pytest.approx(0.5)
    assert ind.pct_return([200, 100], 1) == pytest.approx(-0.5)


def test_pct_return_needs_enough_points_and_a_positive_base():
    assert ind.pct_return([100, 110], 2) is None
    assert ind.pct_return([], 1) is None
    assert ind.pct_return([0, 10], 1) is None


def test_sma():
    assert ind.sma([1, 2, 3, 4, 5], 2) == pytest.approx(4.5)
    assert ind.sma([1, 2, 3, 4, 5], 5) == pytest.approx(3)
    assert ind.sma([1, 2], 3) is None


# --------------------------------------------------------------------------- RSI
def test_rsi_all_up_is_100():
    assert ind.rsi([float(i) for i in range(1, 40)]) == 100.0


def test_rsi_all_down_is_0():
    assert ind.rsi([float(i) for i in range(40, 1, -1)]) == pytest.approx(0.0)


def test_rsi_flat_is_50():
    assert ind.rsi([10.0] * 30) == 50.0


def test_rsi_needs_more_than_period_points():
    assert ind.rsi([1.0] * 14) is None
    assert ind.rsi([1.0] * 15) is not None


# the classic Wilder RSI worked example (StockCharts): 70.53, 66.32, 66.55, 69.41, 66.36, 57.97
# (their table rounds intermediate averages, so allow a small tolerance)
TEXTBOOK = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
            46.00, 46.03, 46.41, 46.22, 45.64]


@pytest.mark.parametrize("length,expected", [(15, 70.53), (16, 66.32), (17, 66.55), (18, 69.41), (19, 66.36),
                                             (20, 57.97)])
def test_rsi_matches_textbook_values(length, expected):
    assert ind.rsi(TEXTBOOK[:length]) == pytest.approx(expected, abs=0.15)


# --------------------------------------------------------------------------- volatility / drawdown
def test_volatility_of_a_constant_series_is_zero():
    assert ind.annualized_volatility([100.0] * 100, 90, 252) == pytest.approx(0.0)


def test_volatility_known_scaling():
    # alternating +10% / back down: every daily log return is ±ln(1.1), so the daily stdev is exactly ln(1.1)
    closes = [100.0 if i % 2 == 0 else 110.0 for i in range(41)]
    daily = math.log(1.1)
    assert ind.annualized_volatility(closes, 40, 252) == pytest.approx(daily * math.sqrt(252))
    assert ind.annualized_volatility(closes, 40, 365) == pytest.approx(daily * math.sqrt(365))


def test_volatility_uses_only_the_window_and_needs_enough_returns():
    calm = [100.0] * 200
    wild = [100.0 if i % 2 == 0 else 150.0 for i in range(200)]
    # the last 90 returns are calm, earlier wild moves are outside the window
    assert ind.annualized_volatility(wild + calm, 90, 252) == pytest.approx(0.0)
    assert ind.annualized_volatility([100.0] * 10, 90, 252) is None  # fewer than 20 returns


def test_max_drawdown():
    assert ind.max_drawdown([100, 120, 60, 90, 130]) == pytest.approx(-0.5)
    assert ind.max_drawdown([1, 2, 3, 4]) == 0.0
    assert ind.max_drawdown([100]) is None


# --------------------------------------------------------------------------- correlation / volume
def test_correlation_identical_inverse_and_too_short():
    a = [math.sin(i) for i in range(30)]
    assert ind.correlation(a, a) == pytest.approx(1.0)
    assert ind.correlation(a, [-x for x in a]) == pytest.approx(-1.0)
    assert ind.correlation(a[:19], a[:19]) is None  # fewer than 20 points
    assert ind.correlation(a, [1.0] * 30) is None  # zero variance


def test_correlation_uses_the_common_tail():
    a = [math.sin(i) for i in range(40)]
    longer = [999.0] * 10 + a  # unrelated extra history at the start is ignored
    assert ind.correlation(longer, a) == pytest.approx(1.0)


def test_volume_trend():
    volumes = [100.0] * 90 + [150.0] * 20
    assert ind.volume_trend(volumes) == pytest.approx(0.5)
    assert ind.volume_trend([100.0] * 110) == pytest.approx(0.0)


def test_volume_trend_is_none_safe():
    # missing / zero volumes are skipped instead of crashing
    volumes = [None, 0, 100.0] * 30 + [None] * 5 + [200.0] * 20
    assert ind.volume_trend(volumes) == pytest.approx(1.0)
    assert ind.volume_trend([None] * 200) is None
    assert ind.volume_trend([100.0] * 39) is None  # needs recent + 20 points
    assert ind.volume_trend([]) is None


# --------------------------------------------------------------------------- scenario ranges
@pytest.mark.parametrize("ppy", [252, 365])
def test_scenario_ranges_are_ordered_and_contiguous(ppy):
    r = ind.scenario_ranges(100.0, 0.4, 30, ppy)
    bear, base, bull = r["bear"], r["base"], r["bull"]
    for low, high in (bear, base, bull):
        assert low < high
    assert bear[1] < bull[0]
    assert bear[0] < base[0] < base[1] < bull[1]
    # touching at the 25th / 75th percentiles, no gaps or overlaps
    assert bear[1] == pytest.approx(base[0])
    assert base[1] == pytest.approx(bull[0])
    # the base case straddles the current price (no drift)
    assert base[0] < 100.0 < base[1]


def test_scenario_ranges_widen_with_time():
    week = ind.scenario_ranges(100.0, 0.4, 7, 365)
    month = ind.scenario_ranges(100.0, 0.4, 30, 365)
    assert month["base"][1] - month["base"][0] > week["base"][1] - week["base"][0]
    assert month["bear"][0] < week["bear"][0]
    assert month["bull"][1] > week["bull"][1]


def test_scenario_ranges_exact_values_for_crypto():
    sigma = 0.5 * math.sqrt(30 / 365)
    r = ind.scenario_ranges(200.0, 0.5, 30, 365)
    assert r["base"] == pytest.approx((200 * math.exp(-ind.Z_25 * sigma), 200 * math.exp(ind.Z_25 * sigma)))
    assert r["bear"][0] == pytest.approx(200 * math.exp(-ind.Z_05 * sigma))
    assert r["bull"][1] == pytest.approx(200 * math.exp(ind.Z_05 * sigma))


def test_scenario_ranges_use_trading_days_for_stocks():
    # 30 calendar days = round(30 * 252 / 365) = 21 trading days
    sigma = 0.3 * math.sqrt(21 / 252)
    r = ind.scenario_ranges(100.0, 0.3, 30, 252)
    assert r["base"][1] == pytest.approx(100 * math.exp(ind.Z_25 * sigma))
    assert r["bull"][1] == pytest.approx(100 * math.exp(ind.Z_05 * sigma))


def test_zero_volatility_collapses_the_ranges_to_the_price():
    r = ind.scenario_ranges(100.0, 0.0, 7, 252)
    assert all(value == pytest.approx(100.0) for pair in r.values() for value in pair)
