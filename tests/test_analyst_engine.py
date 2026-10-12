"""
Market Analyst: the rules engine (backend/analyst/engine.py) on synthetic, deterministic market data.
"""
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from backend.analyst import engine
from backend.analyst.engine import build_report, fmt_money
from backend.analyst.gemini import _numbers
from backend.analyst.schema import AnalystReport
from tests.analyst_helpers import BAD_FUNDAMENTALS, COIN, GOOD_FUNDAMENTALS, make_closes, make_data


def utc_today():
    return datetime.now(timezone.utc).date()


def crypto_up(coin=None, **fields):
    return make_data("up", asset_type="crypto", symbol="SOL", coin=dict(coin or COIN),
                     btc_closes=make_closes("up", 365, 50000), **fields)


MIXED_FUNDAMENTALS = {**BAD_FUNDAMENTALS, "trailingPE": 80.0, "targetMeanPrice": 70.0, "currentPrice": 100.0,
                      "numberOfAnalystOpinions": 10, "recommendationMean": 4.0}


# --------------------------------------------------------------------------- sentiment and confidence
@pytest.mark.parametrize("data,sentiment,confidence", [
    (make_data("up", fundamentals=dict(GOOD_FUNDAMENTALS)), "bullish", "high"),
    (make_data("up"), "bullish", "medium"),
    (make_data("up", fundamentals=dict(BAD_FUNDAMENTALS)), "bullish", "medium"),
    (make_data("down"), "bearish", "medium"),
    (make_data("down", fundamentals=dict(BAD_FUNDAMENTALS)), "bearish", "high"),
    (make_data("flat"), "neutral", "medium"),
    (make_data("flat", asset_type="crypto", symbol="SOL"), "neutral", "low"),
    (make_data("up", fundamentals=dict(MIXED_FUNDAMENTALS)), "neutral", "low"),  # price up, fundamentals poor
    (crypto_up(), "bullish", "high"),
], ids=["up+good-fundamentals", "up-price-only", "up+bad-fundamentals", "down", "down+bad-fundamentals",
        "flat-stock", "flat-crypto", "mixed-signals", "crypto-up"])
def test_sentiment_and_confidence(data, sentiment, confidence):
    report = build_report(data)
    assert report.status == "ok"
    assert report.sentiment == sentiment
    assert report.confidence == confidence
    assert -1 <= report.score <= 1
    if sentiment == "bullish":
        assert report.score > 0.15
    elif sentiment == "bearish":
        assert report.score < -0.15
    else:
        assert -0.15 <= report.score <= 0.15
    assert f"a {sentiment} outlook" in report.summary
    assert f"({confidence} confidence)" in report.summary


def test_few_signals_means_low_confidence():
    # 45 points: no 50-day average yet, so only momentum (and RSI) can speak
    report = build_report(make_data("up", n=45))
    assert report.status == "ok"
    assert report.confidence == "low"


def test_bullish_and_bearish_reports_have_matching_text():
    up = build_report(make_data("up", fundamentals=dict(GOOD_FUNDAMENTALS)))
    down = build_report(make_data("down", fundamentals=dict(BAD_FUNDAMENTALS)))
    assert "favourable" in up.bottom_line and "unfavourable" not in up.bottom_line
    assert "unfavourable" in down.bottom_line
    assert any("above" in r for r in up.reasons)
    assert any("below" in r for r in down.reasons)
    assert 1 <= len(up.reasons) <= 3 and 1 <= len(down.reasons) <= 3


def test_constant_price_is_not_bearish():
    report = build_report(make_data("constant"))
    assert report.sentiment == "neutral"
    assert all(i.title != "Downtrend in place" for i in report.insights)


def test_reasons_never_contradict_the_sentiment():
    data = make_data("up", asset_type="crypto", symbol="SOL")
    # range-bound series whose 30-day return is positive while the 90-day return is slightly negative
    data.closes = [100 * (1 + 0.02 * math.sin(i * 0.9) + 0.01 * math.sin(i * 2.3))
                   for i in range(len(data.closes))]
    report = build_report(data)
    assert report.sentiment == "bullish"  # precondition: the case the bug shows up in
    assert not any(r.startswith("Down") for r in report.reasons), report.reasons


# --------------------------------------------------------------------------- insufficient data
@pytest.mark.parametrize("n", [0, 1, 20, 29])
def test_insufficient_data_below_30_points(n):
    report = build_report(make_data("up", n=n))
    assert report.status == "insufficient_data"
    assert report.sentiment is None and report.confidence is None and report.score is None
    assert report.scenarios == [] and report.insights == [] and report.reasons == [] and report.watch == []
    assert report.main_risk is None and report.bottom_line is None
    assert f"({n} daily data points; at least 30 are needed)" in report.summary
    assert "enough price history" in report.summary
    assert report.disclaimer


def test_30_points_is_enough():
    report = build_report(make_data("up", n=30))
    assert report.status == "ok"
    assert report.sentiment is not None


def test_insufficient_data_keeps_sources_and_limitations():
    data = make_data("up", n=5, name="Tiny Coin", asset_type="crypto", symbol="tiny",
                     limitations=["No news feed is connected."])
    report = build_report(data)
    assert "Tiny Coin" in report.summary
    assert report.asset.symbol == "TINY"
    assert report.limitations == ["No news feed is connected."]
    assert report.sources and report.sources[0].name == "Synthetic test data"


# --------------------------------------------------------------------------- scenarios and ranges
@pytest.mark.parametrize("asset_type", ["stock", "crypto"])
@pytest.mark.parametrize("n", [60, 365])
def test_scenarios_with_ranges(asset_type, n):
    report = build_report(make_data("flat", n=n, asset_type=asset_type))
    assert [s.case for s in report.scenarios] == ["bull", "base", "bear"]
    by_case = {s.case: s for s in report.scenarios}
    for scenario in report.scenarios:
        assert [r.days for r in scenario.ranges] == [7, 30]
        assert scenario.summary and scenario.conditions
    for i in range(2):
        bull, base, bear = by_case["bull"].ranges[i], by_case["base"].ranges[i], by_case["bear"].ranges[i]
        assert bear.low < bear.high <= base.low + 1e-9 < base.high <= bull.low + 1e-9 < bull.high
        assert base.low < report.asset.price < base.high
    week, month = by_case["base"].ranges
    assert month.high - month.low > week.high - week.low
    assert report.range_method and "volatility" in report.range_method


def test_no_ranges_below_60_points():
    report = build_report(make_data("up", n=59))
    assert report.status == "ok"
    assert [s.case for s in report.scenarios] == ["bull", "base", "bear"]
    assert all(s.ranges == [] for s in report.scenarios)
    assert report.range_method is None


def test_stock_ranges_are_tighter_than_crypto_for_the_same_series():
    # same prices, but stocks scale volatility with 252 trading days per year and 21 trading days per month
    stock = build_report(make_data("flat", asset_type="stock"))
    crypto = build_report(make_data("flat", asset_type="crypto"))
    s_base = stock.scenarios[1].ranges[1]
    c_base = crypto.scenarios[1].ranges[1]
    assert s_base.high - s_base.low != pytest.approx(c_base.high - c_base.low)


# --------------------------------------------------------------------------- stock vs crypto signals
def _spy(monkeypatch, name, calls):
    real = getattr(engine, name)

    def wrapper(*args, **kwargs):
        calls.append(name)
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, name, wrapper)


def test_stock_reports_never_use_crypto_signals(monkeypatch):
    calls = []
    for name in ("crypto_signals", "fundamentals_signal", "valuation_signal", "analysts_signal"):
        _spy(monkeypatch, name, calls)
    report = build_report(make_data("up", fundamentals=dict(GOOD_FUNDAMENTALS)))
    assert "crypto_signals" not in calls
    assert {"fundamentals_signal", "valuation_signal", "analysts_signal"} <= set(calls)
    groups = {m.group for m in report.metrics}
    assert {"fundamentals", "valuation", "analysts"} <= groups
    assert not groups & {"supply", "market"}
    assert not {i.kind for i in report.insights} & {"supply", "market", "correlation"}
    labels = {m.label for m in report.metrics}
    assert not labels & {"All-time high", "24h volume", "Correlation with BTC (90-day)", "Circulating supply"}


def test_crypto_reports_never_use_stock_signals(monkeypatch):
    calls = []
    for name in ("crypto_signals", "fundamentals_signal", "valuation_signal", "analysts_signal"):
        _spy(monkeypatch, name, calls)
    report = build_report(crypto_up())
    assert calls == ["crypto_signals"]
    groups = {m.group for m in report.metrics}
    assert not groups & {"fundamentals", "valuation", "analysts"}
    assert {"market", "supply"} <= groups
    assert not {i.kind for i in report.insights} & {"fundamentals", "valuation", "analysts"}
    labels = {m.label for m in report.metrics}
    assert {"All-time high", "24h volume", "Correlation with BTC (90-day)"} <= labels
    assert any("Bitcoin" in r for r in report.reasons)


def test_crypto_signals_cover_liquidity_ath_and_btc():
    data = crypto_up(coin={**COIN, "total_volume": 1.0e8})  # 0.13% turnover -> thin liquidity
    facts = engine.calculate_facts(data)
    keys = {s.key for s in engine.crypto_signals(facts, data)}
    assert keys == {"liquidity", "ath", "btc"}
    assert facts.btc_corr == pytest.approx(1.0, abs=0.01)  # same shape as BTC


def test_analyst_target_is_converted_to_the_users_currency():
    # history already converted to CAD (~1.4x the USD quote); Yahoo's target is in USD
    data = make_data("up", currency="CAD", fundamentals=dict(GOOD_FUNDAMENTALS))  # Yahoo: currentPrice 100 USD
    data.closes = [c * 140.0 / data.closes[-1] for c in data.closes]  # last close 140 CAD = 100 USD
    report = build_report(data)
    expected = fmt_money(120.0 * 1.4, "CAD")
    assert expected == "CA$168.00"
    target = next(m for m in report.metrics if m.label == "Analyst mean target")
    assert target.value == expected
    insight = engine.analysts_signal(data).insight
    assert expected in insight.detail
    assert "+20.0%" in insight.detail  # upside is currency independent
    assert "20 analysts" in insight.detail


def test_analyst_target_without_current_price_is_shown_unconverted():
    fundamentals = {k: v for k, v in GOOD_FUNDAMENTALS.items() if k != "currentPrice"}
    report = build_report(make_data("up", currency="CAD", fundamentals=fundamentals))
    target = next(m for m in report.metrics if m.label == "Analyst mean target")
    assert target.value == "120.00"  # no conversion ratio, so no (wrong) currency symbol either


# --------------------------------------------------------------------------- watch list and main risk
def test_upcoming_earnings_is_watched_and_is_the_main_risk():
    earnings = utc_today() + timedelta(days=10)
    report = build_report(make_data("up", calendar={"Earnings Date": earnings, "Earnings Average": 1.25,
                                                    "Earnings Low": 1.1, "Earnings High": 1.4}))
    assert report.watch[0].kind == "earnings"
    assert report.watch[0].date.date() == earnings
    assert "1.25" in report.watch[0].detail and "1.10–1.40" in report.watch[0].detail
    assert report.main_risk.title == "Upcoming earnings"
    assert any("Earnings on" in c for c in report.scenarios[0].conditions)


def test_earnings_between_21_and_90_days_is_watched_but_not_the_main_risk():
    report = build_report(make_data("up", calendar={"Earnings Date": utc_today() + timedelta(days=40)}))
    assert report.watch[0].kind == "earnings"
    assert report.main_risk.title != "Upcoming earnings"


@pytest.mark.parametrize("offset", [-1, -30, 91, 200])
def test_past_or_far_earnings_are_ignored(offset):
    when = utc_today() + timedelta(days=offset)
    for value in (when, datetime(when.year, when.month, when.day, 14, tzinfo=timezone.utc)):
        report = build_report(make_data("up", calendar={"Earnings Date": value}))
        assert all(w.kind != "earnings" for w in report.watch)
        assert report.main_risk.title != "Upcoming earnings"


def test_watch_list_has_at_most_3_items():
    today = utc_today()
    data = make_data("up", calendar={"Earnings Date": today + timedelta(days=5),
                                     "Ex-Dividend Date": today + timedelta(days=3)})
    report = build_report(data)  # earnings, dividend, price level and an overbought RSI all qualify
    assert len(report.watch) == 3
    assert [w.kind for w in report.watch] == ["earnings", "dividend", "price_level"]
    for data in (make_data("up"), make_data("down"), crypto_up(), make_data("flat", asset_type="crypto")):
        assert 1 <= len(build_report(data).watch) <= 3


def test_only_dated_events_carry_a_date():
    report = build_report(make_data("up", calendar={"Earnings Date": utc_today() + timedelta(days=5)}))
    for item in report.watch:
        assert (item.date is not None) == (item.kind in ("earnings", "dividend"))


# --------------------------------------------------------------------------- stale data
@pytest.mark.parametrize("asset_type,age,stale", [
    ("stock", timedelta(hours=1), False),
    ("stock", timedelta(days=3), False),  # a long weekend is not stale
    ("stock", timedelta(days=5), True),
    ("crypto", timedelta(hours=1), False),
    ("crypto", timedelta(days=1), False),
    ("crypto", timedelta(days=3), True),
])
def test_stale_detection(asset_type, age, stale):
    end = datetime.now(timezone.utc) - age
    report = build_report(make_data("up", asset_type=asset_type, end=end))
    assert report.stale is stale
    if stale:
        assert report.stale_reason and engine.fmt_date(end) in report.stale_reason
    else:
        assert report.stale_reason is None
    assert report.period.end == end
    assert report.period.days == 364


# --------------------------------------------------------------------------- nothing is invented
THRESHOLDS = {"14", "30", "70"}  # RSI period and overbought / oversold levels quoted in the text


def metric_numbers(report):
    found = set()
    for m in report.metrics:
        found |= _numbers(m.value) | _numbers(m.label)
    return found


@pytest.mark.parametrize("data", [
    make_data("up", fundamentals=dict(GOOD_FUNDAMENTALS)),
    make_data("down", fundamentals=dict(BAD_FUNDAMENTALS)),
    make_data("flat"),
    make_data("up", n=45),
    make_data("flat", asset_type="crypto", symbol="SOL"),
], ids=["up", "down", "flat", "short", "crypto"])
def test_numbers_in_the_text_come_from_the_metrics(data):
    report = build_report(data)
    allowed = metric_numbers(report) | THRESHOLDS
    texts = [report.summary, report.bottom_line, *report.reasons, *[i.detail for i in report.insights],
             *[i.title for i in report.insights]]
    for text in texts:
        assert _numbers(text) <= allowed, (text, _numbers(text) - allowed)


def test_every_possible_insight_uses_only_metric_numbers():
    stock = make_data("up", fundamentals={**GOOD_FUNDAMENTALS, "targetMeanPrice": 133.0})  # +33.0% upside
    crypto = crypto_up(coin={**COIN, "total_volume": 1.0e8})
    problems = []
    for data in (stock, crypto):
        facts = engine.calculate_facts(data)
        allowed = metric_numbers(build_report(data)) | THRESHOLDS
        signals = [engine.trend_signal(facts, data), engine.momentum_signal(facts), engine.rsi_signal(facts),
                   engine.volume_signal(facts), engine.fundamentals_signal(data), engine.valuation_signal(data),
                   engine.analysts_signal(data), *engine.crypto_signals(facts, data)]
        for signal in filter(None, signals):
            extra = _numbers(signal.insight.detail) - allowed
            if extra:
                problems.append((signal.key, sorted(extra)))
    assert problems == []


# --------------------------------------------------------------------------- schema
@pytest.mark.parametrize("data", [make_data("up", fundamentals=dict(GOOD_FUNDAMENTALS)), crypto_up(),
                                  make_data("up", n=10)], ids=["stock", "crypto", "insufficient"])
def test_report_validates_and_round_trips_through_json(data):
    report = build_report(data)
    text = report.model_dump_json()
    parsed = json.loads(text)
    assert parsed["engine"] == "rules"
    assert parsed["cached"] is False
    again = AnalystReport.model_validate_json(text)
    assert again == report
    assert AnalystReport.model_validate(report.model_dump()) == report


def test_asset_info():
    report = build_report(make_data("up", symbol="nvda", currency="EUR", name="NVIDIA Corporation"))
    assert report.asset.symbol == "NVDA"
    assert report.asset.name == "NVIDIA Corporation"
    assert report.asset.currency == "EUR"
    assert report.asset.type == "stock"
    assert report.asset.price == pytest.approx(make_closes("up", 365)[-1])
    assert report.metrics[0].label == "Last price" and report.metrics[0].value.startswith("€")
    assert report.disclaimer == engine.DISCLAIMER
