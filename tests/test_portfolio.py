"""/holdings, /dashboard, /prices/history and /portfolio/history (market data comes from the FakeMarket stub)."""
from datetime import datetime, timedelta, timezone

import pytest

import backend.routes.assets as routes_module
from conftest import RATES

AAPL_CAD = 100 * RATES["usd_to_cad"]  # AAPL trades at 100 USD in the fake market
BTC_CAD = 50000  # BTC-CAD in the fake market


# ---------------------------------------------------------------------------------------------------------------------
# /holdings
# ---------------------------------------------------------------------------------------------------------------------
def test_holdings_empty(client, user):
    assert client.get("/holdings", headers=user.headers).json() == []


def test_holdings_values(client, user, buy):
    buy(user, "AAPL", 2, 100)
    buy(user, "AAPL", 2, 200)
    buy(user, "btc", 0.5, 40000, asset_type="crypto")

    holdings = {h["symbol"]: h for h in client.get("/holdings", headers=user.headers).json()}

    assert set(holdings) == {"AAPL", "btc"}
    assert holdings["AAPL"]["quantity"] == pytest.approx(4)
    assert holdings["AAPL"]["price_paid"] == pytest.approx(600)
    assert holdings["AAPL"]["current_price"] == pytest.approx(4 * AAPL_CAD)
    assert holdings["AAPL"]["type"] == "stock"
    assert holdings["btc"]["current_price"] == pytest.approx(0.5 * BTC_CAD)
    assert holdings["btc"]["type"] == "crypto"


def test_holdings_partial_sell_keeps_average_price(client, user, buy, sell):
    buy(user, "AAPL", 4, 100)
    sell(user, "AAPL", 1, 150)
    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["quantity"] == pytest.approx(3)
    assert h["price_paid"] == pytest.approx(300)


def test_fully_sold_positions_disappear(client, user, buy, sell):
    buy(user, "ETH", 0.3, 2000, asset_type="crypto", api_id="eth")
    sell(user, "ETH", 0.1, 2000, asset_type="crypto", api_id="eth")
    sell(user, "ETH", 0.2, 2000, asset_type="crypto", api_id="eth")
    buy(user, "AAPL", 1, 100)
    sell(user, "AAPL", 1, 100)

    assert client.get("/holdings", headers=user.headers).json() == []


def test_holdings_in_usd(client, make_user, buy):
    usd_user = make_user(currency="USD")
    buy(usd_user, "AAPL", 1, 70)  # 70 USD -> 100 CAD stored
    [h] = client.get("/holdings", headers=usd_user.headers).json()
    assert h["price_paid"] == pytest.approx(70)
    assert h["current_price"] == pytest.approx(AAPL_CAD * RATES["usd"])


def test_holdings_with_unknown_price_are_worth_zero(client, user, buy):
    buy(user, "DELISTED", 1, 100)
    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["current_price"] == 0


# ---------------------------------------------------------------------------------------------------------------------
# /dashboard
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("period", ["day", "week", "month", "year", "all"])
def test_dashboard_empty(client, user, period):
    res = client.get(f"/dashboard?current_timeperiod={period}", headers=user.headers)
    assert res.json() == {"value": 0.0, "curr_timeperiod": 0.0}


def test_dashboard_all_time_includes_realized_and_unrealized_profit(client, user, buy, sell):
    buy(user, "AAPL", 3, 100)
    sell(user, "AAPL", 1, 150)  # +50 realized

    res = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()
    assert res["value"] == pytest.approx(2 * AAPL_CAD)
    assert res["curr_timeperiod"] == pytest.approx(2 * (AAPL_CAD - 100) + 50)


def test_dashboard_handles_crypto_with_lowercase_ids(client, user, buy):
    buy(user, "btc", 0.5, 40000, asset_type="crypto")

    res = client.get("/dashboard?current_timeperiod=all", headers=user.headers)
    assert res.status_code == 200, res.text
    assert res.json()["value"] == pytest.approx(0.5 * BTC_CAD)
    assert res.json()["curr_timeperiod"] == pytest.approx(0.5 * (BTC_CAD - 40000))


@pytest.mark.parametrize("period", ["day", "week", "month", "year"])
def test_dashboard_period_profit_ignores_new_deposits(client, user, buy, period):
    # bought just now: the profit for the period is the gain on it, not the money put in
    buy(user, "AAPL", 2, 100)
    buy(user, "btc", 0.1, 45000, asset_type="crypto")

    res = client.get(f"/dashboard?current_timeperiod={period}", headers=user.headers).json()
    assert res["value"] == pytest.approx(2 * AAPL_CAD + 0.1 * BTC_CAD)
    assert res["curr_timeperiod"] == pytest.approx(2 * (AAPL_CAD - 100) + 0.1 * (BTC_CAD - 45000))


def test_dashboard_period_profit_for_older_holdings(client, user, buy, db):
    # held since before the period with no new money in: profit = value now - value then (same fake price) = 0
    tx = buy(user, "AAPL", 2, 100)
    db.set_created_at(tx["id"], datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3))

    res = client.get("/dashboard?current_timeperiod=day", headers=user.headers).json()
    assert res["value"] == pytest.approx(2 * AAPL_CAD)
    assert res["curr_timeperiod"] == pytest.approx(0)


def test_dashboard_in_eur(client, make_user, buy):
    eur_user = make_user(currency="EUR")
    buy(eur_user, "AAPL", 1, 60)  # 100 CAD

    res = client.get("/dashboard?current_timeperiod=all", headers=eur_user.headers).json()
    assert res["value"] == pytest.approx(AAPL_CAD * RATES["eur"])
    assert res["curr_timeperiod"] == pytest.approx((AAPL_CAD - 100) * RATES["eur"])


def test_dashboard_rejects_unknown_period(client, user):
    assert client.get("/dashboard?current_timeperiod=decade", headers=user.headers).status_code == 422


def test_dashboard_without_period(client, user, buy):
    buy(user, "AAPL", 1, 100)
    assert client.get("/dashboard", headers=user.headers).status_code != 500


# ---------------------------------------------------------------------------------------------------------------------
# /prices/history
# ---------------------------------------------------------------------------------------------------------------------
def hourly_points(start, hours):
    return [{"time": (start + timedelta(hours=h)).isoformat(), "price": float(h)} for h in range(hours)]


@pytest.fixture
def stub_history(monkeypatch):
    calls = []

    def _stub(points):
        async def fake(symbol, type, range, currency):
            calls.append((symbol, type, range, currency))
            ticker = f"{symbol}-USD" if type == "crypto" else symbol
            return list(points), ticker

        monkeypatch.setattr(routes_module, "get_history_of_prices", fake)
        return calls

    return _stub


def test_price_history_1d_stock_keeps_only_the_latest_session(client, user, stub_history):
    # two trading sessions in New York time
    ny = timezone(timedelta(hours=-4))
    day1 = [{"time": datetime(2024, 6, 3, 9, 30, tzinfo=ny).replace(hour=9 + i).isoformat(), "price": 1.0}
            for i in range(7)]
    day2 = [{"time": datetime(2024, 6, 4, 9, 30, tzinfo=ny).replace(hour=9 + i).isoformat(), "price": 2.0}
            for i in range(7)]
    calls = stub_history(day1 + day2)

    res = client.get("/prices/history?symbol=AAPL&type=stock&range=1D", headers=user.headers)
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "AAPL"
    assert body["range"] == "1D"
    assert body["data"] == day2
    assert calls == [("AAPL", "stock", "1D", "CAD")]


def test_price_history_1d_crypto_keeps_the_last_24_hours(client, user, stub_history):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    points = hourly_points(now - timedelta(hours=47), 48)
    stub_history(points)

    body = client.get("/prices/history?symbol=BTC&type=crypto&range=1D", headers=user.headers).json()
    assert body["symbol"] == "BTC-USD"
    assert 23 <= len(body["data"]) <= 25
    cutoff = datetime.now(timezone.utc) - timedelta(days=1, minutes=1)
    assert all(datetime.fromisoformat(p["time"]) >= cutoff for p in body["data"])
    assert body["data"][-1] == points[-1]


@pytest.mark.parametrize("range_", ["1W", "1M", "1Y", "5Y"])
def test_price_history_longer_ranges_are_not_trimmed(client, user, stub_history, range_):
    points = hourly_points(datetime(2024, 1, 1, tzinfo=timezone.utc), 72)
    stub_history(points)
    body = client.get(f"/prices/history?symbol=AAPL&type=stock&range={range_}", headers=user.headers).json()
    assert body["data"] == points


def test_price_history_empty(client, user, stub_history):
    stub_history([])
    body = client.get("/prices/history?symbol=NOPE&type=stock&range=1D", headers=user.headers).json()
    assert body["data"] == []


def test_price_history_rejects_unknown_range(client, user):
    assert client.get("/prices/history?symbol=AAPL&type=stock&range=2D", headers=user.headers).status_code == 422


def test_price_history_end_to_end_with_fake_market(client, make_user):
    usd_user = make_user(currency="USD")
    body = client.get("/prices/history?symbol=BTC&type=crypto&range=1W", headers=usd_user.headers).json()
    assert body["symbol"] == "BTC-USD"
    assert body["data"][0]["price"] == pytest.approx(40000 * RATES["usd_to_cad"] * RATES["usd"])


# ---------------------------------------------------------------------------------------------------------------------
# /portfolio/history
# ---------------------------------------------------------------------------------------------------------------------
def test_portfolio_history_empty_portfolio(client, user):
    data = client.get("/portfolio/history?range=7", headers=user.headers).json()
    assert len(data) == 169
    assert all(point["value"] == 0 for point in data)
    times = [datetime.fromisoformat(p["time"]) for p in data]
    assert times == sorted(times)
    assert abs(times[-1] - datetime.now(timezone.utc)) < timedelta(seconds=30)


def test_portfolio_history_values(client, user, buy, db):
    tx = buy(user, "AAPL", 2, 100)
    db.set_created_at(tx["id"], datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2))
    buy(user, "btc", 0.1, 40000, asset_type="crypto")  # bought now, so only in the last point

    data = client.get("/portfolio/history?range=7", headers=user.headers).json()
    assert len(data) == 169

    assert data[0]["value"] == 0  # before anything was bought
    # history uses the BTC-USD pair (40000 USD) converted to CAD
    assert data[-1]["value"] == pytest.approx(2 * AAPL_CAD + 0.1 * 40000 * RATES["usd_to_cad"])
    assert data[-2]["value"] == pytest.approx(2 * AAPL_CAD)


def test_portfolio_history_1d_point_count(client, user):
    assert len(client.get("/portfolio/history?range=1", headers=user.headers).json()) == 289
