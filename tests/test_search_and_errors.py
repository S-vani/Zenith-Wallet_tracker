"""Asset search routes (TwelveData / CoinGecko are faked) and app-wide error handling."""
import pytest

import backend.routes.assets as routes_module
from conftest import RATES

TWELVE_SEARCH = "https://api.twelvedata.com/symbol_search"
TWELVE_QUOTE = "https://api.twelvedata.com/quote"
GECKO_SEARCH = "https://api.coingecko.com/api/v3/search"
GECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"


def stock(symbol, country="United States", kind="Common Stock"):
    return {"symbol": symbol, "country": country, "instrument_type": kind}


def quote(symbol, close, change=1.0, pct=0.5):
    return {"symbol": symbol, "close": str(close), "change": str(change), "percent_change": str(pct)}


# ---------------------------------------------------------------------------------------------------------------------
# stock search
# ---------------------------------------------------------------------------------------------------------------------
def test_stock_search_filters_and_converts(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"data": [
        stock("AAPL"),
        stock("AAPL"),  # duplicate listing
        stock("AAPL", country="Germany"),
        stock("AAPB", kind="Warrant"),
        stock("SPY", kind="ETF"),
    ]}
    search_http.responses[TWELVE_QUOTE] = {"AAPL": quote("AAPL", 100, change=2, pct=2.0),
                                           "SPY": quote("SPY", 500)}

    res = client.get("/assets/search/stock?asset=  aapl ", headers=user.headers)
    assert res.status_code == 200
    results = res.json()

    assert [r["symbol"] for r in results] == ["AAPL", "SPY"]
    assert results[0] == {
        "api_id": "AAPL", "symbol": "AAPL", "type": "stock", "image": "",
        "price": pytest.approx(100 * RATES["usd_to_cad"]),
        "change": pytest.approx(2 * RATES["usd_to_cad"]),
        "change_pct": 2.0,
    }
    search_url, params = search_http.calls[0]
    assert search_url == TWELVE_SEARCH
    assert params["symbol"] == "AAPL"  # trimmed and uppercased
    assert search_http.calls[1][1]["symbol"] == "AAPL,SPY"


def test_stock_search_single_quote_and_user_currency(client, make_user, search_http):
    usd_user = make_user(currency="USD")
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("MSFT")]}
    search_http.responses[TWELVE_QUOTE] = quote("MSFT", 200)  # one symbol -> a bare quote, not a dict of quotes

    [result] = client.get("/assets/search/stock?asset=msft", headers=usd_user.headers).json()
    assert result["price"] == pytest.approx(200 * RATES["usd_to_cad"] * RATES["usd"])


def test_stock_search_caps_results_at_six(client, user, search_http):
    symbols = [f"S{i}" for i in range(10)]
    search_http.responses[TWELVE_SEARCH] = {"data": [stock(s) for s in symbols]}
    search_http.responses[TWELVE_QUOTE] = lambda params: {s: quote(s, 1) for s in params["symbol"].split(",")}

    assert len(client.get("/assets/search/stock?asset=s", headers=user.headers).json()) == 6


def test_stock_search_skips_quotes_with_errors(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("AAA"), stock("BBB")]}
    search_http.responses[TWELVE_QUOTE] = {"AAA": {"code": 404, "message": "not found"}, "BBB": quote("BBB", 3)}
    assert [r["symbol"] for r in client.get("/assets/search/stock?asset=a", headers=user.headers).json()] == ["BBB"]


def test_stock_search_no_matches(client, user, search_http):
    search_http.responses[TWELVE_SEARCH] = {"data": [stock("XYZ", country="Canada")]}
    assert client.get("/assets/search/stock?asset=xyz", headers=user.headers).json() == []
    assert len(search_http.calls) == 1  # no quote request when nothing matched


def test_stock_search_blank_query_skips_the_api(client, user, search_http):
    assert client.get("/assets/search/stock?asset=%20%20", headers=user.headers).json() == []
    assert search_http.calls == []


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
