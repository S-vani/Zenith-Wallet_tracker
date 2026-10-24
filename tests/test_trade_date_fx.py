"""
Backdated trades typed in USD / EUR are stored in CAD at the exchange rate of their own date (Yahoo's daily
USDCAD=X / EURCAD=X history, "latest close known at that time"), which the capital gains / ACB report relies on.
Recent trades, CAD trades, and trades whose rate history is unavailable keep using the current rate.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import backend.routes.imports as import_routes
import backend.services.asset_services as services

from conftest import RATES

# CAD per 1 unit, by year (round numbers; the current rates in RATES are 1/0.7 and 1/0.6)
USD_CAD = {2022: 1.25, 2023: 1.30, 2024: 1.35, 2025: 1.38, 2026: 1.39}
EUR_CAD = {2022: 1.40, 2023: 1.45, 2024: 1.50, 2025: 1.55, 2026: 1.60}
FX = {"USDCAD=X": USD_CAD, "EURCAD=X": EUR_CAD}


class FxTicker:
    def __init__(self, fake, symbol):
        self.fake, self.symbol = fake, symbol

    def history(self, start=None, end=None, period=None, interval=None):
        self.fake.calls.append((self.symbol, period, interval))
        if self.fake.mode == "error":
            raise RuntimeError("Yahoo is down")
        if self.fake.mode == "empty":
            return pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([], tz="UTC"))
        index = pd.date_range(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp.now(tz="UTC").floor("D"), freq="D")
        return pd.DataFrame({"Close": [FX[self.symbol][day.year] for day in index]}, index=index)


@pytest.fixture
def fx(market, monkeypatch):
    """Daily FX histories for USDCAD=X / EURCAD=X; `fx.calls` lists the history requests, `fx.mode` breaks them."""
    real_ticker = market.Ticker
    state = type("FxFake", (), {})()
    state.calls, state.mode = [], "ok"
    monkeypatch.setattr(market, "Ticker",
                        lambda symbol: FxTicker(state, symbol.upper()) if symbol.upper() in FX
                        else real_ticker(symbol))
    monkeypatch.setattr(import_routes, "_preview_times", {})
    monkeypatch.setattr(import_routes, "_import_times", {})
    return state


def at(*args):
    return datetime(*args, tzinfo=timezone.utc).isoformat()


def post(client, owner, expect=200, **overrides):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 70, "quantity": 1,
            "api_id": "AAPL"}
    body.update(overrides)
    res = client.post("/transactions", headers=owner.headers, json=body)
    assert res.status_code == expect, res.text
    return res.json()


def stored(db, tx_id):
    return float(db.get_transaction(tx_id).price_of_one)


def test_backdated_usd_buy_uses_the_rate_of_its_date(client, make_user, db, fx):
    usd = make_user(currency="USD")
    tx = post(client, usd, created_at=at(2024, 6, 15, 14))
    assert stored(db, tx["id"]) == pytest.approx(70 * USD_CAD[2024])
    assert fx.calls == [("USDCAD=X", "max", "1d")]
    # shown in the user's own currency exactly as typed
    [listed] = client.get("/transactions", headers=usd.headers).json()
    assert listed["price_of_one"] == pytest.approx(70)

    # a second backdated trade reuses the cached history
    eur = make_user(currency="EUR")
    tx2 = post(client, usd, created_at=at(2023, 6, 15))
    post(client, eur, price_of_one=60, created_at=at(2023, 6, 15))
    assert stored(db, tx2["id"]) == pytest.approx(70 * USD_CAD[2023])
    assert fx.calls == [("USDCAD=X", "max", "1d"), ("EURCAD=X", "max", "1d")]


def test_latest_close_known_at_the_time_is_used(client, make_user, db, fx):
    usd = make_user(currency="USD")
    # the 2024-01-01 bar only closes at the end of that day, so a trade at noon still uses 2023-12-31's close
    tx = post(client, usd, created_at=at(2024, 1, 1, 12))
    assert stored(db, tx["id"]) == pytest.approx(70 * USD_CAD[2023])


def test_recent_and_cad_trades_are_unchanged(client, make_user, db, fx):
    usd = make_user(currency="USD")
    now_trade = post(client, usd)
    recent = post(client, usd, created_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat())
    assert stored(db, now_trade["id"]) == pytest.approx(70 / RATES["usd"])
    assert stored(db, recent["id"]) == pytest.approx(70 / RATES["usd"])

    cad = make_user(currency="CAD")
    old = post(client, cad, price_of_one=100, created_at=at(2023, 6, 15))
    assert stored(db, old["id"]) == pytest.approx(100)
    assert fx.calls == []  # no history needed for any of them


@pytest.mark.parametrize("mode", ["empty", "error"])
def test_unavailable_history_falls_back_to_the_current_rate(client, make_user, db, fx, mode):
    fx.mode = mode
    usd = make_user(currency="USD")
    tx = post(client, usd, created_at=at(2024, 6, 15))
    assert stored(db, tx["id"]) == pytest.approx(70 / RATES["usd"])


def test_dates_before_the_history_and_bad_closes_fall_back(client, make_user, db, fx):
    usd = make_user(currency="USD")
    tx = post(client, usd, created_at=at(2015, 6, 15))  # the fake history starts in 2022
    assert stored(db, tx["id"]) == pytest.approx(70 / RATES["usd"])

    history = services.PriceSeries(known=[datetime(2024, 1, 1, tzinfo=timezone.utc)], closes=[140.0])
    when = datetime(2024, 6, 1)
    assert services.cad_price_on(70, "USD", when, RATES, history) == pytest.approx(70 / RATES["usd"])


def test_update_recomputes_when_the_date_or_price_changes(client, make_user, db, fx):
    usd = make_user(currency="USD")
    tx = post(client, usd, created_at=at(2023, 6, 15))
    assert stored(db, tx["id"]) == pytest.approx(70 * USD_CAD[2023])

    def put(**changes):
        res = client.put(f"/transactions/{tx['id']}", headers=usd.headers, json=changes)
        assert res.status_code == 200, res.text

    put(created_at=at(2024, 6, 15))  # the price as typed, at the new date's rate
    assert stored(db, tx["id"]) == pytest.approx(70 * USD_CAD[2024])

    put(price_of_one=80)  # a new price keeps the trade's own date
    assert stored(db, tx["id"]) == pytest.approx(80 * USD_CAD[2024])

    put(quantity=2)  # nothing price-related: untouched
    assert stored(db, tx["id"]) == pytest.approx(80 * USD_CAD[2024])

    put(created_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())  # now recent: current rate
    assert stored(db, tx["id"]) == pytest.approx(80 / RATES["usd"])
    assert float(db.get_transaction(tx["id"]).price_entered) == pytest.approx(80)


def test_import_uses_per_date_rates_with_one_fetch_per_currency(client, make_user, db, fx):
    owner = make_user(currency="CAD")
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    rows = [
        {"line": 1, "date": "2023-06-15", "action": "BUY", "asset_type": "stock", "symbol": "AAPL",
         "quantity": 2, "price": 100, "currency": "USD"},
        {"line": 2, "date": "2024-06-15", "action": "BUY", "asset_type": "stock", "symbol": "AAPL",
         "quantity": 1, "price": 100, "currency": "USD"},
        {"line": 3, "date": "2025-06-15", "action": "SELL", "asset_type": "stock", "symbol": "AAPL",
         "quantity": 1, "price": 100, "currency": "USD"},
        {"line": 4, "date": "2024-06-15", "action": "BUY", "asset_type": "stock", "symbol": "SAP.DE",
         "quantity": 1, "price": 100, "currency": "EUR"},
        {"line": 5, "date": "2024-06-15", "action": "BUY", "asset_type": "stock", "symbol": "SHOP.TO",
         "quantity": 1, "price": 100, "currency": "CAD"},
        {"line": 6, "date": recent, "action": "BUY", "asset_type": "stock", "symbol": "MSFT",
         "quantity": 1, "price": 100, "currency": "USD"},
    ]
    res = client.post("/transactions/import", headers=owner.headers, json={"rows": rows})
    assert res.status_code == 200, res.text
    assert sorted(fx.calls) == [("EURCAD=X", "max", "1d"), ("USDCAD=X", "max", "1d")]

    saved = {(t["symbol"], t["action"], t["created_at"][:10]): t["price_of_one"]
             for t in client.get("/transactions", headers=owner.headers).json()}  # CAD user: CAD prices
    assert saved[("AAPL", "BUY", "2023-06-15")] == pytest.approx(100 * USD_CAD[2023])
    assert saved[("AAPL", "BUY", "2024-06-15")] == pytest.approx(100 * USD_CAD[2024])
    assert saved[("AAPL", "SELL", "2025-06-15")] == pytest.approx(100 * USD_CAD[2025])
    assert saved[("SAP.DE", "BUY", "2024-06-15")] == pytest.approx(100 * EUR_CAD[2024])
    assert saved[("SHOP.TO", "BUY", "2024-06-15")] == pytest.approx(100)
    msft = next(price for (symbol, _, _), price in saved.items() if symbol == "MSFT")
    assert msft == pytest.approx(100 / RATES["usd"])


def test_failed_import_saves_nothing_after_fetching_rates(client, make_user, fx):
    owner = make_user(currency="CAD")
    rows = [{"line": 1, "date": "2024-06-15", "action": "SELL", "asset_type": "stock", "symbol": "AAPL",
             "quantity": 1, "price": 100, "currency": "USD"}]
    res = client.post("/transactions/import", headers=owner.headers, json={"rows": rows})
    assert res.status_code == 409
    assert client.get("/transactions", headers=owner.headers).json() == []


def test_capital_gains_report_uses_trade_date_rates(client, make_user, fx):
    usd = make_user(currency="USD")
    post(client, usd, price_of_one=70, created_at=at(2023, 6, 15))  # 91 CAD
    post(client, usd, action="SELL", price_of_one=84, created_at=at(2024, 6, 15))  # 113.40 CAD
    body = client.get("/reports/capital-gains", headers=usd.headers, params={"year": 2024}).json()
    [sale] = body["sales"]
    assert (sale["proceeds"], sale["acb"], sale["gain"]) == (113.4, 91.0, 22.4)
    assert any("trade date" in note for note in sale["notes"])
    assert any("exchange rate of the trade date" in note for note in body["notes"])
