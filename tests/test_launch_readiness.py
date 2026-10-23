"""
Launch-readiness hardening: chart rate limit, unknown-coin cache, Yahoo concurrency / shared fetches, one FX refresh at
a time, no DB connection held while pricing, forced iOS update (426), /health, the SECRET check, the per-user trade
cap, the provider-neutral email sender and password hashing off the event loop.
"""
import asyncio
from collections import deque
import logging
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest

import backend.analyst.data as market_data
import backend.analyst.service as analyst_service
import backend.db_models.assets as models_module
import backend.main as main_module
import backend.routes.assets as routes_module
import backend.services.asset_services as services
from backend.db.database import engine
from conftest import REAL_GET_ALL_CONVERSION_RATES


# =====================================================================================================================
# 1. /prices/history rate limit and the unknown-coin cache
# =====================================================================================================================
def test_price_history_is_rate_limited_per_user(client, make_user, monkeypatch):
    monkeypatch.setattr(routes_module, "PRICE_HISTORY_RATE_LIMIT", 3)
    monkeypatch.setattr(routes_module, "_price_history_times", {})
    first, second = make_user(), make_user()
    params = {"symbol": "AAPL", "type": "stock", "range": "1M"}

    for _ in range(3):
        assert client.get("/prices/history", params=params, headers=first.headers).status_code == 200
    res = client.get("/prices/history", params=params, headers=first.headers)
    assert res.status_code == 429
    assert "charts very quickly" in res.json()["detail"]
    assert 1 <= int(res.headers["retry-after"]) <= 61

    # another user has their own allowance
    assert client.get("/prices/history", params=params, headers=second.headers).status_code == 200


def test_search_429_also_says_when_to_retry(client, user, monkeypatch):
    monkeypatch.setattr(routes_module, "_search_times", {uuid.UUID(user.id): deque(
        [time.monotonic()] * routes_module.SEARCH_RATE_LIMIT)})
    res = client.get("/assets/search/crypto", params={"asset": "zzzq"}, headers=user.headers)
    assert res.status_code == 429 and "retry-after" in res.headers


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def gecko(monkeypatch):
    """Fake httpx for backend.analyst.data: `routes[url] = (status, payload)`; calls are recorded."""
    state = SimpleNamespace(routes={}, calls=[])

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, **kwargs):
            state.calls.append(url)
            status, payload = state.routes[url]
            return _Resp(status, payload)

    monkeypatch.setattr(market_data, "httpx", SimpleNamespace(AsyncClient=AsyncClient, HTTPError=httpx.HTTPError))
    monkeypatch.setattr(market_data, "_unknown_coins", {})
    return state


def test_unknown_coin_is_remembered_for_a_day(gecko, monkeypatch):
    gecko.routes[f"{market_data.COINGECKO}/search"] = (200, {"coins": []})

    for _ in range(3):
        assert asyncio.run(market_data.coingecko_chart("MADEUP", "1M", "CAD")) == []
    assert len(gecko.calls) == 1  # only the first lookup reached CoinGecko

    # a day later it's asked again (it may have been listed since)
    market_data._unknown_coins["symbol:madeup"] -= market_data.UNKNOWN_COIN_SECONDS
    asyncio.run(market_data.coingecko_chart("madeup", "1M", "CAD"))
    assert len(gecko.calls) == 2


def test_unknown_coin_id_is_remembered_but_a_rate_limit_is_not(gecko):
    chart = f"{market_data.COINGECKO}/coins/no-such-coin/market_chart"
    gecko.routes[chart] = (404, {"error": "coin not found"})
    asyncio.run(market_data.coingecko_chart("x", "1M", "CAD", coin_id="no-such-coin"))
    asyncio.run(market_data.coingecko_chart("x", "1M", "CAD", coin_id="no-such-coin"))
    assert gecko.calls == [chart]

    busy = f"{market_data.COINGECKO}/coins/busy-coin/market_chart"
    gecko.routes[busy] = (429, {})
    asyncio.run(market_data.coingecko_chart("x", "1M", "CAD", coin_id="busy-coin"))
    asyncio.run(market_data.coingecko_chart("x", "1M", "CAD", coin_id="busy-coin"))
    assert gecko.calls.count(busy) == 2


def test_unknown_coin_cache_is_bounded(gecko, monkeypatch):
    monkeypatch.setattr(market_data, "UNKNOWN_COIN_CACHE_SIZE", 3)
    for i in range(5):
        market_data._remember_unknown_coin(f"symbol:c{i}")
    assert list(market_data._unknown_coins) == ["symbol:c2", "symbol:c3", "symbol:c4"]


# =====================================================================================================================
# 2. Yahoo protection
# =====================================================================================================================
def test_yahoo_calls_are_limited_and_run_on_their_own_threads():
    lock = threading.Lock()
    state = SimpleNamespace(active=0, peak=0, threads=set())

    def blocking_call():
        with lock:
            state.active += 1
            state.peak = max(state.peak, state.active)
        state.threads.add(threading.current_thread().name)
        time.sleep(0.05)
        with lock:
            state.active -= 1
        return "done"

    async def go():
        return await asyncio.gather(*[services.run_yahoo(blocking_call) for _ in range(15)])

    assert asyncio.run(go()) == ["done"] * 15
    assert 1 < state.peak <= services.YAHOO_CONCURRENCY
    assert all(name.startswith("yahoo") for name in state.threads)


def _series(price):
    return services.PriceSeries(labels=["x"], times=[services.datetime.now(services.timezone.utc)],
                                known=[services.datetime.now(services.timezone.utc)], closes=[price],
                                volumes=[None])


def test_concurrent_cache_misses_share_one_fetch():
    calls = []

    async def fetch():
        calls.append(1)
        await asyncio.sleep(0.05)
        return _series(10.0)

    async def go():
        return await asyncio.gather(*[services._cached_series(("test", "ONE"), 60, fetch) for _ in range(10)])

    results = asyncio.run(go())
    assert len(calls) == 1
    assert all(r is results[0] for r in results)
    assert not services._series_inflight  # nothing left behind


def test_a_shared_failed_fetch_fails_every_waiter_once():
    calls = []

    async def fetch():
        calls.append(1)
        await asyncio.sleep(0.02)
        raise RuntimeError("yahoo down")

    async def go():
        return await asyncio.gather(*[services._cached_series(("test", "BAD"), 60, fetch) for _ in range(5)],
                                    return_exceptions=True)

    results = asyncio.run(go())
    assert len(calls) == 1
    assert all(isinstance(r, RuntimeError) for r in results)


def test_one_waiter_giving_up_doesnt_cancel_the_fetch_for_others():
    async def fetch():
        await asyncio.sleep(0.05)
        return _series(5.0)

    async def go():
        impatient = asyncio.ensure_future(asyncio.wait_for(services._cached_series(("test", "S"), 60, fetch), 0.01))
        patient = asyncio.ensure_future(services._cached_series(("test", "S"), 60, fetch))
        with pytest.raises(asyncio.TimeoutError):
            await impatient
        return await patient

    assert asyncio.run(go()).closes == [5.0]


def test_listing_currency_cache_is_a_bounded_lru(monkeypatch):
    monkeypatch.setattr(services, "SYMBOL_CURRENCY_CACHE_SIZE", 3)

    async def go():
        for symbol in ("A", "B", "C", "A", "D"):
            await services.get_ticker_currency(symbol)

    asyncio.run(go())
    assert list(services._symbol_currency_cache) == ["C", "A", "D"]


def test_expired_exchange_rates_are_refreshed_by_one_request(monkeypatch):
    calls = []

    def slow(name, value):
        async def fetch():
            calls.append(name)
            await asyncio.sleep(0.02)
            return value
        return fetch

    monkeypatch.setattr(services, "get_usd_to_cad", slow("usd_to_cad", 1.4))
    monkeypatch.setattr(services, "get_usd", slow("usd", 0.7))
    monkeypatch.setattr(services, "get_eur", slow("eur", 0.6))
    monkeypatch.setattr(services, "_rates_cache", {})
    monkeypatch.setattr(services, "_rates_cache_time", 0)
    monkeypatch.setattr(services, "_rates_retry_at", 0)
    assert services.has_cached_rates() is False

    async def go():
        return await asyncio.gather(*[REAL_GET_ALL_CONVERSION_RATES() for _ in range(8)])

    results = asyncio.run(go())
    assert sorted(calls) == ["eur", "usd", "usd_to_cad"]
    assert all(r == {"usd_to_cad": 1.4, "usd": 0.7, "eur": 0.6} for r in results)
    assert services.has_cached_rates() is True


def test_expired_cross_rates_are_refreshed_by_one_request(monkeypatch):
    calls = []

    async def fetch(now):
        calls.append(now)
        await asyncio.sleep(0.02)
        services._usd_rates_cache.update(rates={"GBP": 0.8}, time=now)

    monkeypatch.setattr(services, "_fetch_usd_cross_rates", fetch)
    monkeypatch.setattr(services, "_usd_rates_cache", {"time": 0.0, "rates": {}, "retry_at": 0.0})

    async def go():
        await asyncio.gather(*[services._refresh_usd_cross_rates() for _ in range(6)])

    asyncio.run(go())
    assert len(calls) == 1


# =====================================================================================================================
# 3. No database connection is held while waiting on price sources
# =====================================================================================================================
def _checked_out():
    return engine.sync_engine.pool.checkedout()


def test_pricing_happens_without_a_database_connection(client, user, buy, monkeypatch):
    buy(user, "AAPL", 2, 100)
    seen = []
    real_prices_at, real_asset_series = services.get_prices_at, services._asset_series

    async def prices_at(*args, **kwargs):
        seen.append(("prices", _checked_out()))
        return await real_prices_at(*args, **kwargs)

    async def asset_series(*args, **kwargs):
        seen.append(("series", _checked_out()))
        return await real_asset_series(*args, **kwargs)

    monkeypatch.setattr(services, "get_prices_at", prices_at)
    monkeypatch.setattr(services, "_asset_series", asset_series)

    assert client.get("/holdings", headers=user.headers).status_code == 200
    for period in ("day", "all"):
        res = client.get("/dashboard", params={"current_timeperiod": period}, headers=user.headers)
        assert res.status_code == 200 and res.json()["value"] > 0
    assert client.get("/portfolio/history", params={"range": 7}, headers=user.headers).status_code == 200
    assert client.get("/prices/history", params={"symbol": "AAPL", "type": "stock", "range": "1M"},
                      headers=user.headers).status_code == 200

    assert seen and {count for _, count in seen} == {0}, seen


def test_analyst_waits_on_market_data_without_a_database_connection(client, user, monkeypatch):
    seen = []

    async def collect(symbol, asset_type, currency, coin_id=None):
        seen.append(_checked_out())
        raise market_data.DataUnavailable("No data in this test.")

    monkeypatch.setattr(market_data, "collect", collect)
    res = client.get("/analyst", params={"symbol": f"Q{uuid.uuid4().hex[:6]}", "type": "stock"},
                     headers=user.headers)
    assert res.status_code == 503
    assert seen == [0]


# =====================================================================================================================
# 4. Forced update for the iOS app
# =====================================================================================================================
@pytest.mark.parametrize("version, expected", [
    ("1.1", 426), ("1.1.9", 426), ("0.9", 426), ("abc", 426), ("", 426), ("1.2.x", 426),
    ("1.2", 200), ("1.2.0", 200), ("1.2.1", 200), ("1.10", 200), ("2", 200),
])
def test_outdated_app_versions_get_426(client, monkeypatch, version, expected):
    monkeypatch.setenv("MIN_IOS_APP_VERSION", "1.2")
    res = client.get("/users", headers={"X-Zenith-App-Version": version})
    assert res.status_code == expected
    if expected == 426:
        assert res.json() == {"detail": "This version of Zenith is out of date. Please update it from the App Store.",
                              "code": "UPDATE_REQUIRED"}


def test_requests_without_the_header_are_never_blocked(client, monkeypatch):
    monkeypatch.setenv("MIN_IOS_APP_VERSION", "99.0")
    assert client.get("/users").status_code == 200


def test_no_minimum_means_no_check(client, monkeypatch):
    monkeypatch.delenv("MIN_IOS_APP_VERSION", raising=False)
    assert client.get("/users", headers={"X-Zenith-App-Version": "0.0.1"}).status_code == 200
    monkeypatch.setenv("MIN_IOS_APP_VERSION", "not-a-version")  # misconfigured: ignored (and logged)
    assert client.get("/users", headers={"X-Zenith-App-Version": "0.0.1"}).status_code == 200


def test_426_reaches_the_app_through_cors_and_preflights_pass(client, monkeypatch):
    monkeypatch.setenv("MIN_IOS_APP_VERSION", "2.0")
    origin = "capacitor://localhost"

    preflight = client.options("/users", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "x-zenith-app-version, x-zenith-client, authorization"})
    assert preflight.status_code == 200
    allowed = preflight.headers["access-control-allow-headers"].lower()
    assert "x-zenith-app-version" in allowed and "x-zenith-client" in allowed

    res = client.get("/users", headers={"Origin": origin, "X-Zenith-App-Version": "1.0"})
    assert res.status_code == 426
    assert res.headers["access-control-allow-origin"] == origin
    assert res.headers["x-content-type-options"] == "nosniff"


# =====================================================================================================================
# 5. /health
# =====================================================================================================================
def test_health_reports_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok" and body["db"] is True and isinstance(body["fx_cached"], bool)


def test_health_is_503_when_the_database_is_down(client, monkeypatch):
    class Broken:
        async def __aenter__(self):
            raise ConnectionError("database is gone")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(main_module, "engine", SimpleNamespace(connect=lambda: Broken()))
    res = client.get("/health")
    assert res.status_code == 503
    assert res.json()["status"] == "error" and res.json()["db"] is False


# =====================================================================================================================
# 6. SECRET must be set and long enough
# =====================================================================================================================
@pytest.mark.parametrize("secret", [None, "", "short", "x" * 31])
def test_server_refuses_to_start_with_a_weak_secret(monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("SECRET", raising=False)
    else:
        monkeypatch.setenv("SECRET", secret)
    with pytest.raises(RuntimeError, match="SECRET"):
        main_module.check_secret()


def test_a_long_secret_is_accepted(monkeypatch):
    monkeypatch.setenv("SECRET", "x" * 32)
    main_module.check_secret()


# =====================================================================================================================
# 7. Per-user cap on transactions
# =====================================================================================================================
def test_transactions_per_user_are_capped(client, make_user, buy, monkeypatch):
    monkeypatch.setattr(routes_module, "MAX_TRANSACTIONS_PER_USER", 2)
    owner, other = make_user(), make_user()
    buy(owner, "AAPL", 1, 100)
    buy(owner, "AAPL", 1, 100)
    res = client.post("/transactions", headers=owner.headers, json={
        "symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
        "api_id": "AAPL"})
    assert res.status_code == 422
    assert "up to 2 trades" in res.json()["detail"]
    buy(other, "AAPL", 1, 100)  # the cap is per user


# =====================================================================================================================
# Trades at the same moment replay buy-first (the old random-id order made "buy then sell" flaky)
# =====================================================================================================================
def test_a_buy_and_sell_at_the_same_moment_replay_buy_first(client, user, buy):
    at = "2025-03-01T12:00:00Z"
    for i in range(6):  # with a random order this would pass 1 time in 64
        symbol = f"T{i}"
        for action in ("BUY", "SELL"):
            res = client.post("/transactions", headers=user.headers, json={
                "symbol": symbol, "action": action, "asset_type": "stock", "price_of_one": 10, "quantity": 1,
                "api_id": symbol, "created_at": at})
            assert res.status_code == 200, res.text


# =====================================================================================================================
# 8. Provider-neutral email
# =====================================================================================================================
class RecordingSMTP:
    instances = []
    fail_times = 0

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        RecordingSMTP.instances.append(self)
        if RecordingSMTP.fail_times > 0:
            RecordingSMTP.fail_times -= 1
            raise ConnectionError("smtp down for someone@example.com")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def sendmail(self, sender, to, message):
        self.calls.append(("sendmail", sender, to, message))


class RecordingSMTPSSL(RecordingSMTP):
    pass


@pytest.fixture
def smtp(monkeypatch):
    RecordingSMTP.instances = []
    RecordingSMTP.fail_times = 0
    monkeypatch.setattr(models_module.smtplib, "SMTP", RecordingSMTP)
    monkeypatch.setattr(models_module.smtplib, "SMTP_SSL", RecordingSMTPSSL)
    monkeypatch.setattr(models_module, "EMAIL_RETRY_DELAYS", (0, 0))
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_FROM", "GMAIL_USER", "GMAIL_PASS"):
        monkeypatch.delenv(name, raising=False)
    return RecordingSMTP


async def _send_and_wait(to="person@example.com"):
    await models_module.send_notice_email(to, "Subject", "Body")
    await asyncio.gather(*list(models_module._pending_emails))


def _sent(instance):
    return [c for c in instance.calls if isinstance(c, tuple) and c[0] == "sendmail"]


def test_smtp_host_settings_send_through_that_provider(smtp, monkeypatch, run):
    monkeypatch.setenv("SMTP_HOST", "smtp.provider.test")
    monkeypatch.setenv("SMTP_USER", "apikey")
    monkeypatch.setenv("SMTP_PASS", "secret-pass")
    monkeypatch.setenv("EMAIL_FROM", "Zenith <noreply@zenithwalletracker.ca>")
    run(_send_and_wait)

    [server] = smtp.instances
    assert (server.host, server.port) == ("smtp.provider.test", 587)
    assert server.calls[0] == "starttls" and server.calls[1] == ("login", "apikey", "secret-pass")
    [(_, envelope, to, message)] = _sent(server)
    assert envelope == "noreply@zenithwalletracker.ca" and to == "person@example.com"
    assert "From: Zenith <noreply@zenithwalletracker.ca>" in message
    assert "Message-ID: <" in message and "@zenithwalletracker.ca>" in message and "Date: " in message


def test_port_465_uses_ssl_and_no_login_without_a_user(smtp, monkeypatch, run):
    monkeypatch.setenv("SMTP_HOST", "relay.test")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.org")
    run(_send_and_wait)

    [server] = smtp.instances
    assert isinstance(server, RecordingSMTPSSL) and server.port == 465
    assert "starttls" not in server.calls and not any(c[0] == "login" for c in server.calls if isinstance(c, tuple))
    assert len(_sent(server)) == 1


def test_gmail_settings_still_work_unchanged(smtp, monkeypatch, run):
    monkeypatch.setenv("GMAIL_USER", "sender@gmail.example")
    monkeypatch.setenv("GMAIL_PASS", "app-password")
    run(_send_and_wait)

    [server] = smtp.instances
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert server.calls[1] == ("login", "sender@gmail.example", "app-password")
    assert _sent(server)[0][1] == "sender@gmail.example"


def test_nothing_configured_logs_instead_of_sending(smtp, run, caplog):
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        run(_send_and_wait)
    assert smtp.instances == []
    assert models_module._email_account() is None


def test_a_failed_send_is_retried(smtp, monkeypatch, run):
    monkeypatch.setenv("SMTP_HOST", "smtp.provider.test")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.org")
    smtp.fail_times = 2
    run(_send_and_wait)
    assert len(smtp.instances) == 3 and len(_sent(smtp.instances[-1])) == 1


def test_failure_logs_never_include_the_recipient(smtp, monkeypatch, run, caplog):
    monkeypatch.setenv("SMTP_HOST", "smtp.provider.test")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.org")
    smtp.fail_times = 99
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        run(lambda: _send_and_wait("private-person@example.com"))
    assert len(smtp.instances) == 1 + len(models_module.EMAIL_RETRY_DELAYS)
    logged = caplog.text + "".join(str(r.exc_info) for r in caplog.records)
    assert "Gave up" in logged
    assert "private-person" not in logged and "someone@example.com" not in logged


# =====================================================================================================================
# 9. Password checks run off the event loop
# =====================================================================================================================
def test_password_checks_run_in_a_worker_thread(monkeypatch):
    manager = models_module.UserManager(None)
    user = SimpleNamespace(hashed_password=manager.password_helper.hash("right-password-123"))
    threads = []
    real_verify = manager.password_helper.verify_and_update

    def verify(*args):
        threads.append(threading.get_ident())
        return real_verify(*args)

    monkeypatch.setattr(manager.password_helper, "verify_and_update", verify)

    async def go():
        loop_thread = threading.get_ident()
        results = (await manager.check_password(user, "right-password-123"),
                   await manager.check_password(user, "wrong-password-123"))
        return loop_thread, results

    loop_thread, results = asyncio.run(go())
    assert results == (True, False)
    assert threads and loop_thread not in threads


def test_login_and_wrong_password_still_work(client, user):
    from conftest import login
    assert login(client, user.email).status_code == 200
    assert login(client, user.email, "not-the-password-1").status_code == 400
    assert login(client, "nobody-at-all@example.com").status_code == 400


@pytest.mark.parametrize("days", [1, 7, 30, 365, 1000, 3650])
def test_the_last_chart_point_is_exactly_now(days):
    # step * (points - 1) used to round a few microseconds short of now, leaving a trade logged in the same clock
    # tick out of the "now" point (the dashboard chart then ended at 0)
    timestamps, _ = services.calculate_timespans_for_portfolio_history(days)
    assert timestamps[-1] - timestamps[0] == services.timedelta(days=days)
