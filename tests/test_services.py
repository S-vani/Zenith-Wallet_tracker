"""Unit tests for the helper functions in backend/services/asset_services.py."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import backend.services.asset_services as services
from backend.db.database import async_session_maker
from backend.schemas.assets import CreateTransaction
from conftest import RATES, REAL_GET_ALL_CONVERSION_RATES


# ---------------------------------------------------------------------------------------------------------------------
# get_conversion_factor
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("currency, expected", [
    ("USD", RATES["usd"]),
    ("usd", RATES["usd"]),
    ("EUR", RATES["eur"]),
    ("eur", RATES["eur"]),
    ("CAD", 1.0),
    ("", 1.0),
    (None, 1.0),
    ("GBP", 1.0),
])
def test_conversion_factor(currency, expected):
    assert services.get_conversion_factor(RATES, currency) == expected


# ---------------------------------------------------------------------------------------------------------------------
# get_holdings_helper (weighted average price)
# ---------------------------------------------------------------------------------------------------------------------
def test_holdings_helper_weighted_average():
    # 2 @ 100 then 2 @ 200 -> average 150
    assert services.get_holdings_helper(100, 200, 2, 2) == pytest.approx(150)


def test_holdings_helper_accepts_decimals():
    assert services.get_holdings_helper(10.0, Decimal("20"), 1.0, Decimal("3")) == pytest.approx(17.5)


def test_holdings_helper_first_purchase():
    assert services.get_holdings_helper(0, 42, 0, 5) == pytest.approx(42)


# ---------------------------------------------------------------------------------------------------------------------
# calculate_timespans_for_portfolio_history
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("days, points, label", [
    (1, 289, "1D"),
    (7, 169, "1W"),
    (30, 121, "1M"),
    (31, 121, "1M"),
    (365, 366, "1Y"),
])
def test_timespans_point_counts(days, points, label):
    before = datetime.now(timezone.utc)
    timestamps, t = services.calculate_timespans_for_portfolio_history(days)
    after = datetime.now(timezone.utc)

    assert t == label
    assert len(timestamps) == points
    # the last point is "now", so the chart ends on the same value as the portfolio card
    assert before <= timestamps[-1] <= after
    assert timestamps[-1] - timestamps[0] == pytest.approx(timedelta(days=days), abs=timedelta(milliseconds=1))


def test_timespans_are_evenly_spaced_and_increasing():
    timestamps, _ = services.calculate_timespans_for_portfolio_history(7)
    steps = {round((b - a).total_seconds(), 3) for a, b in zip(timestamps, timestamps[1:])}
    assert steps == {3600.0}
    assert all(ts.tzinfo is not None for ts in timestamps)


# ---------------------------------------------------------------------------------------------------------------------
# turn_list_to_dict
# ---------------------------------------------------------------------------------------------------------------------
def _fake_tx(**overrides):
    values = dict(
        id="tx-1", user_id=uuid.UUID(int=1), action="BUY", profit=None, asset_type="stock", symbol="AAPL",
        api_id="AAPL", price_of_one=Decimal("100"), quantity=Decimal("0.3"),
        created_at=datetime(2024, 1, 2, 3, 4, 5),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_turn_list_to_dict_converts_prices_and_profit():
    [row] = services.turn_list_to_dict([_fake_tx(profit=Decimal("10"))], conversion=0.7)
    assert row["price_of_one"] == pytest.approx(70)
    assert row["profit"] == pytest.approx(7)
    assert row["quantity"] == pytest.approx(0.3)  # quantities are never converted
    assert row["api_ids"] == "AAPL"
    assert row["user_id"] == str(uuid.UUID(int=1))


def test_turn_list_to_dict_handles_missing_profit_and_adds_timezone():
    [row] = services.turn_list_to_dict([_fake_tx()])
    assert row["profit"] == 0.0
    assert row["created_at"] == "2024-01-02T03:04:05+00:00"


def test_turn_list_to_dict_empty():
    assert services.turn_list_to_dict([]) == []


# ---------------------------------------------------------------------------------------------------------------------
# exchange rates (real implementation with a fake http client)
# ---------------------------------------------------------------------------------------------------------------------
def test_exchange_rate_helpers_read_the_api_payload(stub_external_services):
    http = stub_external_services.services_http
    http.responses["https://open.er-api.com/v6/latest/USD"] = {"rates": {"CAD": 1.37}}
    http.responses["https://open.er-api.com/v6/latest/CAD"] = {"rates": {"USD": 0.73, "EUR": 0.67}}

    assert asyncio.run(services.get_usd_to_cad()) == pytest.approx(1.37)
    assert asyncio.run(services.get_usd()) == pytest.approx(0.73)
    assert asyncio.run(services.get_eur()) == pytest.approx(0.67)


def test_conversion_rates_are_cached(monkeypatch):
    calls = []

    async def rate(value):
        calls.append(value)
        return value

    monkeypatch.setattr(services, "get_usd_to_cad", lambda: rate(1.5))
    monkeypatch.setattr(services, "get_usd", lambda: rate(0.66))
    monkeypatch.setattr(services, "get_eur", lambda: rate(0.61))
    monkeypatch.setattr(services, "_rates_cache", {})
    monkeypatch.setattr(services, "_rates_cache_time", 0)

    first = asyncio.run(REAL_GET_ALL_CONVERSION_RATES())
    second = asyncio.run(REAL_GET_ALL_CONVERSION_RATES())

    assert first == {"usd_to_cad": 1.5, "usd": 0.66, "eur": 0.61}
    assert second == first
    assert len(calls) == 3  # second call came from the cache


# ---------------------------------------------------------------------------------------------------------------------
# price lookups (fake yfinance)
# ---------------------------------------------------------------------------------------------------------------------
def test_stock_prices_convert_usd_listings_to_cad_then_user_currency():
    now = datetime.now(timezone.utc)
    cad = asyncio.run(services.get_stock_prices_at(["AAPL", "SHOP.TO"], now, "CAD"))
    usd = asyncio.run(services.get_stock_prices_at(["AAPL"], now, "USD"))

    assert cad["AAPL"] == pytest.approx(100 * RATES["usd_to_cad"])
    assert cad["SHOP.TO"] == pytest.approx(50)  # already CAD
    assert usd["AAPL"] == pytest.approx(100 * RATES["usd_to_cad"] * RATES["usd"])


def test_unknown_stock_is_worth_zero():
    assert asyncio.run(services.get_stock_prices_at(["NOPE"], datetime.now(timezone.utc), "CAD")) == {"NOPE": 0.0}


def test_crypto_prices_keep_the_stored_lowercase_id(market):
    prices = asyncio.run(services.get_crypto_prices_at(["btc"], datetime.now(timezone.utc), "EUR"))
    assert prices == {"btc": pytest.approx(50000 * RATES["eur"])}
    assert "BTC-CAD" in market.requested


def test_price_lookups_with_no_symbols_skip_the_api(market):
    now = datetime.now(timezone.utc)
    assert asyncio.run(services.get_crypto_prices_at([], now, "CAD")) == {}
    assert asyncio.run(services.get_stock_prices_at([], now, "CAD")) == {}
    assert market.requested == []


def test_history_of_prices_crypto_uses_usd_pair_and_converts():
    data, ticker = asyncio.run(services.get_history_of_prices("BTC", "crypto", "1W", "USD"))
    assert ticker == "BTC-USD"
    assert data
    assert data[0]["price"] == pytest.approx(40000 * RATES["usd_to_cad"] * RATES["usd"])
    datetime.fromisoformat(data[0]["time"])  # times must be parseable by the routes


def test_history_of_prices_cad_stock_is_not_converted_to_cad_twice():
    data, ticker = asyncio.run(services.get_history_of_prices("SHOP.TO", "stock", "1M", "CAD"))
    assert ticker == "SHOP.TO"
    assert data[-1]["price"] == pytest.approx(50)


def test_history_of_prices_empty():
    assert asyncio.run(services.get_history_of_prices("NOPE", "stock", "1D", "CAD")) == ([], "NOPE")


# ---------------------------------------------------------------------------------------------------------------------
# database backed helpers
# ---------------------------------------------------------------------------------------------------------------------
async def _call_with_session(fn, *args):
    async with async_session_maker() as session:
        return await fn(session, *args)


def test_current_quantity_uses_exact_decimal_math(run, user, buy, sell):
    buy(user, "ETH", 0.3, 2000, asset_type="crypto")
    sell(user, "ETH", 0.1, 2000, asset_type="crypto")

    qty = run(_call_with_session, services.current_quantity, uuid.UUID(user.id), "ETH")
    assert isinstance(qty, Decimal)
    assert qty == Decimal("0.2")


def test_current_quantity_unknown_symbol_is_zero(run, user):
    assert run(_call_with_session, services.current_quantity, uuid.UUID(user.id), "NOTHING") == 0


def test_holdings_at_time_averages_buys_and_drops_sold_positions(run, user, buy, sell):
    buy(user, "AAPL", 2, 100)
    buy(user, "AAPL", 2, 200)
    buy(user, "MSFT", 1, 300)
    sell(user, "MSFT", 1, 310)

    holdings = run(_call_with_session, services.get_holdings_at_time, uuid.UUID(user.id),
                   datetime.now(timezone.utc), "CAD")

    assert set(holdings) == {"AAPL"}
    assert holdings["AAPL"]["avg_price"] == pytest.approx(150)
    assert holdings["AAPL"]["quantity"] == pytest.approx(4)
    assert holdings["AAPL"]["type"] == "stock"


def test_holdings_at_time_respects_the_timestamp(run, user, buy):
    buy(user, "AAPL", 1, 100)
    an_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    assert run(_call_with_session, services.get_holdings_at_time, uuid.UUID(user.id), an_hour_ago, "CAD") == {}


def test_holdings_at_time_converts_average_price(run, make_user, buy):
    usd_user = make_user(currency="USD")
    buy(usd_user, "AAPL", 1, 70)  # entered in USD, stored as 100 CAD

    holdings = run(_call_with_session, services.get_holdings_at_time, uuid.UUID(usd_user.id),
                   datetime.now(timezone.utc), "USD")
    assert holdings["AAPL"]["avg_price"] == pytest.approx(70)


def test_profit_for_one_transaction_uses_average_cost(run, user, buy):
    buy(user, "AAPL", 2, 100)
    buy(user, "AAPL", 2, 200)
    sale = CreateTransaction(symbol="AAPL", action="SELL", asset_type="stock", price_of_one=180, quantity=1,
                             api_id="AAPL")

    profit = run(_call_with_session, services.calculate_profit_for_one_transaction, uuid.UUID(user.id), sale, "CAD")
    assert profit == pytest.approx(30)


def test_realized_profit_and_cash_flow(run, user, buy, sell):
    buy(user, "AAPL", 2, 100)
    sell(user, "AAPL", 1, 150)  # +50 profit
    uid = uuid.UUID(user.id)

    realized = run(_call_with_session, services.get_total_realized_profit, uid, "USD")
    assert realized == pytest.approx(50 * RATES["usd"])

    now = datetime.now(timezone.utc)
    cash = run(_call_with_session, services.get_cash_flow_between, uid, now - timedelta(days=1), now, "CAD")
    assert cash == pytest.approx(2 * 100 - 1 * 150)
