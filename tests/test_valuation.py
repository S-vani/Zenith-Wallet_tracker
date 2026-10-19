"""
Regression tests for the money / valuation fixes: unpriced assets, sold-out portfolios, the return % base,
long "All" charts, closes from the future, exchange-rate outages, chart vs value card and CoinGecko's 1-year limit.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import HTTPException

import backend.analyst.data as market_data
import backend.routes.assets as routes_module
import backend.services.asset_services as services
from conftest import RATES, REAL_GET_ALL_CONVERSION_RATES

AAPL_CAD = 100 * RATES["usd_to_cad"]  # AAPL trades at 100 USD in the fake market
BTC_CAD = 50000


def now_utc():
    return datetime.now(timezone.utc)


def naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def coingecko(monkeypatch):
    """Stub CoinGecko's chart: `prices[symbol]` is a CAD price (or a list of points), calls are recorded."""
    state = type("CoinGecko", (), {})()
    state.prices = {}
    state.calls = []

    async def fake_chart(symbol, range_code, currency):
        state.calls.append((symbol.lower(), range_code, currency))
        price = state.prices.get(symbol.lower())
        if price is None:
            return []
        if isinstance(price, list):
            return price
        now = now_utc()
        return [{"time": (now - timedelta(days=d)).isoformat(), "price": price} for d in (300, 30, 2, 1)] + \
            [{"time": (now - timedelta(seconds=1)).isoformat(), "price": price}]

    monkeypatch.setattr(market_data, "coingecko_chart", fake_chart)
    return state


class BarsMarket:
    """A fake yfinance whose history() returns whatever `bars(ticker, period, interval)` gives (index, closes)."""

    def __init__(self, bars, currencies=None):
        self.bars = bars
        self.currencies = currencies or {}
        self.requested = []

    def Ticker(self, symbol):  # noqa: N802 - mirrors yfinance
        market = self
        symbol = symbol.upper()

        class _Ticker:
            info = {"currency": market.currencies.get(symbol, "USD")}

            def history(self, period=None, interval=None, start=None, end=None):
                market.requested.append((symbol, period, interval))
                result = market.bars(symbol, period, interval)
                if not result:
                    return pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([], tz="UTC"))
                index, closes = result
                return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(index))

        return _Ticker()


# ---------------------------------------------------------------------------------------------------------------------
# 1. assets with no Yahoo price
# ---------------------------------------------------------------------------------------------------------------------
def test_coin_missing_on_yahoo_is_priced_from_coingecko(client, user, buy, coingecko):
    coingecko.prices["pepe"] = 0.00004  # CAD
    buy(user, "pepe", 1_000_000, 0.00002, asset_type="crypto")

    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["current_price"] == pytest.approx(40)

    d = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()
    assert d["value"] == pytest.approx(40)
    assert d["curr_timeperiod"] == pytest.approx(20)
    assert d["unpriced"] == []

    history = client.get("/portfolio/history?range=7", headers=user.headers).json()
    assert history[-1]["value"] == pytest.approx(40)

    # CoinGecko's demo key is rate limited: the second round of requests is served from the cache
    calls = len(coingecko.calls)
    client.get("/holdings", headers=user.headers)
    client.get("/dashboard?current_timeperiod=all", headers=user.headers)
    assert len(coingecko.calls) == calls
    assert all(currency == "CAD" for _, _, currency in coingecko.calls)


def test_asset_with_no_price_anywhere_is_unavailable_not_zero(client, user, buy, coingecko):
    buy(user, "pepe", 1_000_000, 0.00002, asset_type="crypto")  # 20 CAD, nobody has a price
    buy(user, "AAPL", 1, 100)

    holdings = {h["symbol"]: h for h in client.get("/holdings", headers=user.headers).json()}
    assert holdings["pepe"]["current_price"] is None
    assert holdings["AAPL"]["current_price"] == pytest.approx(AAPL_CAD)

    for period in ("all", "day", "year"):
        d = client.get(f"/dashboard?current_timeperiod={period}", headers=user.headers).json()
        assert d["value"] == pytest.approx(AAPL_CAD)  # pepe left out, not counted as 0
        assert d["curr_timeperiod"] == pytest.approx(AAPL_CAD - 100)  # no -20 "loss" on pepe
        assert d["basis"] == pytest.approx(100)  # pepe's cost left out of the base too
        assert d["unpriced"] == ["pepe"]

    # empty answers are cached briefly too, so one page load doesn't keep hitting CoinGecko
    calls = len(coingecko.calls)
    client.get("/holdings", headers=user.headers)
    assert len(coingecko.calls) == calls


def test_delisted_stock_is_unavailable(client, user, buy):
    buy(user, "GONE", 2, 50)
    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["current_price"] is None
    d = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()
    assert d == {"value": 0.0, "curr_timeperiod": 0.0, "basis": 0.0, "unpriced": ["GONE"]}


def test_yahoo_outage_serves_the_last_good_prices(client, user, buy, market, monkeypatch):
    buy(user, "AAPL", 1, 100)
    assert client.get("/holdings", headers=user.headers).json()[0]["current_price"] == pytest.approx(AAPL_CAD)

    def broken(symbol):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(services, "yf", type("Down", (), {"Ticker": staticmethod(broken)}))
    for entry in services._series_cache.values():
        entry["checked"] = 0  # expired: the next request tries Yahoo again, which fails

    assert client.get("/holdings", headers=user.headers).json()[0]["current_price"] == pytest.approx(AAPL_CAD)
    d = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()
    assert d["value"] == pytest.approx(AAPL_CAD)


def test_crypto_falls_back_to_the_usd_pair(market):
    market.prices["DOGE-USD"] = 0.5  # no DOGE-CAD on Yahoo
    prices = asyncio.run(services.get_crypto_prices_at(["doge"], now_utc(), "CAD"))
    assert prices["doge"] == pytest.approx(0.5 * RATES["usd_to_cad"])


# ---------------------------------------------------------------------------------------------------------------------
# 2. selling everything keeps realized profit
# ---------------------------------------------------------------------------------------------------------------------
def test_sold_out_portfolio_keeps_realized_profit(client, user, buy, sell):
    buy(user, "AAPL", 10, 100)
    sell(user, "AAPL", 10, 140)  # +400 CAD realized

    for period in ("all", "day", "week", "month", "year"):
        d = client.get(f"/dashboard?current_timeperiod={period}", headers=user.headers).json()
        assert d["value"] == 0.0
        assert d["curr_timeperiod"] == pytest.approx(400), period
        assert d["basis"] == pytest.approx(1000), period


# ---------------------------------------------------------------------------------------------------------------------
# 3. the return % base
# ---------------------------------------------------------------------------------------------------------------------
def test_all_time_basis_is_total_invested(client, user, buy, sell):
    buy(user, "AAPL", 10, 100)  # 1000 invested
    sell(user, "AAPL", 9, 110)  # +90 realized
    d = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()
    assert d["curr_timeperiod"] == pytest.approx(90 + (AAPL_CAD - 100))  # 130
    assert d["basis"] == pytest.approx(1000)
    assert d["curr_timeperiod"] / d["basis"] * 100 == pytest.approx(13)  # was shown as +1300%


def test_period_basis_is_start_value_plus_money_put_in(client, user, buy, db):
    old = buy(user, "AAPL", 2, 100)
    db.set_created_at(old["id"], naive(now_utc() - timedelta(days=3)))
    buy(user, "AAPL", 1, 140)  # today

    d = client.get("/dashboard?current_timeperiod=day", headers=user.headers).json()
    assert d["value"] == pytest.approx(3 * AAPL_CAD)
    assert d["curr_timeperiod"] == pytest.approx(0)  # same fake price then and now, bought today at the price
    assert d["basis"] == pytest.approx(2 * AAPL_CAD + 140)


# ---------------------------------------------------------------------------------------------------------------------
# 4. the "All" chart goes back further than a year
# ---------------------------------------------------------------------------------------------------------------------
def test_all_range_uses_weekly_history_beyond_a_year(client, user, buy, db, monkeypatch):
    start = pd.Timestamp(now_utc()).floor("D") - pd.Timedelta(weeks=600)

    def bars(symbol, period, interval):
        index = pd.date_range(start=start, periods=601, freq="W", tz="UTC")
        return index, [100.0 + i for i in range(len(index))]  # rises every week

    fake = BarsMarket(bars)
    monkeypatch.setattr(services, "yf", fake)
    t = buy(user, "AAPL", 1, 100)
    db.set_created_at(t["id"], naive(now_utc() - timedelta(days=1000)))

    data = client.get("/portfolio/history?range=1000", headers=user.headers).json()
    assert len(data) == 366
    assert ("AAPL", "10y", "1wk") in fake.requested
    first_year = [p["value"] for p in data if datetime.fromisoformat(p["time"]) < now_utc() - timedelta(days=640)]
    assert first_year and len(set(first_year)) > 30  # moves with the weekly prices instead of sitting flat


@pytest.mark.parametrize("days, label", [(365, "1Y"), (1000, "5Y"), (3650, "MAX")])
def test_timespan_labels_for_long_ranges(days, label):
    timestamps, t = services.calculate_timespans_for_portfolio_history(days)
    assert t == label and len(timestamps) == 366


# ---------------------------------------------------------------------------------------------------------------------
# 5. never use a close that hadn't happened yet
# ---------------------------------------------------------------------------------------------------------------------
def test_stock_daily_bar_is_not_used_before_its_close(monkeypatch):
    # yfinance daily bars are labelled 00:00 New York time (04:00 UTC) but hold that day's 16:00 close
    day2 = pd.Timestamp(now_utc() - timedelta(days=100)).floor("D") + pd.Timedelta(hours=4)
    day1 = day2 - pd.Timedelta(days=1)

    def bars(symbol, period, interval):
        assert interval == "1d"
        return [day1, day2], [100.0, 110.0]

    monkeypatch.setattr(services, "yf", BarsMarket(bars))
    before_open = (day2 + pd.Timedelta(hours=6)).to_pydatetime()  # 06:00 New York: the latest close is day 1's
    prices = asyncio.run(services.get_stock_prices_at(["AAPL"], before_open, "CAD"))
    assert prices["AAPL"] == pytest.approx(100 * RATES["usd_to_cad"])

    next_day = (day2 + pd.Timedelta(days=1, hours=1)).to_pydatetime()
    prices = asyncio.run(services.get_stock_prices_at(["AAPL"], next_day, "CAD"))
    assert prices["AAPL"] == pytest.approx(110 * RATES["usd_to_cad"])


def test_crypto_daily_bar_is_not_used_before_its_close(monkeypatch):
    day2 = pd.Timestamp(now_utc() - timedelta(days=100)).floor("D")
    day1 = day2 - pd.Timedelta(days=1)
    monkeypatch.setattr(services, "yf", BarsMarket(lambda s, p, i: ([day1, day2], [10.0, 20.0])))

    noon = (day2 + pd.Timedelta(hours=12)).to_pydatetime()
    assert asyncio.run(services.get_crypto_prices_at(["btc"], noon, "CAD")) == {"btc": pytest.approx(10.0)}


def test_hourly_bar_is_used_only_once_it_has_ended(monkeypatch):
    hour = pd.Timestamp(now_utc() - timedelta(days=10)).floor("h")
    monkeypatch.setattr(services, "yf", BarsMarket(lambda s, p, i: ([hour, hour + pd.Timedelta(hours=1)], [1.0, 2.0])))

    inside_second = (hour + pd.Timedelta(minutes=90)).to_pydatetime()
    assert asyncio.run(services.get_crypto_prices_at(["eth"], inside_second, "CAD")) == {"eth": pytest.approx(1.0)}


def test_the_live_bar_gives_the_current_price(monkeypatch):
    today = pd.Timestamp(now_utc()).floor("min") - pd.Timedelta(minutes=2)  # bar still in progress
    monkeypatch.setattr(services, "yf",
                        BarsMarket(lambda s, p, i: ([today - pd.Timedelta(minutes=5), today], [1.0, 3.0])))
    assert asyncio.run(services.get_crypto_prices_at(["eth"], now_utc(), "CAD")) == {"eth": pytest.approx(3.0)}


# ---------------------------------------------------------------------------------------------------------------------
# 6. exchange rates
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def real_rates(monkeypatch):
    """Use the real get_all_conversion_rates with fake rate helpers; `calls` counts api round trips."""
    state = type("Rates", (), {})()
    state.calls = 0
    state.down = False

    async def helper(value):
        state.calls += 1
        if state.down:
            raise RuntimeError("open.er-api is down")
        return value

    monkeypatch.setattr(services, "get_usd_to_cad", lambda: helper(1.5))
    monkeypatch.setattr(services, "get_usd", lambda: helper(0.66))
    monkeypatch.setattr(services, "get_eur", lambda: helper(0.61))
    monkeypatch.setattr(services, "get_all_conversion_rates", REAL_GET_ALL_CONVERSION_RATES)
    monkeypatch.setattr(routes_module, "get_all_conversion_rates", REAL_GET_ALL_CONVERSION_RATES)
    monkeypatch.setattr(services, "_rates_cache", {})
    monkeypatch.setattr(services, "_rates_cache_time", 0)
    monkeypatch.setattr(services, "_rates_retry_at", 0)
    return state


def test_rates_are_cached_for_an_hour(real_rates, monkeypatch):
    asyncio.run(services.get_all_conversion_rates())
    assert real_rates.calls == 3
    monkeypatch.setattr(services, "_rates_cache_time", time.time() - 3500)
    asyncio.run(services.get_all_conversion_rates())
    assert real_rates.calls == 3
    monkeypatch.setattr(services, "_rates_cache_time", time.time() - 3700)
    asyncio.run(services.get_all_conversion_rates())
    assert real_rates.calls == 6


def test_rate_outage_serves_the_last_good_rates(client, user, buy, real_rates, monkeypatch):
    buy(user, "AAPL", 1, 100)
    monkeypatch.setattr(services, "_rates_cache_time", time.time() - 7200)  # expired
    real_rates.down = True
    calls = real_rates.calls

    res = client.get("/dashboard?current_timeperiod=all", headers=user.headers)
    assert res.status_code == 200, res.text
    assert res.json()["value"] == pytest.approx(100 * 1.5)  # the last good USD->CAD rate
    assert client.get("/holdings", headers=user.headers).status_code == 200
    assert real_rates.calls - calls == 3  # tried once, then waits before retrying instead of on every request


def test_rate_outage_with_nothing_cached_is_a_503_not_a_500(client, user, buy, real_rates, monkeypatch):
    buy(user, "AAPL", 1, 100)
    monkeypatch.setattr(services, "_rates_cache", {})  # e.g. a restart during the outage
    real_rates.down = True
    res = client.get("/dashboard?current_timeperiod=all", headers=user.headers)
    assert res.status_code == 503
    assert "Exchange rates" in res.json()["detail"]
    with pytest.raises(HTTPException):
        asyncio.run(services.get_all_conversion_rates())


def test_unknown_listing_currency_is_unavailable_not_usd(market, monkeypatch, caplog):
    market.prices["ODD.QQ"] = 10.0
    market.currencies["ODD.QQ"] = "XYZ"
    monkeypatch.setitem(services._usd_rates_cache, "rates", {"EUR": 0.9})
    monkeypatch.setitem(services._usd_rates_cache, "time", 10 ** 12)  # fresh: no network call

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        prices = asyncio.run(services.get_stock_prices_at(["ODD.QQ"], now_utc(), "CAD"))
    assert prices == {"ODD.QQ": None}
    assert "XYZ" in caplog.text


def test_missing_listing_currency_is_guessed_from_the_ticker(monkeypatch):
    def broken(symbol):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(services, "yf", type("Down", (), {"Ticker": staticmethod(broken)}))
    assert asyncio.run(services.get_ticker_currency("SHOP.TO")) == "CAD"
    assert asyncio.run(services.get_ticker_currency("VOD.L")) == "GBp"
    assert asyncio.run(services.get_ticker_currency("AAPL")) == "USD"
    assert asyncio.run(services.get_ticker_currency("ODD.QQ")) is None
    assert services._symbol_currency_cache == {}  # a guess after a failure isn't remembered


def test_cross_rate_error_payload_keeps_the_old_table(stub_external_services, monkeypatch):
    stub_external_services.services_http.responses["https://open.er-api.com/v6/latest/USD"] = {"result": "error"}
    monkeypatch.setitem(services._usd_rates_cache, "rates", {"EUR": 0.9})
    monkeypatch.setitem(services._usd_rates_cache, "time", 0)  # stale: refreshes, and the refresh fails
    monkeypatch.setitem(services._usd_rates_cache, "retry_at", 0)

    assert asyncio.run(services.get_native_to_cad_factor("EUR")) == pytest.approx(RATES["usd_to_cad"] / 0.9)
    assert services._usd_rates_cache["rates"] == {"EUR": 0.9}


# ---------------------------------------------------------------------------------------------------------------------
# 7. the chart ends on the value card's number
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("days", [1, 7, 30, 365])
def test_chart_last_point_matches_the_value_card(client, user, buy, days):
    buy(user, "btc", 0.1, 40000, asset_type="crypto")
    buy(user, "AAPL", 2, 100)
    buy(user, "SHOP.TO", 3, 40)

    card = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()["value"]
    chart = client.get(f"/portfolio/history?range={days}", headers=user.headers).json()
    assert chart[-1]["value"] == pytest.approx(card)
    assert card == pytest.approx(0.1 * BTC_CAD + 2 * AAPL_CAD + 3 * 50)


def test_portfolio_history_drops_fully_sold_positions(client, user, buy, sell, db):
    t = buy(user, "AAPL", 2, 100)
    db.set_created_at(t["id"], naive(now_utc() - timedelta(days=3)))
    s = sell(user, "AAPL", 2, 120)
    db.set_created_at(s["id"], naive(now_utc() - timedelta(days=2)))

    data = client.get("/portfolio/history?range=7", headers=user.headers).json()
    mid = [p for p in data if now_utc() - timedelta(days=3) + timedelta(hours=2) < datetime.fromisoformat(p["time"])
           < now_utc() - timedelta(days=2) - timedelta(hours=2)]
    assert mid and all(p["value"] == pytest.approx(2 * AAPL_CAD) for p in mid)
    assert data[-1]["value"] == 0


# ---------------------------------------------------------------------------------------------------------------------
# 8. CoinGecko's "5Y" is really one year, and the response says so
# ---------------------------------------------------------------------------------------------------------------------
def test_coingecko_5y_chart_is_labelled_as_one_year(client, user, coingecko):
    coingecko.prices["pepe"] = 0.00004
    body = client.get("/prices/history?symbol=PEPE&type=crypto&range=5Y", headers=user.headers).json()
    assert body["data"]
    assert body["source"] == "CoinGecko"
    assert body["range"] == "5Y"
    assert body["covered_range"] == "1Y"
    assert "last year" in body["note"]
    assert coingecko.calls == [("pepe", "1Y", "CAD")]


def test_coingecko_chart_within_a_year_needs_no_label(client, make_user, coingecko):
    usd_user = make_user(currency="USD")
    coingecko.prices["pepe"] = 0.00004
    body = client.get("/prices/history?symbol=PEPE&type=crypto&range=1M", headers=usd_user.headers).json()
    assert body["source"] == "CoinGecko"
    assert "covered_range" not in body and "note" not in body
    assert body["data"][-1]["price"] == pytest.approx(0.00004 * RATES["usd"])  # CAD -> the user's currency


def test_yahoo_chart_source(client, user):
    body = client.get("/prices/history?symbol=AAPL&type=stock&range=1W", headers=user.headers).json()
    assert body["source"] == "Yahoo Finance" and "covered_range" not in body
