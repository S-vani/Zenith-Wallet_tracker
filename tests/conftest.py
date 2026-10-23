"""
Shared test setup.

Everything at module level here runs BEFORE any backend module is imported, which matters because the backend reads
its settings (database url, jwt secret, email account) at import time:
  - every test session gets its own temporary SQLite database, the real walletdatabase.db is never touched
  - SECRET is a throwaway test value and GMAIL_USER/GMAIL_PASS are empty, so no email can ever be sent
  - outgoing network connections are blocked, so a missing stub fails loudly instead of calling a real api
"""
import ipaddress
import os
import shutil
import socket
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# remove folders left behind by interrupted runs (older than an hour, so a run in parallel isn't affected)
for _old in Path(tempfile.gettempdir()).glob("zenith-tests-*"):
    try:
        if time.time() - _old.stat().st_mtime > 3600:
            shutil.rmtree(_old, ignore_errors=True)
    except OSError:
        pass
_TMP_DIR = tempfile.mkdtemp(prefix="zenith-tests-")

# load_dotenv() in the backend never overrides variables that are already set, so these win over .env
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + (Path(_TMP_DIR) / "test.db").as_posix()
os.environ["SECRET"] = "test-secret-not-used-anywhere-else-0123456789"
os.environ["GMAIL_USER"] = ""
os.environ["GMAIL_PASS"] = ""
os.environ["FRONTEND_URL"] = "http://localhost:5173"
os.environ["API_KEY"] = "test-twelvedata-key"
os.environ["API_KEY_COINEGECKO"] = "test-coingecko-key"


# ---------------------------------------------------------------------------------------------------------------------
# Network guard: only loopback connections are allowed (asyncio uses a local socket pair internally on Windows)
# ---------------------------------------------------------------------------------------------------------------------
class NetworkBlocked(RuntimeError):
    pass


def _is_local(host) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        raise NetworkBlocked(f"Tests must not use the network (tried to connect to {address!r})")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        raise NetworkBlocked(f"Tests must not use the network (tried to connect to {address!r})")
    return _real_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _is_local(host):
        raise NetworkBlocked(f"Tests must not use the network (tried to resolve {host!r})")
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex
socket.getaddrinfo = _guarded_getaddrinfo

# ---------------------------------------------------------------------------------------------------------------------
# Backend imports (only now that the environment is set up)
# ---------------------------------------------------------------------------------------------------------------------
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import backend.db_models.assets as models_module  # noqa: E402
import backend.ratelimit as ratelimit  # noqa: E402
import backend.routes.assets as routes_module  # noqa: E402
import backend.services.asset_services as services  # noqa: E402
from backend.db.database import DATABASE_URL, async_session_maker, engine  # noqa: E402
from backend.db_models.assets import Transaction, User  # noqa: E402
from backend.main import app  # noqa: E402

assert "walletdatabase" not in DATABASE_URL, "tests must never use the real database"

# Kept so the real implementations can still be tested even though every test stubs them
REAL_GET_ALL_CONVERSION_RATES = services.get_all_conversion_rates

# 1 USD = 1.4 CAD, 1 CAD = 0.7 USD, 1 CAD = 0.6 EUR (round numbers keep the expected values readable)
RATES = {"usd_to_cad": 1.4, "usd": 0.7, "eur": 0.6}

PASSWORD = "correct-horse-battery"


def pytest_sessionfinish(session, exitstatus):
    # the engine holds the sqlite file open on Windows, release it before deleting the temp folder
    try:
        engine.sync_engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------------
# Fake market data (replaces yfinance)
# ---------------------------------------------------------------------------------------------------------------------
class FakeMarket:
    """
    Stands in for the yfinance module. `prices` maps a yahoo ticker (e.g. "AAPL", "BTC-CAD", "BTC-USD") to a price in
    the ticker's own currency, and `currencies` maps a ticker to its trading currency (default USD).
    """

    def __init__(self):
        self.prices = {
            "AAPL": 100.0,  # USD
            "MSFT": 200.0,  # USD
            "SHOP.TO": 50.0,  # CAD
            "BTC-CAD": 50000.0,
            "ETH-CAD": 2000.0,
            "BTC-USD": 40000.0,
        }
        self.currencies = {"SHOP.TO": "CAD"}
        self.previous_closes = {}  # ticker -> the close before the latest one (defaults to an unchanged price)
        self.requested = []

    def Ticker(self, symbol):  # noqa: N802 - mirrors yfinance's api
        symbol = symbol.upper()  # yfinance uppercases tickers too
        self.requested.append(symbol)
        return FakeTicker(self, symbol)


class FakeTicker:
    def __init__(self, market, symbol):
        self.market = market
        self.symbol = symbol

    @property
    def info(self):
        return {"currency": self.market.currencies.get(self.symbol, "USD")}

    def history(self, start=None, end=None, period=None, interval=None):
        price = self.market.prices.get(self.symbol)
        if price is None:
            return pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([], tz="UTC"))

        if period is not None:
            # a few days of hourly candles ending now
            now = pd.Timestamp.now(tz="UTC").floor("h")
            index = pd.date_range(end=now, periods=24 * 8, freq="h", tz="UTC")
            previous = self.market.previous_closes.get(self.symbol, price)
            return pd.DataFrame({"Close": [previous] * (len(index) - 1) + [price]}, index=index)
        else:
            index = pd.DatetimeIndex([pd.Timestamp(end) - pd.Timedelta(minutes=1)])
            if index.tz is None:
                index = index.tz_localize("UTC")
        return pd.DataFrame({"Close": [price] * len(index)}, index=index)


# ---------------------------------------------------------------------------------------------------------------------
# Fake httpx (used by the stock / crypto search routes)
# ---------------------------------------------------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeHttpx:
    """
    Replaces the httpx module inside a backend module. Register responses with `fake.responses[url] = payload`
    (payload can be a callable taking the query params). Unregistered urls fail the test.
    """

    def __init__(self):
        self.responses = {}
        self.calls = []
        self.clients = []
        # code under test catches httpx.HTTPError; a payload callable can raise it to fake a timeout
        self.HTTPError = type("HTTPError", (Exception,), {})
        outer = self

        class AsyncClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs
                outer.clients.append(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, params=None, **kwargs):
                outer.calls.append((url, dict(params or {})))
                if url not in outer.responses:
                    raise NetworkBlocked(f"No fake response registered for {url}")
                payload = outer.responses[url]
                if callable(payload):
                    payload = payload(params or {})
                return FakeResponse(payload)

        self.AsyncClient = AsyncClient


class FakeSMTP:
    instances = []

    def __init__(self, *args, **kwargs):
        FakeSMTP.instances.append(self)
        raise AssertionError("Tests must never send email")


@pytest.fixture(autouse=True)
def stub_external_services(monkeypatch):
    """Applied to every test: fixed exchange rates, fake market data, fake http clients and no smtp."""

    async def fake_rates():
        return dict(RATES)

    monkeypatch.setattr(services, "get_all_conversion_rates", fake_rates)
    monkeypatch.setattr(routes_module, "get_all_conversion_rates", fake_rates)

    market = FakeMarket()
    monkeypatch.setattr(services, "yf", market)
    monkeypatch.setattr(services, "_symbol_currency_cache", {})
    monkeypatch.setattr(services, "_series_cache", {})  # cached price histories must not leak between tests

    routes_http = FakeHttpx()
    services_http = FakeHttpx()
    monkeypatch.setattr(routes_module, "httpx", routes_http)
    monkeypatch.setattr(routes_module, "_stock_search_cache", {})
    monkeypatch.setattr(services, "httpx", services_http)

    FakeSMTP.instances = []
    monkeypatch.setattr(models_module.smtplib, "SMTP", FakeSMTP)

    # The auth rate limiter counts in memory per IP, and every test client has the same one ("testclient"):
    # start each test with empty counters so the whole suite doesn't add up to a 429 (test_security.py tests it)
    ratelimit.limiter.reset()

    return SimpleNamespace(market=market, routes_http=routes_http, services_http=services_http)


@pytest.fixture
def market(stub_external_services):
    return stub_external_services.market


@pytest.fixture
def search_http(stub_external_services):
    return stub_external_services.routes_http


# ---------------------------------------------------------------------------------------------------------------------
# App client and users
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client():
    # one client (and so one event loop) for the whole session, the async engine stays on that loop
    with TestClient(app) as test_client:
        yield test_client
        # close the database connections on their own event loop so the temp file can be deleted afterwards
        test_client.portal.call(engine.dispose)


@pytest.fixture
def run(client):
    """Run an async function on the app's event loop, e.g. run(some_async_fn, arg1, arg2)."""

    def _run(fn, *args):
        return client.portal.call(fn, *args)

    return _run


def unique_email(prefix="user"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _set_user_fields(email, **values):
    async with async_session_maker() as session:
        await session.execute(update(User).where(User.email == email).values(**values))
        await session.commit()


async def _get_user(email):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalars().first()


async def _get_transaction(tx_id):
    async with async_session_maker() as session:
        return await session.get(Transaction, tx_id)


async def _set_transaction_created_at(tx_id, created_at):
    async with async_session_maker() as session:
        await session.execute(update(Transaction).where(Transaction.id == tx_id).values(created_at=created_at))
        await session.commit()


@pytest.fixture
def db(run):
    """Small helpers for reading/changing rows directly in the test database."""
    return SimpleNamespace(
        set_user=lambda email, **values: run(lambda: _set_user_fields(email, **values)),
        get_user=lambda email: run(_get_user, email),
        get_transaction=lambda tx_id: run(_get_transaction, tx_id),
        set_created_at=lambda tx_id, created_at: run(_set_transaction_created_at, tx_id, created_at),
    )


def register(client, email=None, password=PASSWORD, name="Test User", currency="CAD"):
    payload = {"email": email or unique_email(), "password": password, "name": name}
    if currency is not None:
        payload["currency"] = currency
    return client.post("/auth/register", json=payload)


def login(client, email, password=PASSWORD):
    return client.post("/auth/jwt/login", data={"username": email, "password": password})


@pytest.fixture
def make_user(client, db):
    """Create a verified, logged in user. Returns a namespace with email, id and auth headers."""

    def _make(currency="CAD", name="Test User"):
        email = unique_email()
        res = register(client, email=email, name=name, currency=currency)
        assert res.status_code == 201, res.text
        db.set_user(email, is_verified=True)
        token = login(client, email)
        assert token.status_code == 200, token.text
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
        return SimpleNamespace(email=email, id=res.json()["id"], headers=headers, currency=currency)

    return _make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def buy(client):
    """Post a transaction, e.g. buy(user, "AAPL", 2, 100) or buy(user, "btc", 0.5, 40000, asset_type="crypto")."""

    def _tx(owner, symbol, quantity, price, action="BUY", asset_type="stock", api_id=None, expect=200):
        res = client.post("/transactions", headers=owner.headers, json={
            "symbol": symbol,
            "action": action,
            "asset_type": asset_type,
            "price_of_one": price,
            "quantity": quantity,
            "api_id": api_id or symbol,
        })
        assert res.status_code == expect, res.text
        return res.json()

    return _tx


@pytest.fixture
def sell(buy):
    def _sell(owner, symbol, quantity, price, **kwargs):
        return buy(owner, symbol, quantity, price, action="SELL", **kwargs)

    return _sell


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def naive_utc(*args):
    return datetime(*args)


__all__ = ["RATES", "PASSWORD", "register", "login", "unique_email", "utc", "naive_utc", "timedelta"]
