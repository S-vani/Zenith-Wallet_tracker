"""
Market Analyst: GET /analyst and the caching / rate limiting in backend/analyst/service.py.

Market data collection is replaced by synthetic AssetData (and counted), so these tests are fast and offline.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, update

from backend.analyst import data as market_data
from backend.analyst import gemini, service
from backend.analyst.schema import AnalystReport
from backend.analyst.service import AnalystCache
from backend.db.database import async_session_maker
from tests.analyst_helpers import make_data
from tests.conftest import _set_user_fields, login, register, unique_email

CURRENCY_SCALE = {"USD": 1.0, "CAD": 1.4, "EUR": 0.6}


def base_price(ident: str) -> float:
    """A different (deterministic) price level per asset, so reports for different assets are easy to tell apart."""
    return 50.0 + sum(ord(c) for c in ident.upper()) % 200


# --------------------------------------------------------------------------- fixtures
def _new_user(client, currency):
    email = unique_email("analyst")
    res = register(client, email=email, currency=currency)
    assert res.status_code == 201, res.text
    client.portal.call(partial(_set_user_fields, email, is_verified=True))
    token = login(client, email)
    assert token.status_code == 200, token.text
    return SimpleNamespace(email=email, id=res.json()["id"], currency=currency,
                           headers={"Authorization": f"Bearer {token.json()['access_token']}"})


@pytest.fixture(scope="module")
def users(client):
    """A few users shared by the module (registration is the slow part); their counters are reset per test."""
    return SimpleNamespace(cad=_new_user(client, "CAD"), usd=_new_user(client, "USD"), other=_new_user(client, "CAD"))


async def _wipe_cache():
    async with async_session_maker() as session:
        await session.execute(delete(AnalystCache))
        await session.commit()


async def _age_cache(key, age):
    created = (datetime.now(timezone.utc) - age).replace(tzinfo=None)
    async with async_session_maker() as session:
        res = await session.execute(update(AnalystCache).where(AnalystCache.key == key).values(created_at=created))
        await session.commit()
        assert res.rowcount == 1, f"no cache entry {key}"


@pytest.fixture(autouse=True)
def clean_analyst_state(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client.portal.call(_wipe_cache)
    service._user_generations.clear()
    service._locks.clear()
    yield
    client.portal.call(_wipe_cache)
    service._user_generations.clear()
    service._locks.clear()


@pytest.fixture
def collect(monkeypatch):
    """
    Fake market_data.collect. Records every call; `.n` / `.shape` control the generated history, `.error` makes
    it raise (e.g. DataUnavailable), `.delay` makes it slow.
    """
    state = SimpleNamespace(calls=[], n=365, shape="up", error=None, delay=0.0)

    async def fake(symbol, asset_type, currency, coin_id=None):
        state.calls.append((symbol, asset_type, currency, coin_id))
        if state.delay:
            await asyncio.sleep(state.delay)
        if state.error:
            raise state.error
        start = base_price(coin_id or symbol) * CURRENCY_SCALE[currency]
        return make_data(state.shape, n=state.n, asset_type=asset_type, currency=currency, symbol=symbol,
                         start=start, name=f"{symbol.upper()} test asset")

    monkeypatch.setattr(market_data, "collect", fake)
    return state


@pytest.fixture
def age_cache(client):
    def _age(key, age):
        client.portal.call(_age_cache, key, age)

    return _age


def get(client, user, symbol, type="stock", **params):
    return client.get("/analyst", params={"symbol": symbol, "type": type, **params},
                      headers=user.headers if user else {})


# --------------------------------------------------------------------------- auth and validation
def test_requires_auth(client, collect):
    assert get(client, None, "NVDA").status_code == 401
    assert client.get("/analyst", params={"symbol": "NVDA", "type": "stock"},
                      headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert collect.calls == []


@pytest.mark.parametrize("params", [
    {"symbol": "NVDA", "type": "bond"},
    {"symbol": "NVDA"},
    {"type": "stock"},
    {"symbol": "", "type": "stock"},
    {"symbol": "NV DA", "type": "stock"},
    {"symbol": "<script>", "type": "stock"},
    {"symbol": "NVDA;DROP", "type": "stock"},
    {"symbol": "../etc", "type": "stock"},
    {"symbol": "A" * 21, "type": "stock"},
    {"symbol": "SOL", "type": "crypto", "coin_id": "Solana"},
    {"symbol": "SOL", "type": "crypto", "coin_id": "sol ana"},
    {"symbol": "SOL", "type": "crypto", "coin_id": "sol/../x"},
    {"symbol": "SOL", "type": "crypto", "coin_id": "a" * 81},
    {"symbol": "NVDA", "type": "stock", "refresh": "maybe"},
], ids=lambda p: "-".join(f"{k}={str(v)[:12]}" for k, v in p.items()))
def test_bad_parameters_are_422(client, users, collect, params):
    res = client.get("/analyst", params=params, headers=users.cad.headers)
    assert res.status_code == 422, res.text
    assert collect.calls == []


@pytest.mark.parametrize("symbol", ["BRK-B", "BRK.B", "^GSPC", "EURUSD=X", "A" * 20, "shop.to"])
def test_valid_symbol_formats_are_accepted(client, users, collect, symbol):
    res = get(client, users.cad, symbol)
    assert res.status_code == 200, res.text
    assert res.json()["asset"]["symbol"] == symbol.upper()


# --------------------------------------------------------------------------- happy path and caching
def test_first_call_generates_and_second_is_cached(client, users, collect):
    first = get(client, users.cad, "NVDA")
    assert first.status_code == 200, first.text
    body = first.json()
    AnalystReport.model_validate(body)
    assert body["status"] == "ok"
    assert body["cached"] is False
    assert body["engine"] == "rules"
    assert body["asset"] == {"symbol": "NVDA", "name": "NVDA test asset", "type": "stock", "currency": "CAD",
                             "price": body["asset"]["price"]}
    assert body["sentiment"] == "bullish"
    assert [s["case"] for s in body["scenarios"]] == ["bull", "base", "bear"]
    generated = datetime.fromisoformat(body["generated_at"])
    refresh_at = datetime.fromisoformat(body["refresh_available_at"])
    assert timedelta(minutes=4) < refresh_at - generated < timedelta(minutes=6)

    second = get(client, users.cad, "NVDA")
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert {k: v for k, v in second.json().items() if k != "cached"} == \
           {k: v for k, v in body.items() if k != "cached"}
    assert collect.calls == [("NVDA", "stock", "CAD", None)]


def test_cache_is_shared_between_users_of_the_same_currency(client, users, collect):
    get(client, users.cad, "NVDA")
    res = get(client, users.other, "NVDA")
    assert res.json()["cached"] is True
    assert len(collect.calls) == 1


def test_symbol_case_and_whitespace_share_one_cache_entry(client, users, collect):
    assert get(client, users.cad, "nvda").json()["cached"] is False
    assert get(client, users.cad, "NVDA").json()["cached"] is True
    assert len(collect.calls) == 1


def test_refresh_within_cooldown_is_429(client, users, collect):
    get(client, users.cad, "NVDA")
    res = get(client, users.cad, "NVDA", refresh="true")
    assert res.status_code == 429
    assert "refresh it again in 5 min" in res.json()["detail"]
    retry = int(res.headers["Retry-After"])
    assert 0 < retry <= 300
    assert len(collect.calls) == 1
    # a normal (non refresh) request still gets the cached report
    assert get(client, users.cad, "NVDA").json()["cached"] is True


def test_refresh_after_cooldown_regenerates(client, users, collect, age_cache):
    get(client, users.cad, "NVDA")
    age_cache("stock:NVDA:CAD", timedelta(minutes=6))
    res = get(client, users.cad, "NVDA", refresh="true")
    assert res.status_code == 200, res.text
    assert res.json()["cached"] is False
    assert len(collect.calls) == 2
    # and the new report restarts the cooldown
    assert get(client, users.cad, "NVDA", refresh="true").status_code == 429


def test_refresh_cooldown_constant_is_respected(client, users, collect, monkeypatch):
    monkeypatch.setattr(service, "REFRESH_COOLDOWN", timedelta(seconds=0))
    get(client, users.cad, "NVDA")
    res = get(client, users.cad, "NVDA", refresh="true")
    assert res.status_code == 200 and res.json()["cached"] is False
    assert len(collect.calls) == 2


def test_refresh_without_a_cached_report_just_generates(client, users, collect):
    res = get(client, users.cad, "NVDA", refresh="true")
    assert res.status_code == 200 and res.json()["cached"] is False


@pytest.mark.parametrize("asset_type,key,fresh_age,expired_age", [
    ("stock", "stock:NVDA:CAD", timedelta(minutes=50), timedelta(minutes=61)),
    ("crypto", "crypto:solana:CAD", timedelta(minutes=20), timedelta(minutes=31)),
])
def test_ttl_expiry_regenerates(client, users, collect, age_cache, asset_type, key, fresh_age, expired_age):
    params = {"coin_id": "solana"} if asset_type == "crypto" else {}
    symbol = "SOL" if asset_type == "crypto" else "NVDA"
    get(client, users.cad, symbol, asset_type, **params)

    age_cache(key, fresh_age)
    assert get(client, users.cad, symbol, asset_type, **params).json()["cached"] is True
    assert len(collect.calls) == 1

    age_cache(key, expired_age)
    res = get(client, users.cad, symbol, asset_type, **params)
    assert res.json()["cached"] is False
    assert len(collect.calls) == 2


def test_broken_cache_entry_is_regenerated(client, users, collect):
    get(client, users.cad, "NVDA")

    async def corrupt():
        async with async_session_maker() as session:
            await session.execute(update(AnalystCache).values(payload='{"status": "nonsense"}'))
            await session.commit()

    client.portal.call(corrupt)
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 200 and res.json()["cached"] is False
    assert len(collect.calls) == 2


# --------------------------------------------------------------------------- cache keys
def test_cache_key_separates_currency(client, users, collect):
    cad = get(client, users.cad, "NVDA").json()
    usd = get(client, users.usd, "NVDA").json()
    assert cad["asset"]["currency"] == "CAD" and usd["asset"]["currency"] == "USD"
    assert cad["cached"] is False and usd["cached"] is False
    assert cad["asset"]["price"] == pytest.approx(usd["asset"]["price"] * 1.4)
    assert cad["metrics"][0]["value"].startswith("CA$") and usd["metrics"][0]["value"].startswith("$")
    assert [c[2] for c in collect.calls] == ["CAD", "USD"]
    # each one is then cached separately
    assert get(client, users.cad, "NVDA").json()["asset"]["currency"] == "CAD"
    assert get(client, users.usd, "NVDA").json()["asset"]["currency"] == "USD"
    assert len(collect.calls) == 2


def test_unsupported_user_currency_falls_back_to_cad(client, users, collect):
    client.portal.call(partial(_set_user_fields, users.other.email, currency="GBP"))
    try:
        res = get(client, users.other, "NVDA")
        assert res.status_code == 200
        assert res.json()["asset"]["currency"] == "CAD"
        assert collect.calls[0][2] == "CAD"
    finally:
        client.portal.call(partial(_set_user_fields, users.other.email, currency="CAD"))


def test_cache_key_separates_assets(client, users, collect):
    nvda = get(client, users.cad, "NVDA").json()
    aapl = get(client, users.cad, "AAPL").json()
    assert nvda["asset"]["symbol"] == "NVDA" and aapl["asset"]["symbol"] == "AAPL"
    assert nvda["asset"]["price"] != aapl["asset"]["price"]
    assert aapl["cached"] is False
    assert len(collect.calls) == 2


def test_crypto_is_cached_by_coin_id(client, users, collect):
    a = get(client, users.cad, "SOL", "crypto", coin_id="solana").json()
    b = get(client, users.cad, "SOL", "crypto", coin_id="solana-wormhole").json()
    assert a["cached"] is False and b["cached"] is False
    assert a["asset"]["price"] != b["asset"]["price"]
    # same coin id (any symbol casing) is the same report
    assert get(client, users.cad, "sol", "crypto", coin_id="solana").json()["cached"] is True
    assert [c[3] for c in collect.calls] == ["solana", "solana-wormhole"]
    assert collect.calls[0][1] == "crypto"


def test_stock_and_crypto_with_the_same_symbol_are_separate(client, users, collect):
    stock = get(client, users.cad, "COIN").json()
    crypto = get(client, users.cad, "COIN", "crypto").json()
    assert stock["asset"]["type"] == "stock" and crypto["asset"]["type"] == "crypto"
    assert crypto["cached"] is False
    assert len(collect.calls) == 2


def test_switching_assets_always_returns_the_requested_asset(client, users, collect):
    for symbol in ["NVDA", "AAPL", "MSFT", "NVDA", "AAPL", "TSLA", "NVDA"]:
        body = get(client, users.cad, symbol).json()
        assert body["asset"]["symbol"] == symbol
        assert body["asset"]["price"] == pytest.approx(make_data("up", start=base_price(symbol) * 1.4).closes[-1])
    assert [c[0] for c in collect.calls] == ["NVDA", "AAPL", "MSFT", "TSLA"]


def test_concurrent_requests_generate_once_and_never_mix_assets(client, users, collect, run):
    collect.delay = 0.05

    async def burst():
        async def one(symbol):
            async with async_session_maker() as session:
                return await service.get_report(session, users.cad.id, symbol, "stock", "CAD")

        return await asyncio.gather(*(one(s) for s in ["NVDA", "AAPL", "NVDA", "AAPL", "NVDA"]))

    reports = run(burst)
    assert [r.asset.symbol for r in reports] == ["NVDA", "AAPL", "NVDA", "AAPL", "NVDA"]
    assert sorted(c[0] for c in collect.calls) == ["AAPL", "NVDA"]  # one generation per asset (per-key lock)
    assert sum(not r.cached for r in reports) == 2


# --------------------------------------------------------------------------- data problems
def test_data_unavailable_without_cache_is_503(client, users, collect):
    collect.error = market_data.DataUnavailable("Price history is unavailable right now.")
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 503
    assert res.json() == {"detail": "Price history is unavailable right now."}


def test_data_unavailable_with_an_expired_cache_serves_the_old_report(client, users, collect, age_cache):
    first = get(client, users.cad, "NVDA").json()
    age_cache("stock:NVDA:CAD", timedelta(hours=3))
    collect.error = market_data.DataUnavailable("Price history is unavailable right now.")
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 200
    assert res.json()["cached"] is True
    assert res.json()["generated_at"] == first["generated_at"]
    assert len(collect.calls) == 2  # it did try to refresh


def test_data_unavailable_on_refresh_serves_the_old_report(client, users, collect, age_cache):
    get(client, users.cad, "NVDA")
    age_cache("stock:NVDA:CAD", timedelta(minutes=10))
    collect.error = market_data.DataUnavailable("down")
    res = get(client, users.cad, "NVDA", refresh="true")
    assert res.status_code == 200 and res.json()["cached"] is True


def test_slow_data_is_a_503_with_a_readable_message(client, users, collect, monkeypatch):
    monkeypatch.setattr(service, "COLLECT_TIMEOUT_SECONDS", 0.05)
    collect.delay = 2
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 503
    assert res.json()["detail"] == "Market data took too long to load. Please try again."


def test_insufficient_data_is_200(client, users, collect):
    collect.n = 12
    res = get(client, users.cad, "NEWIPO")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "insufficient_data"
    assert body["sentiment"] is None and body["scenarios"] == []
    assert "12 daily data points" in body["summary"]


def test_unexpected_errors_are_a_clean_500(client, users, collect):
    collect.error = RuntimeError("boom with secret details")
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 500
    assert "boom" not in res.text


# --------------------------------------------------------------------------- per-user hourly limit
def test_hourly_generation_limit_per_user(client, users, collect, monkeypatch):
    monkeypatch.setattr(service, "GENERATIONS_PER_HOUR", 3)
    for symbol in ("AAA", "BBB", "CCC"):
        assert get(client, users.cad, symbol).status_code == 200
    res = get(client, users.cad, "DDD")
    assert res.status_code == 429
    assert "hourly limit" in res.json()["detail"]
    assert len(collect.calls) == 3

    # cached reports are still free
    assert get(client, users.cad, "AAA").json()["cached"] is True
    # another user is unaffected (and the asset the first user was refused is generated for them)
    res = get(client, users.other, "DDD")
    assert res.status_code == 200 and res.json()["cached"] is False
    # ...after which the first user gets it from the cache
    assert get(client, users.cad, "DDD").json()["cached"] is True


def test_hourly_limit_serves_an_expired_report_instead_of_failing(client, users, collect, monkeypatch, age_cache):
    monkeypatch.setattr(service, "GENERATIONS_PER_HOUR", 1)
    get(client, users.cad, "NVDA")
    age_cache("stock:NVDA:CAD", timedelta(hours=2))
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 200 and res.json()["cached"] is True
    assert len(collect.calls) == 1


def test_hourly_limit_window_slides(client, users, collect, monkeypatch):
    monkeypatch.setattr(service, "GENERATIONS_PER_HOUR", 1)
    get(client, users.cad, "AAA")
    assert get(client, users.cad, "BBB").status_code == 429
    window = service._user_generations[str(users.cad.id)]
    window[0] -= 3601  # the first generation is now more than an hour old
    assert get(client, users.cad, "BBB").status_code == 200


# --------------------------------------------------------------------------- secrets and gemini
def _echo_gemini(monkeypatch, seen):
    """Fake Gemini that returns the draft it was sent (a valid, faithful 'rewrite')."""

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None, **kwargs):
            seen.append(headers)
            prompt = json["contents"][0]["parts"][0]["text"]
            draft = _json.loads(prompt.split("DRAFT (JSON):\n", 1)[1])
            draft["summary"] = "Rewritten. " + draft["summary"]
            text = _json.dumps(draft)
            return SimpleNamespace(status_code=200,
                                   json=lambda: {"candidates": [{"content": {"parts": [{"text": text}]}}]})

    monkeypatch.setattr(gemini, "httpx", SimpleNamespace(AsyncClient=AsyncClient, HTTPError=httpx.HTTPError))


_json = json


def test_response_never_contains_api_keys(client, users, collect, monkeypatch):
    secrets = {"GEMINI_API_KEY": "gm-secret-0f9e8d7c6b", "API_KEY_COINEGECKO": "cg-secret-1a2b3c4d5e",
               "API_KEY": "td-secret-9z8y7x6w"}
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    seen = []
    _echo_gemini(monkeypatch, seen)

    texts = [get(client, users.cad, "NVDA").text, get(client, users.cad, "SOL", "crypto", coin_id="solana").text,
             get(client, users.cad, "NVDA").text]
    assert seen == [{"x-goog-api-key": secrets["GEMINI_API_KEY"]}] * 2  # the key was used, only in the header
    for text in texts:
        body = json.loads(text)
        assert body["engine"] == "gemini"
        assert body["summary"].startswith("Rewritten. ")
        for value in secrets.values():
            assert value not in text
        assert "test-coingecko-key" not in text and "test-twelvedata-key" not in text


def test_gemini_failure_still_returns_the_rules_report(client, users, collect, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gm-secret-0f9e8d7c6b")

    class Failing:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("gemini is down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(gemini, "httpx", SimpleNamespace(AsyncClient=Failing, HTTPError=httpx.HTTPError))
    res = get(client, users.cad, "NVDA")
    assert res.status_code == 200
    assert res.json()["engine"] == "rules"
