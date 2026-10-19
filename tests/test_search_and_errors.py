"""Asset search routes (TwelveData / CoinGecko are faked) and app-wide error handling."""
import uuid
from collections import deque

import pytest

import backend.routes.assets as routes_module
from conftest import RATES

TWELVE_SEARCH = "https://api.twelvedata.com/symbol_search"
GECKO_SEARCH = "https://api.coingecko.com/api/v3/search"
GECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"


@pytest.fixture(autouse=True)
def fresh_search_state(monkeypatch):
    # conftest already resets the stock cache; the crypto cache and the per-user search counts live here
    monkeypatch.setattr(routes_module, "_crypto_search_cache", {})
    monkeypatch.setattr(routes_module, "_search_times", {})


def stock(symbol, country="United States", kind="Common Stock", name=None):
    return {"symbol": symbol, "country": country, "instrument_type": kind, "instrument_name": name or f"{symbol} Inc"}


RATE_LIMITED = {"code": 429, "status": "error",
                "message": "You have run out of API credits for the current minute. 9 API credits were used, "
                           "with the current limit being 8."}


# ---------------------------------------------------------------------------------------------------------------------
# stock search (matches from TwelveData, prices from Yahoo via the fake market)
# ---------------------------------------------------------------------------------------------------------------------
def test_stock_search_filters_and_converts(client, user, search_http, market):
    search_http.responses[TWELVE_SEARCH] = {"data": [
        stock("AAPL", name="Apple Inc."),
        stock("AAPL", name="Apple Inc. (duplicate)"),  # duplicate listing
        stock("AAPL", country="Germany"),
        stock("AAPB", kind="Warrant"),
        stock("SPY", kind="ETF"),
    ]}
    market.previous_closes["AAPL"] = 98.0  # AAPL is 100 in the fake market
    market.prices["SPY"] = 500.0

    res = client.get("/assets/search/stock?asset=  aapl ", headers=user.headers)
    assert res.status_code == 200
    results = res.json()

    assert [r["symbol"] for r in results] == ["AAPL", "SPY"]
    assert results[0] == {
        "api_id": "AAPL", "symbol": "AAPL", "name": "Apple Inc.", "type": "stock", "image": "",
        "price": pytest.approx(100 * RATES["usd_to_cad"]),
        "change": pytest.approx(2 * RATES["usd_to_cad"]),
        "change_pct": pytest.approx(2 / 98 * 100),
    }
    assert results[1]["change"] == 0 and results[1]["change_pct"] == 0
    [(search_url, params)] = search_http.calls  # prices no longer spend TwelveData credits
    assert search_url == TWELVE_SEARCH
    assert params["symbol"] == "AAPL"  # trimmed and uppercased


def test_stock_search_user_currency(client, make_user, search_http):
    usd_user = make_user(currency="USD")
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("MSFT")]}

    [result] = client.get("/assets/search/stock?asset=msft", headers=usd_user.headers).json()
    assert result["price"] == pytest.approx(200 * RATES["usd_to_cad"] * RATES["usd"])


def test_stock_search_caps_results_at_six(client, user, search_http, market):
    symbols = [f"S{i}" for i in range(10)]
    market.prices.update({s: 1.0 for s in symbols})
    search_http.responses[TWELVE_SEARCH] = {"data": [stock(s) for s in symbols]}

    assert len(client.get("/assets/search/stock?asset=s", headers=user.headers).json()) == 6


def test_stock_search_skips_symbols_without_prices(client, user, search_http, market):
    market.prices["BBB"] = 3.0  # Yahoo knows nothing about AAA
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("AAA"), stock("BBB")]}
    assert [r["symbol"] for r in client.get("/assets/search/stock?asset=a", headers=user.headers).json()] == ["BBB"]


def test_stock_search_no_matches(client, user, search_http, market):
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("XYZ", country="Canada")]}
    assert client.get("/assets/search/stock?asset=xyz", headers=user.headers).json() == []
    assert market.requested == []  # no price lookups when nothing matched


def test_stock_search_blank_query_skips_the_api(client, user, search_http):
    assert client.get("/assets/search/stock?asset=%20%20", headers=user.headers).json() == []
    assert search_http.calls == []


def test_stock_search_rate_limit_is_an_error_not_no_results(client, user, search_http):
    # regression: TwelveData's per-minute limit used to come back as [] and the page said "check the spelling"
    search_http.responses[TWELVE_SEARCH] = RATE_LIMITED
    res = client.get("/assets/search/stock?asset=nvda", headers=user.headers)
    assert res.status_code == 503
    assert "try again in a minute" in res.json()["detail"]


def test_stock_search_other_provider_errors_are_503(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"code": 401, "status": "error", "message": "invalid api key"}
    res = client.get("/assets/search/stock?asset=nvda", headers=user.headers)
    assert res.status_code == 503
    assert "invalid api key" not in res.text  # provider details stay server-side


def test_stock_search_reuses_matches_for_repeat_queries(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("AAPL")]}
    for query in ("aapl", "AAPL ", "aapl"):
        assert [r["symbol"] for r in client.get(f"/assets/search/stock?asset={query}", headers=user.headers).json()]                == ["AAPL"]
    assert len(search_http.calls) == 1  # one TwelveData credit for three searches


def test_stock_search_does_not_cache_errors(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = RATE_LIMITED
    assert client.get("/assets/search/stock?asset=aapl", headers=user.headers).status_code == 503
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("AAPL")]}
    assert client.get("/assets/search/stock?asset=aapl", headers=user.headers).json()[0]["symbol"] == "AAPL"


def test_stock_search_matches_expire(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("AAPL")]}
    client.get("/assets/search/stock?asset=aapl", headers=user.headers)
    routes_module._stock_search_cache["AAPL"] = (-10 ** 6, [{"symbol": "AAPL", "name": ""}])  # cached long ago
    client.get("/assets/search/stock?asset=aapl", headers=user.headers)
    assert len(search_http.calls) == 2


def test_stock_search_503_when_no_prices_at_all(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("ZZZZ")]}  # matched, but Yahoo has nothing
    assert client.get("/assets/search/stock?asset=zzzz", headers=user.headers).status_code == 503


# ---------------------------------------------------------------------------------------------------------------------
# crypto search
# ---------------------------------------------------------------------------------------------------------------------
def coin(symbol, price=10.0, change=1.0, pct=2.0, image="img"):
    return {"symbol": symbol, "current_price": price, "price_change_24h": change,
            "price_change_percentage_24h": pct, "image": image}


def test_crypto_search_dedupes_and_converts(client, make_user, search_http):
    eur_user = make_user(currency="EUR")
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": f"id{i}"} for i in range(8)]}
    search_http.responses[GECKO_MARKETS] = [
        coin("btc", price=50000, change=500, pct=1.0),
        coin("btc", price=1),  # a less popular coin with the same ticker
        coin("eth", price=None),  # missing data is skipped
        coin("sol", price=100),
    ]

    results = client.get("/assets/search/crypto?asset=b", headers=eur_user.headers).json()
    assert [r["symbol"] for r in results] == ["btc", "sol"]
    assert results[0]["price"] == pytest.approx(50000 * RATES["eur"])
    assert results[0]["change"] == pytest.approx(500 * RATES["eur"])
    assert results[0]["change_pct"] == 1.0
    assert results[0]["type"] == "crypto"
    # only the top 6 search results are priced
    assert search_http.calls[1][1]["ids"] == ",".join(f"id{i}" for i in range(6))


def test_crypto_search_no_results(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": []}
    assert client.get("/assets/search/crypto?asset=zzz", headers=user.headers).json() == []


def test_crypto_search_rate_limited_returns_503(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": "bitcoin"}]}
    search_http.responses[GECKO_MARKETS] = {"status": {"error_code": 429, "error_message": "rate limited"}}
    res = client.get("/assets/search/crypto?asset=btc", headers=user.headers)
    assert res.status_code == 503


def test_crypto_search_blank_query_skips_the_api(client, user, search_http):
    assert client.get("/assets/search/crypto?asset=%20", headers=user.headers).json() == []
    assert search_http.calls == []


def test_crypto_search_returns_the_coin_name(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": "bitcoin"}]}
    search_http.responses[GECKO_MARKETS] = [{**coin("btc"), "name": "Bitcoin", "id": "bitcoin"}]
    [result] = client.get("/assets/search/crypto?asset=btc", headers=user.headers).json()
    assert result["name"] == "Bitcoin" and result["coin_id"] == "bitcoin"


def test_crypto_search_missing_image_is_an_empty_string(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": "x"}]}
    search_http.responses[GECKO_MARKETS] = [coin("xyz", image=None)]
    [result] = client.get("/assets/search/crypto?asset=xyz", headers=user.headers).json()
    assert result["image"] == "" and result["name"] == ""


def test_crypto_search_reuses_results_for_repeat_queries(client, user, make_user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": "bitcoin"}]}
    search_http.responses[GECKO_MARKETS] = [coin("btc", price=100)]
    usd_user = make_user(currency="USD")
    for query, who in (("btc", user), ("BTC ", user), ("btc", usd_user)):
        [result] = client.get(f"/assets/search/crypto?asset={query}", headers=who.headers).json()
        # cached in CAD, converted per user
        assert result["price"] == pytest.approx(100 * (RATES["usd"] if who is usd_user else 1))
    assert len(search_http.calls) == 2  # one search + one markets call for three searches


def test_crypto_search_cache_expires(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": "bitcoin"}]}
    search_http.responses[GECKO_MARKETS] = [coin("btc")]
    client.get("/assets/search/crypto?asset=btc", headers=user.headers)
    stored_at, value = routes_module._crypto_search_cache["btc"]
    routes_module._crypto_search_cache["btc"] = (stored_at - routes_module.CRYPTO_SEARCH_TTL - 1, value)
    client.get("/assets/search/crypto?asset=btc", headers=user.headers)
    assert len(search_http.calls) == 4


def test_crypto_search_does_not_cache_errors(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": [{"api_symbol": "bitcoin"}]}
    search_http.responses[GECKO_MARKETS] = {"status": {"error_code": 429}}
    assert client.get("/assets/search/crypto?asset=btc", headers=user.headers).status_code == 503
    search_http.responses[GECKO_MARKETS] = [coin("btc")]
    assert client.get("/assets/search/crypto?asset=btc", headers=user.headers).json()[0]["symbol"] == "btc"


# ---------------------------------------------------------------------------------------------------------------------
# abuse limits: query length, bounded caches, per-user rate limit
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["stock", "crypto"])
def test_search_rejects_long_queries_without_calling_providers(client, user, search_http, kind):
    res = client.get(f"/assets/search/{kind}?asset={'a' * 21}", headers=user.headers)
    assert res.status_code == 422
    assert "20 characters or fewer" in res.json()["detail"]
    assert search_http.calls == []


@pytest.mark.parametrize("kind", ["stock", "crypto"])
def test_search_rejects_huge_queries(client, user, search_http, kind):
    res = client.get(f"/assets/search/{kind}?asset={'a' * 5000}", headers=user.headers)
    assert res.status_code == 422
    assert "aaaa" not in res.text  # the 422 handler never echoes input
    assert search_http.calls == []


def test_search_allows_20_characters_and_surrounding_spaces(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": []}
    assert client.get(f"/assets/search/crypto?asset=%20%20{'a' * 20}%20%20", headers=user.headers).status_code == 200


def test_search_caches_are_bounded_lru(monkeypatch):
    monkeypatch.setattr(routes_module, "SEARCH_CACHE_SIZE", 3)
    cache = {}
    for key in "abc":
        routes_module._cache_put(cache, key, key.upper())
    assert routes_module._cache_get(cache, "a", 60) == "A"  # "a" is now the most recently used
    routes_module._cache_put(cache, "d", "D")
    assert list(cache) == ["c", "a", "d"]  # "b" was the least recently used
    assert routes_module._cache_get(cache, "b", 60) is None


def test_search_cache_entries_expire():
    cache = {"old": (-10 ** 6, "value")}
    assert routes_module._cache_get(cache, "old", 600) is None
    assert cache == {}  # expired entries are removed, not kept around


def test_new_searches_are_rate_limited_per_user(client, user, make_user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": []}
    for i in range(routes_module.SEARCH_RATE_LIMIT):
        assert client.get(f"/assets/search/crypto?asset=q{i}", headers=user.headers).status_code == 200

    res = client.get("/assets/search/crypto?asset=another", headers=user.headers)
    assert res.status_code == 429
    assert "wait a minute" in res.json()["detail"]
    # stock searches count towards the same limit
    assert client.get("/assets/search/stock?asset=new", headers=user.headers).status_code == 429

    # cached queries are still answered, and other users aren't affected
    assert client.get("/assets/search/crypto?asset=q0", headers=user.headers).status_code == 200
    other = make_user()
    assert client.get("/assets/search/crypto?asset=another", headers=other.headers).status_code == 200


def test_rate_limit_window_slides(client, user, search_http):
    search_http.responses[GECKO_SEARCH] = {"coins": []}
    # the limit is used up, but by searches made long ago
    routes_module._search_times[uuid.UUID(user.id)] = deque([-10 ** 6] * routes_module.SEARCH_RATE_LIMIT)
    assert client.get("/assets/search/crypto?asset=fresh", headers=user.headers).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------
# error handling / CORS
# ---------------------------------------------------------------------------------------------------------------------
ORIGIN = "http://localhost:5173"


def test_unexpected_errors_return_json_500_with_cors(client, user, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes_module, "get_holdings_at_time_list", explode)

    res = client.get("/holdings", headers={**user.headers, "Origin": ORIGIN})
    assert res.status_code == 500
    assert res.json() == {"detail": "Something went wrong on our end. Please try again."}
    assert res.headers["access-control-allow-origin"] == ORIGIN


def test_cors_preflight_allows_the_frontend(client):
    res = client.options("/transactions", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization",
    })
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == ORIGIN


def test_cors_rejects_other_origins(client):
    res = client.get("/users", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_unknown_route_is_404(client):
    assert client.get("/definitely-not-a-route").status_code == 404


def test_cors_allows_the_ios_app(client):
    # the Capacitor app loads its pages from capacitor://localhost
    res = client.options("/users", headers={
        "Origin": "capacitor://localhost", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    assert res.headers["access-control-allow-origin"] == "capacitor://localhost"
