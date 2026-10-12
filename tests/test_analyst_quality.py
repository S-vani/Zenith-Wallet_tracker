"""
Regressions for the report-quality review: stablecoins, loss-making companies, wording that matches where the price
actually is, short histories, missing prices and listing currencies.
"""
import asyncio
import math
import re

import pytest

import backend.services.asset_services as services
from backend.analyst.engine import build_report, fmt_money, fmt_pct
from tests.analyst_helpers import COIN, GOOD_FUNDAMENTALS, make_closes, make_data

ALL_TEXT_FIELDS = ("summary", "bottom_line")


def all_text(report) -> str:
    parts = [report.summary, report.bottom_line or "", *report.reasons]
    parts += [i.title + " " + i.detail for i in report.insights]
    parts += [s.summary + " " + " ".join(s.conditions) for s in report.scenarios]
    parts += [w.title + " " + w.detail for w in report.watch]
    if report.main_risk:
        parts.append(report.main_risk.title + " " + report.main_risk.detail)
    return " ".join(parts)


# --------------------------------------------------------------------------- stablecoins
def stablecoin(shape="up", currency="CAD"):
    # an FX drift of ~3% looks like an "uptrend" in CAD terms
    closes = [1.36 * (1 + 0.03 * i / 364) for i in range(365)] if shape == "up" else [1.0] * 365
    data = make_data("flat", asset_type="crypto", symbol="USDT", currency=currency, name="Tether",
                     coin={**COIN, "id": "tether", "price_usd": 1.0001, "ath": 1.32, "ath_change_percentage": -0.5},
                     is_stablecoin=True)
    data.closes = closes
    return data


@pytest.mark.parametrize("currency", ["CAD", "USD"])
def test_stablecoins_are_neutral_with_a_peg_story(currency):
    report = build_report(stablecoin(currency=currency))
    assert report.sentiment == "neutral"
    text = all_text(report)
    for word in ("Uptrend", "Downtrend", "momentum", "new highs", "all-time high"):
        assert word not in text, word
    assert report.main_risk.title == "Losing the peg"
    assert any(w.title == "The $1.00 peg" for w in report.watch)
    if currency != "USD":
        assert "exchange rate" in report.summary


# --------------------------------------------------------------------------- loss-making companies
def test_negative_margins_are_shown_as_losses_and_never_solid():
    fundamentals = {**GOOD_FUNDAMENTALS, "revenueGrowth": 0.60, "earningsGrowth": None,
                    "profitMargins": -2.49, "operatingMargins": -2.61}
    report = build_report(make_data("down", fundamentals=fundamentals))
    margin = next(m for m in report.metrics if m.label == "Profit margin")
    assert margin.value.startswith("−")
    fundamentals_insight = next((i for i in report.insights if i.kind == "fundamentals"), None)
    if fundamentals_insight:
        assert fundamentals_insight.title in ("Weak fundamentals", "Mixed fundamentals")
        assert "a loss" in fundamentals_insight.detail


def test_thin_margins_are_not_solid():
    fundamentals = {**GOOD_FUNDAMENTALS, "revenueGrowth": 0.05, "earningsGrowth": 0.0, "profitMargins": 0.037}
    report = build_report(make_data("flat", fundamentals=fundamentals))
    insight = next((i for i in report.insights if i.kind == "fundamentals"), None)
    assert insight is None or insight.title != "Solid fundamentals"


# --------------------------------------------------------------------------- wording matches the price position
def test_conditions_when_price_is_below_its_long_term_average():
    report = build_report(make_data("down"))
    bull, _, bear = report.scenarios
    assert any(c.startswith("A recovery above the 200-day average") for c in bull.conditions)
    assert any(c.startswith("The price stays below the 200-day average") for c in bear.conditions)
    assert not any("stays above" in c for c in bull.conditions)


def test_conditions_when_price_is_above_its_long_term_average():
    report = build_report(make_data("up"))
    bull, _, bear = report.scenarios
    assert any("stays above the 200-day average" in c for c in bull.conditions)
    assert any("break below the 200-day average" in c for c in bear.conditions)


def test_price_level_advice_never_contradicts_itself():
    for shape in ("up", "down", "flat"):
        report = build_report(make_data(shape))
        level = next(w for w in report.watch if w.kind == "price_level")
        assert "support below would support" not in level.detail
        assert "resistance above would support" not in level.detail
        assert "0.0% from the current price" not in level.detail


def test_grammar_in_bottom_line_and_summary():
    for shape in ("up", "down"):
        report = build_report(make_data(shape, asset_type="crypto", symbol="SOL", coin=dict(COIN),
                                        btc_closes=make_closes(shape, 365)))
        assert "driven mainly by up" not in report.bottom_line
        assert "driven mainly by down" not in report.bottom_line
        assert "On the other side:" not in report.summary
        assert "bitcoin dependence" not in report.bottom_line  # proper noun keeps its capital


def test_no_buy_or_sell_wording():
    report = build_report(make_data("up", fundamentals={**GOOD_FUNDAMENTALS, "recommendationKey": "strong_buy",
                                                       "recommendationMean": 1.3}))
    text = all_text(report).lower() + " ".join(m.value.lower() for m in report.metrics)
    assert not re.search(r"(strong )?(buy|sell)", text)  # "buyers"/"sellers" are fine, advice isn't


# --------------------------------------------------------------------------- short histories
def test_short_history_caps_confidence_and_labels_honestly():
    report = build_report(make_data("up", n=84, fundamentals=dict(GOOD_FUNDAMENTALS)))
    assert report.confidence == "low"
    labels = [m.label for m in report.metrics]
    assert not any("52-week" in label or "(1 year)" in label for label in labels)
    assert any("days of price history" in limitation for limitation in report.limitations)


def test_correlation_needs_enough_returns():
    report = build_report(make_data("up", n=40, asset_type="crypto", symbol="NEW", coin=dict(COIN),
                                    btc_closes=make_closes("up", 365)))
    assert not any(m.label.startswith("Correlation with BTC") for m in report.metrics)


def test_no_data_at_all_reads_as_not_found():
    report = build_report(make_data("up", n=0))
    assert report.status == "insufficient_data"
    assert "No market data was found" in report.summary


# --------------------------------------------------------------------------- formatting & conversion
def test_formatters_survive_nan_and_use_real_minus_signs():
    assert fmt_money(math.nan, "CAD") == "n/a"
    assert fmt_pct(math.nan) == "n/a"
    assert fmt_pct(-0.25).startswith("−")


@pytest.mark.parametrize("currency,expected", [("CAD", 1.0), ("USD", 1.4), ("GBp", 1.4 / 0.8 / 100),
                                               ("EUR", 1.4 / 0.9)])
def test_listing_currency_converts_to_cad(monkeypatch, currency, expected):
    monkeypatch.setitem(services._usd_rates_cache, "rates", {"EUR": 0.9, "GBP": 0.8})
    monkeypatch.setitem(services._usd_rates_cache, "time", 10 ** 12)  # fresh: no network call

    async def fake_rates():
        return {"usd_to_cad": 1.4, "usd": 0.7, "eur": 0.6}

    monkeypatch.setattr(services, "get_all_conversion_rates", fake_rates)
    assert asyncio.run(services.get_native_to_cad_factor(currency)) == pytest.approx(expected)
