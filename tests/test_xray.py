"""Portfolio X-Ray: the pure maths with made-up data, and the endpoint end to end with the fake market."""
import random
from datetime import date, timedelta

import pytest

from backend.services import profiles, xray


def test_concentration():
    c = xray.concentration({"AAPL": 0.5, "MSFT": 0.3, "BTC": 0.2})
    assert c["top"] == {"symbol": "AAPL", "weight": 0.5}
    assert c["top3_weight"] == pytest.approx(1.0)
    assert c["effective_holdings"] == pytest.approx(1 / (0.25 + 0.09 + 0.04))


def test_look_through_opens_funds_and_finds_hidden_overlap():
    weights = {"AAPL": 0.4, "VOO": 0.5, "btc": 0.1}
    types = {"AAPL": "stock", "VOO": "stock", "btc": "crypto"}
    profiles_ = {
        "AAPL": {"sector": "Technology", "country": "United States", "quote_type": "EQUITY"},
        "VOO": {"quote_type": "ETF", "name": "Vanguard S&P 500 ETF",
                "fund_sectors": {"technology": 0.3, "healthcare": 0.7},
                "fund_holdings": [{"symbol": "AAPL", "name": "Apple", "weight": 0.07}]},
    }
    out = xray.look_through(weights, types, profiles_)
    sectors = {s["name"]: s["weight"] for s in out["sectors"]}
    assert sectors["Technology"] == pytest.approx(0.4 + 0.15)
    assert sectors["Healthcare"] == pytest.approx(0.35)
    assert sectors["Crypto"] == pytest.approx(0.1)
    regions = {r["name"]: r["weight"] for r in out["regions"]}
    assert regions == {"United States": pytest.approx(0.9), "Crypto": pytest.approx(0.1)}
    apple = next(c for c in out["companies"] if c["name"] == "AAPL")
    assert apple["weight"] == pytest.approx(0.4 + 0.035) and apple["via"] == ["VOO"]


def test_region_guesses_from_fund_names():
    assert xray.region_of({"quote_type": "ETF", "name": "iShares Core Equity ETF Portfolio", "category": "Global"},
                          "XEQT.TO", "stock") == "Global (fund)"
    assert xray.region_of({"quote_type": "ETF", "name": "iShares S&P/TSX 60"}, "XIU.TO", "stock") == "Canada"
    assert xray.region_of({}, "SHOP.TO", "stock") == "Canada"


def _walk(seed, days, scale=0.01):
    rnd = random.Random(seed)
    return [rnd.gauss(0, scale) for _ in range(days)]


def test_risk_stats_beta_volatility_drawdown_and_pairs():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(120)]
    market = _walk(1, 120)
    noise = _walk(2, 120, 0.002)
    returns = {
        "A": {d: 2 * m + n for d, m, n in zip(days, market, noise)},  # beta ~2
        "B": {d: 2 * m for d, m in zip(days, market)},  # moves with A
        "C": {d: r for d, r in zip(days, _walk(3, 120))},  # unrelated
    }
    bench = dict(zip(days, market))
    stats = xray.risk_stats({"A": 0.4, "B": 0.4, "C": 0.2}, returns, bench)
    assert stats["days"] == 120
    assert stats["holding_betas"]["A"] == pytest.approx(2.0, abs=0.1)
    assert stats["beta"] == pytest.approx(1.6, abs=0.2)
    assert stats["volatility"] > 0 and stats["max_drawdown"] <= 0
    assert stats["correlated_pairs"][0]["a"] in ("A", "B") and stats["correlated_pairs"][0]["correlation"] > 0.9


def test_risk_stats_needs_enough_history():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
    assert xray.risk_stats({"A": 1.0}, {"A": dict.fromkeys(days, 0.01)}, None) == {"days": 10}


def test_stress_tests_and_score():
    weights = {"AAPL": 0.6, "btc": 0.4}
    types = {"AAPL": "stock", "btc": "crypto"}
    exposure = {"sectors": [{"name": "Technology", "weight": 0.6}, {"name": "Crypto", "weight": 0.4}],
                "regions": [], "companies": []}
    risk = {"holding_betas": {"AAPL": 1.5, "btc": 2.0}, "volatility": 0.5}
    tests = {t["name"]: t for t in xray.stress_tests(10_000, weights, types, exposure, risk, "CAD",
                                                      {"AAPL": "USD", "btc": None})}
    assert tests["Stock market falls 20%"]["change_pct"] == pytest.approx(0.6 * -0.3 + 0.4 * -0.4)
    assert tests["Crypto halves"]["change"] == pytest.approx(-2000)
    assert tests["Tech sells off 30%"]["change_pct"] == pytest.approx(-0.18)
    assert tests["The Canadian dollar falls 10%"]["change_pct"] == pytest.approx(0.06)
    score = xray.diversification_score(xray.concentration(weights), exposure, risk, weights, types)
    assert score["score"] < 50 and score["label"] == "Concentrated" and score["reasons"][0] == "top"


def test_findings_are_built_from_the_numbers():
    conc = xray.concentration({"AAPL": 0.5, "MSFT": 0.5})
    exposure = {"sectors": [{"name": "Technology", "weight": 1.0}], "regions": [],
                "companies": [{"name": "NVDA", "weight": 0.05, "via": ["QQQ"]}]}
    out = xray.findings(1000, conc, exposure, {"beta": 1.4, "max_drawdown": -0.3}, [],
                        lambda v: f"${v:,.2f}")
    titles = [f["title"] for f in out]
    assert titles[0] == "AAPL is 50% of your portfolio"
    assert "100% in Technology" in titles and "Moves 1.4× the market" in titles
    assert "You own more NVDA than it looks" in titles
    assert any("$50.00" in f["text"] for f in out)  # a 10% drop in half the portfolio
    for f in out:
        assert "buy" not in f["text"].lower() and "sell" not in f["text"].lower()


def test_xray_endpoint(client, user, buy, monkeypatch):
    monkeypatch.setattr(profiles, "_cache", {})
    monkeypatch.setattr(xray, "_cache", {})
    assert client.get("/portfolio/xray", headers=user.headers).json()["empty"] is True
    buy(user, "AAPL", 2, 100)
    buy(user, "btc", 0.01, 40000, asset_type="crypto")
    monkeypatch.setattr(xray, "_cache", {})
    body = client.get("/portfolio/xray", headers=user.headers).json()
    assert body["empty"] is False and body["currency"] == "CAD"
    assert {h["symbol"] for h in body["holdings"]} == {"AAPL", "BTC"}
    assert sum(h["weight"] for h in body["holdings"]) == pytest.approx(1.0)
    assert 0 <= body["score"]["score"] <= 100
    assert any(t["name"] == "Crypto halves" for t in body["stress_tests"])
    assert client.get("/portfolio/xray").status_code == 401
