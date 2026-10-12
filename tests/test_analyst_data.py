"""
Market Analyst: data collection (backend/analyst/data.py) with faked CoinGecko / Yahoo Finance.
"""
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.analyst import data as market_data
from backend.analyst.data import COINGECKO, DataUnavailable

DAY_MS = 86_400_000
T0 = 1_760_000_000_000 // DAY_MS * DAY_MS  # a midnight in Oct 2025, in ms


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def coingecko(monkeypatch):
    """
    Replaces httpx inside backend.analyst.data. Register `routes[url] = payload` or `(status, payload)`; payload may be
    a callable taking the query params. Unknown urls fail the test.
    """
    state = SimpleNamespace(routes={}, calls=[], headers=None)

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            state.headers = kwargs.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, **kwargs):
            state.calls.append((url, dict(params or {})))
            if url not in state.routes:
                raise AssertionError(f"unexpected request to {url}")
            route = state.routes[url]
            status, payload = route if isinstance(route, tuple) else (200, route)
            if isinstance(payload, Exception):
                raise payload
            return FakeResponse(status, payload(params or {}) if callable(payload) else payload)

    monkeypatch.setattr(market_data, "httpx", SimpleNamespace(AsyncClient=AsyncClient, HTTPError=httpx.HTTPError))
    monkeypatch.setattr(market_data, "_btc_cache", {})
    return state


def chart(prices, volumes=None):
    return {"prices": [[T0 + i * DAY_MS, p] for i, p in enumerate(prices)],
            "total_volumes": [[T0 + i * DAY_MS, v] for i, v in enumerate(volumes or [])]}


SOLANA_DETAILS = {
    "name": "Solana",
    "market_cap_rank": 6,
    "market_data": {
        "market_cap": dict(usd=9.0e10, eur=8.0e10, cad=1.2e11),
        "total_volume": dict(usd=4.0e9, eur=3.5e9, cad=5.5e9),
        "ath": dict(usd=290.0, eur=260.0, cad=400.0),
        "ath_change_percentage": dict(usd=-45.0, eur=-44.0, cad=-46.0),
        "circulating_supply": 4.8e8, "total_supply": 5.9e8, "max_supply": None,
        "last_updated": "2025-10-09T12:00:00.000Z",
    },
}


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- resolve_coin_id
def test_resolve_coin_id_picks_the_coin_whose_symbol_matches(coingecko):
    coingecko.routes[f"{COINGECKO}/search"] = {"coins": [
        {"id": "wrapped-solana", "symbol": "WSOL"},
        {"id": "solana", "symbol": "SOL"},
        {"id": "solana-clone", "symbol": "sol"},
    ]}

    async def go():
        async with market_data.httpx.AsyncClient() as client:
            return await market_data.resolve_coin_id(client, "sol"), await market_data.resolve_coin_id(client, "xyz")

    assert run(go()) == ("solana", None)
    assert coingecko.calls[0] == (f"{COINGECKO}/search", {"query": "sol"})


# --------------------------------------------------------------------------- crypto collection
def test_crypto_is_mapped_into_asset_data_in_the_users_currency(coingecko):
    coingecko.routes[f"{COINGECKO}/coins/solana/market_chart"] = lambda p: chart(
        [100.0, 110.0, 105.0], [1e9, 2e9, 3e9]) if p["vs_currency"] == "eur" else chart([1.0, 1.0, 1.0])
    coingecko.routes[f"{COINGECKO}/coins/solana"] = SOLANA_DETAILS
    coingecko.routes[f"{COINGECKO}/coins/bitcoin/market_chart"] = chart([50000.0, 51000.0, 52000.0])

    data = run(market_data.collect("SOL", "crypto", "EUR", coin_id="solana"))

    assert data.symbol == "SOL" and data.type == "crypto" and data.currency == "EUR"
    assert data.name == "Solana"
    assert data.closes == [100.0, 110.0, 105.0]
    assert data.volumes == [1e9, 2e9, 3e9]
    assert data.times[0] == datetime.fromtimestamp(T0 / 1000, tz=timezone.utc)
    assert all(t.tzinfo is not None for t in data.times)
    assert data.btc_closes == [50000.0, 51000.0, 52000.0]
    assert data.coin["market_cap"] == 8.0e10  # the EUR values, not USD
    assert data.coin["total_volume"] == 3.5e9
    assert data.coin["ath"] == 260.0
    assert data.coin["ath_change_percentage"] == -44.0
    assert data.coin["market_cap_rank"] == 6
    assert "max_supply" not in data.coin  # None values are dropped
    assert data.fundamentals == {}
    assert any(s["name"].startswith("CoinGecko") and s["url"].endswith("/solana") for s in data.sources)
    assert any("news" in lim for lim in data.limitations)

    chart_calls = [p for url, p in coingecko.calls if url.endswith("/market_chart")]
    assert all(p["vs_currency"] == "eur" and p["days"] == 365 for p in chart_calls)
    assert all(url != f"{COINGECKO}/search" for url, _ in coingecko.calls)  # coin_id given, no search needed
    assert coingecko.headers == {"x-cg-demo-api-key": "test-coingecko-key"}


def test_crypto_without_coin_id_is_resolved_by_symbol(coingecko):
    coingecko.routes[f"{COINGECKO}/search"] = {"coins": [{"id": "bitcoin", "symbol": "btc"}]}
    coingecko.routes[f"{COINGECKO}/coins/bitcoin/market_chart"] = chart([60000.0, 61000.0])
    coingecko.routes[f"{COINGECKO}/coins/bitcoin"] = (500, {})
    data = run(market_data.collect("BTC", "crypto", "USD"))
    assert data.closes == [60000.0, 61000.0]
    assert data.btc_closes == []  # bitcoin isn't correlated with itself
    assert any("Market cap and supply" in lim for lim in data.limitations)


def test_unknown_coin_is_a_limitation_not_an_error(coingecko):
    coingecko.routes[f"{COINGECKO}/search"] = {"coins": []}
    data = run(market_data.collect("NOPE", "crypto", "USD"))
    assert data.closes == []
    assert any("No coin called NOPE" in lim for lim in data.limitations)


def test_a_429_from_coingecko_raises_data_unavailable(coingecko):
    coingecko.routes[f"{COINGECKO}/coins/solana/market_chart"] = (429, {"status": {"error_code": 429}})
    with pytest.raises(DataUnavailable, match="rate limiting"):
        run(market_data.collect("SOL", "crypto", "USD", coin_id="solana"))


def test_other_coingecko_failures_raise_data_unavailable(coingecko):
    coingecko.routes[f"{COINGECKO}/coins/solana/market_chart"] = (503, {})
    with pytest.raises(DataUnavailable):
        run(market_data.collect("SOL", "crypto", "USD", coin_id="solana"))
    coingecko.routes[f"{COINGECKO}/coins/solana/market_chart"] = (200, httpx.ConnectError("down"))
    with pytest.raises(DataUnavailable, match="couldn't be reached"):
        run(market_data.collect("SOL", "crypto", "USD", coin_id="solana"))


def test_a_429_on_coin_search_raises_data_unavailable(coingecko):
    coingecko.routes[f"{COINGECKO}/search"] = (429, {"status": {"error_code": 429}})
    with pytest.raises(DataUnavailable):
        run(market_data.collect("BTC", "crypto", "USD"))


def test_btc_failure_only_adds_a_limitation(coingecko):
    coingecko.routes[f"{COINGECKO}/coins/solana/market_chart"] = chart([1.0, 2.0])
    coingecko.routes[f"{COINGECKO}/coins/solana"] = SOLANA_DETAILS
    coingecko.routes[f"{COINGECKO}/coins/bitcoin/market_chart"] = (429, {})
    data = run(market_data.collect("SOL", "crypto", "USD", coin_id="solana"))
    assert data.closes == [1.0, 2.0] and data.btc_closes == []
    assert any("correlation with BTC" in lim for lim in data.limitations)


# --------------------------------------------------------------------------- stocks
class FakeTicker:
    info = {"longName": "NVIDIA Corporation", "currency": "USD", "trailingPE": 50.0, "marketCap": 3e12,
            "currentPrice": 180.0, "irrelevantKey": "dropped", "beta": None}
    calendar = {"Earnings Date": [date(2030, 2, 20), date(2030, 2, 26)], "Earnings Average": 1.2,
                "Ex-Dividend Date": "not a date"}

    def __init__(self, symbol):
        self.symbol = symbol


def test_stock_collection(monkeypatch):
    requested = []

    async def history(symbol, asset_type, range_, currency):
        requested.append((symbol, asset_type, range_, currency))
        return [{"time": "2025-10-08T00:00:00+00:00", "price": 250.0, "volume": 1000},
                {"time": "2025-10-09T00:00:00", "price": 252.5}], symbol

    monkeypatch.setattr(market_data, "get_history_of_prices", history)
    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=FakeTicker))
    data = run(market_data.collect("NVDA", "stock", "CAD"))

    assert requested == [("NVDA", "stock", "1Y", "CAD")]
    assert data.closes == [250.0, 252.5] and data.volumes == [1000, None]
    assert data.times[1] == datetime(2025, 10, 9, tzinfo=timezone.utc)  # naive times are treated as UTC
    assert data.name == "NVIDIA Corporation"
    assert data.fundamentals == {"longName": "NVIDIA Corporation", "currency": "USD", "trailingPE": 50.0,
                                 "marketCap": 3e12, "currentPrice": 180.0}
    assert data.calendar == {"Earnings Date": date(2030, 2, 20), "Earnings Average": 1.2}
    assert data.coin == {} and data.btc_closes == []
    assert [s["name"] for s in data.sources] == ["Yahoo Finance (daily prices & volume)",
                                                 "Yahoo Finance (fundamentals, analyst estimates & calendar)"]


def test_stock_history_failure_raises_data_unavailable(monkeypatch):
    async def broken(*args):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(market_data, "get_history_of_prices", broken)
    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=FakeTicker))
    with pytest.raises(DataUnavailable):
        run(market_data.collect("NVDA", "stock", "USD"))


def test_stock_fundamentals_failure_is_only_a_limitation(monkeypatch):
    async def history(*args):
        return [{"time": "2025-10-09T00:00:00+00:00", "price": 10.0}], "X"

    def broken_ticker(symbol):
        raise RuntimeError("no fundamentals")

    monkeypatch.setattr(market_data, "get_history_of_prices", history)
    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=broken_ticker))
    data = run(market_data.collect("XYZ", "stock", "USD"))
    assert data.closes == [10.0] and data.fundamentals == {}
    assert any("fundamentals couldn't be loaded" in lim for lim in data.limitations)
