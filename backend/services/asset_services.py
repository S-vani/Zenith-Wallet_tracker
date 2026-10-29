"""
Prices and portfolio maths: Yahoo / CoinGecko price histories (cached, "the latest close known at that time"), exchange
rates, holdings and returns, and the ledger replay that keeps every trade's history valid.
"""
import asyncio
import functools
import math
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import yfinance as yf
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models.assets import Transaction
from backend.schemas.assets import ACCOUNT_UNSET
import logging
import time

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
log = logging.getLogger("uvicorn.error")

FX_CACHE_SECONDS = 3600  # open.er-api only updates once a day and asks callers not to poll it often
FX_RETRY_SECONDS = 300  # after a failed refresh the last good rates are served, and the api is retried this often
# With no rates at all (a cold start while open.er-api is down) a failure is remembered this long: every request
# queued on the lock would otherwise retry the api one after another, each waiting for its timeout
FX_COLD_FAILURE_SECONDS = 45

SYMBOL_CURRENCY_CACHE_SIZE = 5000  # listing currencies kept (least recently used dropped first)
_symbol_currency_cache: dict[str, str | None] = {}
_rates_cache: dict = {}
_rates_cache_time: float = 0
_rates_retry_at: float = 0
_rates_failed_at: float = 0  # last failed fetch while nothing was cached (see FX_COLD_FAILURE_SECONDS)

# Yahoo ticker suffix -> listing currency, used when Yahoo doesn't say. No suffix means a US listing.
# Canadian tax dates (trade date, settlement date, the day of a trade-date exchange rate) are counted in Toronto
# time: a trade at 9 pm on Dec 31 is a Dec 31 trade, although it's stored as Jan 1 in UTC
TORONTO = ZoneInfo("America/Toronto")


def toronto_date(value: datetime) -> date:
    """The calendar date in Toronto of a stored time (naive values are UTC, like every stored trade)."""
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value.astimezone(TORONTO).date()


_SUFFIX_CURRENCY = {
    "TO": "CAD", "V": "CAD", "CN": "CAD", "NE": "CAD",
    "L": "GBp",  # London prices are quoted in pence
    "PA": "EUR", "DE": "EUR", "F": "EUR", "AS": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR", "LS": "EUR",
    "VI": "EUR", "HE": "EUR", "IR": "EUR",
    "SW": "CHF", "T": "JPY", "HK": "HKD", "AX": "AUD", "ST": "SEK", "OL": "NOK", "CO": "DKK",
}


# ---------------------------------------------------------------------------------------------------------------------
# Yahoo calls. yfinance is blocking, so it runs in threads. It gets its own pool so a burst of price lookups can't
# take every thread of asyncio's default pool, which also sends emails and hashes passwords. At most
# YAHOO_CONCURRENCY calls run at once (Yahoo rate limits by IP); the pool is bigger than that because a request that
# times out (the analyst's wait_for) lets go of its slot while its thread is still finishing the call.
# ---------------------------------------------------------------------------------------------------------------------
YAHOO_CONCURRENCY = 6
_yahoo_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="yahoo")
_loop_primitives: dict[str, tuple] = {}


def _for_this_loop(name: str, factory):
    """
    One asyncio Lock / Semaphore per event loop. The server runs a single loop, but tests start several, and a
    primitive that ever waited on one loop can't be used from another.
    """
    loop = asyncio.get_running_loop()
    held = _loop_primitives.get(name)
    if held is None or held[0] is not loop:
        held = _loop_primitives[name] = (loop, factory())
    return held[1]


async def run_yahoo(fn, *args, **kwargs):
    """Run a blocking yfinance call on the Yahoo thread pool, at most YAHOO_CONCURRENCY at a time."""
    async with _for_this_loop("yahoo", lambda: asyncio.Semaphore(YAHOO_CONCURRENCY)):
        return await asyncio.get_running_loop().run_in_executor(_yahoo_executor,
                                                                functools.partial(fn, *args, **kwargs))


def guess_listing_currency(symbol: str) -> str | None:
    """Listing currency from the ticker alone: no suffix = USD, a known exchange suffix = its currency, else None."""
    if "." not in symbol:
        return "USD"
    return _SUFFIX_CURRENCY.get(symbol.rsplit(".", 1)[1].upper())


async def get_ticker_currency(symbol: str) -> str | None:
    """
    A function used to cache the ticker currency so it is only called once since ticker.info is expensive to call many times.
    When Yahoo doesn't give one it is guessed from the ticker's suffix (and logged); None means it's unknown.
    """
    if symbol in _symbol_currency_cache:  # If we already have this symbol cached
        _symbol_currency_cache[symbol] = _symbol_currency_cache.pop(symbol)  # most recently used goes last
        return _symbol_currency_cache[symbol]

    try:
        ticker = yf.Ticker(symbol)
        info = await run_yahoo(lambda: ticker.info) or {}
    except Exception:
        info = None  # Yahoo hiccup: guess for now and ask again next time

    currency = (info or {}).get("currency")  # not uppercased: "GBp" (pence) and "GBP" (pounds) differ 100x
    if not currency:
        currency = guess_listing_currency(symbol)
        log.warning("Yahoo gave no listing currency for %s, using %s from the ticker", symbol,
                    currency or "none (its price will show as unavailable)")
        if info is None:
            return currency

    _symbol_currency_cache[symbol] = currency
    while len(_symbol_currency_cache) > SYMBOL_CURRENCY_CACHE_SIZE:  # anyone can look up made-up tickers
        _symbol_currency_cache.pop(next(iter(_symbol_currency_cache)))  # least recently used
    return currency


async def get_all_conversion_rates() -> dict:
    """
    Exchange rates, cached for an hour. If a refresh fails the last good rates are kept and served (retried every
    few minutes) instead of failing every money page; only with no rates at all is it a 503.
    """
    if _rates_usable(time.time()):
        return _rates_cache
    _fail_fast_without_rates(time.time())
    # when the rates expire many requests notice at once; only the first one asks open.er-api, the rest wait for it
    async with _for_this_loop("fx", asyncio.Lock):
        return await _refresh_conversion_rates()


RATES_UNAVAILABLE = "Exchange rates are temporarily unavailable. Please try again in a few minutes."


def _fail_fast_without_rates(now: float) -> None:
    """503 at once while nothing is cached and the last fetch failed only moments ago."""
    if not _rates_cache and now - _rates_failed_at < FX_COLD_FAILURE_SECONDS:
        raise HTTPException(status_code=503, detail=RATES_UNAVAILABLE)


def _rates_usable(now: float) -> bool:
    return bool(_rates_cache) and ((now - _rates_cache_time) < FX_CACHE_SECONDS or now < _rates_retry_at)


def has_cached_rates() -> bool:
    """True when exchange rates are in memory (fresh or the last good ones), for /health."""
    return bool(_rates_cache)


async def _refresh_conversion_rates() -> dict:
    """Fetches fresh exchange rates (one request at a time), falling back to the last good ones on failure."""
    global _rates_cache, _rates_cache_time, _rates_retry_at, _rates_failed_at

    now = time.time()
    if _rates_usable(now):  # refreshed by the request we waited for
        return _rates_cache
    _fail_fast_without_rates(now)  # the request we waited for just failed: don't ask again straight away

    try:
        usd_to_cad, usd, eur = await asyncio.gather(
            get_usd_to_cad(),
            get_usd(),
            get_eur()
        )
        fresh = {"usd_to_cad": float(usd_to_cad), "usd": float(usd), "eur": float(eur)}
        if not all(math.isfinite(v) and v > 0 for v in fresh.values()):
            raise ValueError(f"bad exchange rates {fresh}")
    except Exception as exc:
        if _rates_cache:
            _rates_retry_at = now + FX_RETRY_SECONDS
            log.warning("Exchange rate refresh failed (%s), using the rates from %.0f minutes ago", exc,
                        (now - _rates_cache_time) / 60)
            return _rates_cache
        _rates_failed_at = time.time()
        log.error("Exchange rates are unavailable and none are cached: %s", exc)
        raise HTTPException(status_code=503, detail=RATES_UNAVAILABLE)

    _rates_cache = fresh
    _rates_cache_time = now
    _rates_retry_at = 0
    _rates_failed_at = 0

    return _rates_cache


def get_conversion_factor(rates: dict, currency: str) -> float:
    """
    Function with a bunch of if statements just to avoid repeating if statements on all functions
    """
    currency = (currency or "").upper()
    if currency == "USD":
        return rates["usd"]
    elif currency == "EUR":
        return rates["eur"]
    return 1.0


QTY_STEP = Decimal("1e-10")  # the database keeps 10 decimal places
# Selling up to this fraction more than is owned still counts as "sell everything": quantities arrive as floats,
# and at a billion units a float can't hold all 10 decimals anyway. Far too small to matter as a real amount.
SELL_ALL_TOLERANCE = Decimal("1e-12")


def as_quantity(value) -> Decimal:
    """
    A quantity as an exact Decimal at the database's 10 decimal places. SQLite stores Numeric as a float and hands
    1234567.89 back as 1234567.8899999999, so go through the float's shortest form ("1234567.89", what the user
    typed) instead of using its long binary expansion.
    """
    if value is None:
        return Decimal(0)
    return Decimal(repr(float(value))).quantize(QTY_STEP)


def sell_tolerance(owned: Decimal) -> Decimal:
    return max(QTY_STEP, abs(owned) * SELL_ALL_TOLERANCE)


def _typed_currency(t) -> str | None:
    """The currency a trade's price was typed in, or None for older trades that only have the CAD price."""
    if getattr(t, "price_entered", None) is None or not getattr(t, "currency_entered", None):
        return None
    return str(t.currency_entered).upper()


def price_in_currency(t, currency: str | None, conversion: float) -> float:
    """
    One trade's price in the user's currency: the price exactly as typed when it was typed in that currency
    (so it never drifts with exchange rates), otherwise the CAD price converted at today's rate.
    """
    if currency and _typed_currency(t) == str(currency).upper():
        return float(t.price_entered)
    return float(t.price_of_one) * conversion


def profit_in_currency(t, currency: str | None, conversion: float) -> float:
    """
    A sell's realized profit in the user's currency. Profit is stored in CAD; for a sell typed in the user's
    currency it was worked out in that currency (see _replay_ledger), so convert it back at the rate of the
    sale itself rather than today's rate.
    """
    profit = float(getattr(t, "profit", None) or 0)
    if currency and _typed_currency(t) == str(currency).upper() and float(t.price_of_one) > 0:
        return profit * float(t.price_entered) / float(t.price_of_one)
    return profit * conversion


# Order trades are replayed in. Trades logged quickly one after the other can get the same created_at (the clock
# only ticks every ~15 ms on Windows), and the id is a random uuid, so at an equal time a buy goes before a sell:
# otherwise "buy then sell" could replay as "sell then buy" and be refused as selling more than was owned.
LEDGER_ORDER = (Transaction.created_at.asc(), Transaction.action.asc(), Transaction.id.asc())  # "BUY" < "SELL"


async def end_read(db: AsyncSession) -> None:
    """
    End the session's read-only transaction so its pooled connection goes back while the request waits on Yahoo /
    CoinGecko / exchange rates (a slow provider would otherwise hold one of the few connections the whole time).
    Only for sessions with nothing unsaved; rows already loaded stay usable (the session maker sets
    expire_on_commit=False) and the next query simply takes a connection again.
    """
    await db.commit()


async def get_curr_holdings_prices(holdings: dict[str, dict[str, float | str]], currency: str):
    """
    Return a dictionary in the form {api_id: curr_price}, with None for a holding no source has a price for
    """
    assets = {str(api_id): str(data["type"]) for api_id, data in holdings.items()}
    return await get_prices_at(assets, datetime.now(timezone.utc), currency, coin_ids=holding_coin_ids(holdings))


def holding_coin_ids(holdings: dict) -> dict[str, str]:
    """{api_id: CoinGecko id} for the holdings whose trades name the exact coin (see Transaction.coin_id)."""
    return {str(api_id): data["coin_id"] for api_id, data in holdings.items() if data.get("coin_id")}


def naive_utc(value: datetime) -> datetime:
    """Trades are stored as naive UTC: a time with an offset is converted to UTC first, a naive one is kept as is."""
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


async def _trades(db: AsyncSession, user_id: UUID, exclude=(), action: str | None = None,
                  start: datetime | None = None, end: datetime | None = None):
    """The user's trades, optionally only one action, a time span, and without some symbols."""
    query = select(Transaction).where(Transaction.user_id == user_id)
    if action:
        query = query.where(Transaction.action == action)
    if start is not None:
        query = query.where(Transaction.created_at > naive_utc(start))
    if end is not None:
        query = query.where(Transaction.created_at <= naive_utc(end))
    if exclude:
        query = query.where(Transaction.api_id.notin_(list(exclude)))
    return (await db.execute(query)).scalars().all()


# The three sums below add trade by trade (not one SQL SUM of CAD amounts) so trades typed in the user's currency
# use the amount as typed and never drift with today's exchange rate; older CAD-only trades convert as before.

async def get_total_realized_profit(db: AsyncSession, user_id: UUID, currency: str, exclude=()):
    """
    Add up the profit of every sell. `exclude` lists api_ids to leave out (holdings without a price are left out
    of the return maths entirely).
    """
    conversion = get_conversion_factor(await get_all_conversion_rates(), currency)
    sells = await _trades(db, user_id, exclude, action="SELL")
    return sum(profit_in_currency(t, currency, conversion) for t in sells)


async def get_cash_flow_between(
        db: AsyncSession,
        user_id: UUID,
        start: datetime,
        end: datetime,
        currency: str,
        exclude=()
):
    """
    Money moved into the account between start and end: buys count positive, sells negative. Imagine someone's
    portfolio was $1000 a week ago and is $2000 now, but they profited $100 and bought another $900: this returns
    the $900 so it isn't counted as profit.
    """
    conversion = get_conversion_factor(await get_all_conversion_rates(), currency)
    trades = await _trades(db, user_id, exclude, start=start, end=end)
    return sum(price_in_currency(t, currency, conversion) * float(t.quantity) * (1 if t.action == "BUY" else -1)
               for t in trades)


async def get_buys_between(
        db: AsyncSession,
        user_id: UUID,
        start: datetime | None,
        end: datetime,
        currency: str,
        exclude=()
):
    """
    Money put in by buying between start (exclusive, None = since the first trade) and end: the cost of every buy.
    Used as the base of the return % together with the value at the start of the period.
    """
    conversion = get_conversion_factor(await get_all_conversion_rates(), currency)
    buys = await _trades(db, user_id, exclude, action="BUY", start=start, end=end)
    return sum(price_in_currency(t, currency, conversion) * float(t.quantity) for t in buys)


async def get_holdings_at_time(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime,
        currency: str
):
    """
    Return a dictionary mapping an api id to another dictionary with average price, quantity  and type meant to be a dictionary
    of all the holdings at a certain time. The average price is in the user's currency, using each buy's price as
    typed when it was typed in that currency (so cost basis doesn't move with exchange rates).
    """
    holdings_at_timestamp = {}

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.created_at <= timestamp
        )
        .order_by(*LEDGER_ORDER)
    )

    transactions = result.scalars().all()  # all transactions from timestamp and before

    coin_ids = {}
    for t in transactions:
        apply_trade(holdings_at_timestamp, t, currency, conversion)
        if getattr(t, "coin_id", None):
            coin_ids[str(t.api_id)] = t.coin_id  # the newest trade that names the exact coin wins
    split, _ = account_split(transactions)

    return {
        api_id: {"avg_price": h["avg_price"], "quantity": float(h["qty"]), "type": h["type"],
                 "coin_id": coin_ids.get(api_id),
                 # {account or "UNSET": quantity}: lets the add form say how much one account holds
                 "accounts": {account: float(qty) for account, qty in split.get(api_id, {}).items()}}
        for api_id, h in holdings_at_timestamp.items()
    }


def apply_trade(positions: dict, t, currency: str, conversion: float) -> None:
    """
    Add one trade (oldest first) to `positions` ({api_id: {"avg_price", "qty", "type"}}), average cost method:
    a buy moves the average price, a sell only lowers the quantity, and selling everything removes the position.
    Shared by the holdings and the portfolio chart, so the chart's "invested" line matches the holdings' cost.
    """
    api_id = str(t.api_id)
    qty = as_quantity(t.quantity)  # exact sums, so "Sell all" offers exactly what is owned

    if str(t.action) == "BUY":
        price = price_in_currency(t, currency, conversion)
        if api_id in positions:  # if the api_id is already in the dictionary recalculate its values
            holding = positions[api_id]
            holding["avg_price"] = get_holdings_helper(holding["avg_price"], price, holding["qty"], qty)
            holding["qty"] += qty
        else:
            positions[api_id] = {"avg_price": price, "qty": qty, "type": t.asset_type}

    elif api_id in positions:  # SELL
        holding = positions[api_id]
        if qty >= holding["qty"] - sell_tolerance(holding["qty"]):
            del positions[api_id]  # fully sold, so it's no longer a holding
        else:
            holding["qty"] -= qty


async def get_holdings_at_time_list(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime,
        currency: str
):
    """
    Take the dictionary that get_holdings_at_time returns and turn it into a list to be more easily used by the frontend
    """
    result = await get_holdings_at_time(db, user_id, timestamp, currency)
    await end_read(db)
    prices = await get_curr_holdings_prices(result, currency)

    curr_holdings_list = []

    for key, value in result.items():
        price = prices.get(key)

        curr_holdings_list.append({
            "symbol": key,
            "price_paid": float(value["avg_price"]) * float(value["quantity"]),
            "quantity": float(value["quantity"]),
            "type": value["type"],
            "coin_id": value.get("coin_id"),  # CoinGecko id when the trades name the exact coin (for its chart)
            "accounts": value.get("accounts", {}),  # quantity per account (see account_split); adds up to quantity
            # None = "price unavailable" (no source has one), so it isn't shown as worth $0 / -100%
            "current_price": float(price) * float(value["quantity"]) if price is not None else None
        })

    return curr_holdings_list


def get_holdings_helper(curr_avg: float, new_price: float, curr_quantity: float, new_quantity: float):
    """
    Calculate the average price paid for a certain holding
    """
    total_cost = (float(curr_avg) * float(curr_quantity)) + (float(new_price) * float(new_quantity))
    return total_cost / float((float(curr_quantity) + float(new_quantity)))


_usd_rates_cache: dict = {"time": 0.0, "rates": {}, "retry_at": 0.0}


def _cross_rates_usable(now: float) -> bool:
    fresh = _usd_rates_cache["rates"] and now - _usd_rates_cache["time"] < FX_CACHE_SECONDS
    return bool(fresh or now < _usd_rates_cache.get("retry_at", 0.0))


async def _refresh_usd_cross_rates() -> None:
    """Units of every currency per 1 USD, refreshed hourly; a failed refresh keeps the old table (retried later)."""
    if _cross_rates_usable(time.time()):
        return
    async with _for_this_loop("fx-cross", asyncio.Lock):  # one refresh at a time, like get_all_conversion_rates
        now = time.time()
        if not _cross_rates_usable(now):
            await _fetch_usd_cross_rates(now)


async def _fetch_usd_cross_rates(now: float) -> None:
    """Refreshes the USD cross rates used to turn listing currencies (EUR, GBp...) into CAD."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get("https://open.er-api.com/v6/latest/USD")
        rates = res.json().get("rates")
        if not isinstance(rates, dict) or not rates:  # an error payload must not wipe the last good table
            raise ValueError("no rates in the response")
        _usd_rates_cache["rates"] = rates
        _usd_rates_cache["time"] = now
    except Exception as exc:
        _usd_rates_cache["retry_at"] = now + FX_RETRY_SECONDS
        log.warning("Cross exchange rates couldn't be refreshed (%s), keeping the last ones", exc)


async def get_native_to_cad_factor(currency: str | None) -> float | None:
    """
    Multiplier that turns a price quoted in `currency` (a stock's listing currency from Yahoo) into CAD.
    Handles any currency (EUR, GBP, JPY, ...) via USD cross rates; London prices quoted in pence ("GBp") are / 100.
    Returns None (and logs it) for a currency there's no rate for, so that price shows as unavailable instead of
    silently being treated as USD.
    """
    if not currency:
        return None
    if currency in ("GBp", "GBX", "GBx"):
        pounds = await get_native_to_cad_factor("GBP")
        return pounds / 100 if pounds is not None else None
    code = currency.upper()
    if code == "CAD":
        return 1.0
    rates = await get_all_conversion_rates()
    if code == "USD":
        return float(rates["usd_to_cad"])

    # other currencies: CAD per 1 unit = (CAD per USD) / (units per USD)
    await _refresh_usd_cross_rates()
    per_usd = _usd_rates_cache["rates"].get(code)
    if not per_usd:
        log.warning("No exchange rate for listing currency %s, its prices are shown as unavailable", code)
        return None
    return float(rates["usd_to_cad"]) / float(per_usd)


async def get_usd_to_cad():
    """
    use an api to get the current usd to cad value
    """
    url = "https://open.er-api.com/v6/latest/USD"

    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()

    cad = data.get("rates", {}).get("CAD")

    return float(cad)


async def get_usd():
    """
    use an api to get the current usd price of 1 cad
    """

    url = "https://open.er-api.com/v6/latest/CAD"

    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()

    usd = data.get("rates", {}).get("USD")

    return float(usd)


async def get_eur():
    """
    use an api to get the current eur price of 1 cad
    """

    url = "https://open.er-api.com/v6/latest/CAD"

    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()

    eur = data.get("rates", {}).get("EUR")

    return float(eur)


# ---------------------------------------------------------------------------------------------------------------------
# Price series. Every price (cards, holdings, charts) comes from one cached history per asset, read as "the latest
# close that was known at that time". Yahoo labels a bar with its START (daily bars at 00:00 exchange time) but its
# close only exists once the bar has ended, so a bar counts from start + bar length (or from when it was fetched,
# for the bar still in progress). Using the nearest label instead could pick a close from the future.
# ---------------------------------------------------------------------------------------------------------------------
BAR_LENGTH = {"5m": timedelta(minutes=5), "60m": timedelta(hours=1), "1d": timedelta(days=1),
              "1wk": timedelta(weeks=1)}
SERIES_CACHE_SECONDS = {"5m": 60, "60m": 300, "1d": 1800, "1wk": 6 * 3600}
STALE_SECONDS = 24 * 3600  # if a refresh fails (e.g. a Yahoo outage), the last good prices are served for up to a day
FAILURE_SECONDS = 60  # a failed fetch with nothing to fall back on isn't retried for this long
LIVE_SLACK = timedelta(seconds=60)  # "now" is taken just before the fetch, so allow the live bar a little slack

# Lookups at one moment use the finest history that reaches back far enough: (max age, Yahoo period, interval)
LOOKUP_SPECS = [
    (timedelta(hours=36), "2d", "5m"),
    (timedelta(days=80), "3mo", "60m"),
    (timedelta(days=700), "2y", "1d"),
    (timedelta(days=3400), "10y", "1wk"),
]
# The /prices/history chart ranges (unchanged)
CHART_SPECS = {"1D": ("2d", "5m"), "1W": ("7d", "60m"), "1M": ("1mo", "1d"), "1Y": ("1y", "1d"),
               "5Y": ("5y", "1wk"), "MAX": ("max", "1wk")}
# CoinGecko fallback range for a Yahoo period (its free plan only goes back 365 days)
COINGECKO_RANGE = {"2d": "1W", "7d": "1W", "1mo": "1M", "3mo": "1Y"}
COINGECKO_CACHE_SECONDS = {"1D": 300, "1W": 600, "1M": 1800, "1Y": 3600}
COINGECKO_EMPTY_SECONDS = 300  # an empty answer may just be its rate limit, so check again sooner

_series_cache: dict[tuple, dict] = {}
# Fetches in progress, by cache key: requests that miss the cache together wait for one fetch instead of each
# asking Yahoo / CoinGecko for the same history
_series_inflight: dict[tuple, asyncio.Task] = {}


@dataclass
class PriceSeries:
    """One asset's price history, oldest first, with when each close became known."""
    labels: list[str] = field(default_factory=list)  # bar times as the source gave them (for the charts)
    times: list[datetime] = field(default_factory=list)
    known: list[datetime] = field(default_factory=list)  # when each close was known (see above)
    closes: list[float] = field(default_factory=list)  # in the source's own currency
    volumes: list[float | None] = field(default_factory=list)
    _days: list[date] | None = field(default=None, repr=False, compare=False)  # bar_days, worked out once

    def close_at(self, at: datetime) -> float | None:
        """The latest close known at `at`, or None if the history doesn't reach back that far."""
        i = bisect_right(self.known, at + LIVE_SLACK) - 1
        return self.closes[i] if i >= 0 else None

    def bar_days(self) -> list[date]:
        """
        Each bar's own calendar date. Daily bars are labelled with their start in the exchange's time zone (Yahoo's
        FX bars start at midnight London time, 23:00 UTC in summer), so the label's date is used, not the UTC one.
        """
        if self._days is None or len(self._days) != len(self.closes):
            days = []
            for i in range(len(self.closes)):
                label = self.labels[i] if i < len(self.labels) else ""
                try:
                    days.append(date.fromisoformat(label[:10]))
                except ValueError:
                    days.append((self.times[i] if i < len(self.times) else self.known[i]).date())
            self._days = days
        return self._days

    def close_on_day(self, day: date) -> tuple[float, date] | None:
        """(close, its bar's date) of the bar dated `day`, else of the last bar before it; None before the first."""
        days = self.bar_days()
        i = bisect_right(days, day) - 1
        return (self.closes[i], days[i]) if i >= 0 else None


def lookup_spec(age: timedelta) -> tuple[str, str]:
    """The Yahoo period and interval of the finest history that reaches back `age`."""
    for max_age, period, interval in LOOKUP_SPECS:
        if age <= max_age:
            return period, interval
    return "max", "1wk"


def _as_utc(value) -> datetime:
    """A pandas / ISO / naive time as an aware UTC datetime."""
    value = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _series_from_history(hist, bar: timedelta, fetched: datetime) -> PriceSeries | None:
    """A PriceSeries from a Yahoo history (rows without a real close are skipped), or None when there's none."""
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    volumes = hist["Volume"] if "Volume" in hist.columns else None
    rows = []
    for i, (label, close) in enumerate(zip(hist.index, hist["Close"])):
        close = float(close)
        if not math.isfinite(close) or close <= 0:  # Yahoo sometimes returns today's row with a missing (NaN) close
            continue
        volume = volumes.iloc[i] if volumes is not None else None
        rows.append((_as_utc(label), str(label), close, float(volume) if volume is not None and volume == volume else None))
    rows.sort(key=lambda r: r[0])

    series = PriceSeries()
    for start, label, close, volume in rows:
        series.labels.append(label)
        series.times.append(start)
        series.known.append(min(start + bar, fetched))
        series.closes.append(close)
        series.volumes.append(volume)
    return series if series.closes else None


async def _cached_series(key: tuple, ttl: float, fetch, empty_ttl: float | None = None) -> PriceSeries | None:
    """
    Cache around one price history. An empty answer or an error right after good data is far more likely a hiccup
    than a delisting, so the last good copy (up to STALE_SECONDS old) is served instead of nothing.
    Concurrent misses for the same key share one fetch.
    """
    entry = _series_cache.get(key)
    if entry and time.time() - entry["checked"] < entry["ttl"]:
        if entry.get("error"):
            raise entry["error"]
        return entry["series"]

    loop = asyncio.get_running_loop()
    task = _series_inflight.get(key)
    if task is None or task.done() or task.get_loop() is not loop:
        task = loop.create_task(_fill_series(key, ttl, fetch, empty_ttl))
        _series_inflight[key] = task
        task.add_done_callback(functools.partial(_series_fetch_done, key))
    # shielded: one waiter giving up (a timeout, a closed connection) mustn't cancel the fetch for the others
    return await asyncio.shield(task)


def _series_fetch_done(key: tuple, task: asyncio.Task) -> None:
    """Forgets a finished fetch and keeps its result from being reported as an unhandled error."""
    if _series_inflight.get(key) is task:
        del _series_inflight[key]
    if not task.cancelled():
        task.exception()  # marks the error as seen, in case every waiter gave up before it finished


async def _fill_series(key: tuple, ttl: float, fetch, empty_ttl: float | None) -> PriceSeries | None:
    """Fetches a series for the cache (sharing one fetch between callers), keeping the old one if it fails."""
    now = time.time()
    entry = _series_cache.get(key)
    stale = entry["series"] if entry and entry["series"] is not None and now - entry["fetched"] < STALE_SECONDS \
        else None
    try:
        series = await fetch()
    except Exception as exc:
        if stale is not None:
            log.warning("Price refresh for %s failed (%s), serving the last good prices", key, exc)
            entry.update(checked=now, ttl=ttl)
            return stale
        _series_cache[key] = {"series": None, "fetched": now, "checked": now, "ttl": FAILURE_SECONDS, "error": exc}
        raise

    if series is None and stale is not None:
        entry.update(checked=now, ttl=ttl)
        return stale

    if len(_series_cache) > 5000:  # drop long-dead entries so the cache can't grow forever
        for old in [k for k, v in _series_cache.items() if now - v["checked"] > STALE_SECONDS]:
            del _series_cache[old]
    _series_cache[key] = {"series": series, "fetched": now, "checked": now,
                          "ttl": ttl if series is not None or empty_ttl is None else empty_ttl}
    return series


async def _yahoo_series(ticker: str, period: str, interval: str) -> PriceSeries | None:
    """One Yahoo price history (in the ticker's own currency), or None when Yahoo has no prices for it."""

    async def fetch():
        """Yahoo's history for the ticker as a PriceSeries."""
        requested_at = datetime.now(timezone.utc)
        hist = await run_yahoo(yf.Ticker(ticker).history, period=period, interval=interval)
        return _series_from_history(hist, BAR_LENGTH[interval], requested_at)

    return await _cached_series(("yahoo", ticker.upper(), period, interval), SERIES_CACHE_SECONDS[interval], fetch)


# ---------------------------------------------------------------------------------------------------------------------
# Trade-date exchange rates. A price typed in USD / EUR is stored in CAD too; for a backdated trade (e.g. a broker
# import spanning years) the CAD amount uses the rate of the trade's own date, which the capital gains / ACB report
# needs (CRA wants the rate of the day of the trade). One daily Yahoo history per currency, cached like any price
# series, serves every date: the daily bar dated the trade's date in Toronto time, or the bar before it when that
# day has none (weekends, holidays, or not published yet). When it's unavailable the current rate is used (the
# behaviour before this existed). Trades logged live (or less than TRADE_DATE_FX_AFTER ago) use the current
# open.er-api rate, which is the rate of that day anyway.
# ---------------------------------------------------------------------------------------------------------------------
FX_HISTORY_TICKERS = {"USD": "USDCAD=X", "EUR": "EURCAD=X"}  # closes are CAD per 1 unit of the currency
TRADE_DATE_FX_AFTER = timedelta(days=1)  # trades newer than this simply use the current rate
FX_HISTORY_PERIOD = "max"  # imports can reach back many years; still one request per currency
FX_MAX_GAP_DAYS = 7  # a previous bar older than this means the history has a hole: use the current rate instead


def needs_trade_date_rate(currency: str | None, at: datetime | None, now: datetime | None = None) -> bool:
    """True when a price typed in `currency` for a trade at `at` should use the rate of that date."""
    if at is None or (currency or "").upper() not in FX_HISTORY_TICKERS:
        return False
    now = now or datetime.now(timezone.utc)
    return now - _as_utc(at) > TRADE_DATE_FX_AFTER


async def fx_history(currency: str) -> PriceSeries | None:
    """Yahoo's daily history of CAD per 1 unit of `currency`, or None when it can't be had (the caller falls back)."""
    ticker = FX_HISTORY_TICKERS.get((currency or "").upper())
    if ticker is None:
        return None
    try:
        return await _yahoo_series(ticker, FX_HISTORY_PERIOD, "1d")
    except Exception as exc:
        log.warning("Exchange rate history for %s is unavailable (%s), using the current rate", currency, exc)
        return None


def cad_price_on(price: float, currency: str | None, at: datetime | None, rates: dict,
                 history: PriceSeries | None) -> float:
    """
    A price typed in `currency` as CAD: for a backdated trade (see needs_trade_date_rate) at the close of the daily
    bar dated the trade's Toronto date (the bar before it on weekends and holidays), otherwise, or with no usable
    close, at the current rate.
    """
    current = get_conversion_factor(rates, currency)  # units of the currency per 1 CAD
    if history is not None and needs_trade_date_rate(currency, at):
        day = toronto_date(at)
        found = history.close_on_day(day)
        if found is not None:
            rate, bar_day = found
            # a close far from today's rate is a bad Yahoo row (USD/CAD and EUR/CAD never moved 2x in decades)
            if (day - bar_day).days <= FX_MAX_GAP_DAYS and math.isfinite(rate) and 0.5 < rate * current < 2:
                return float(price) * rate
    return float(price) / current


async def to_cad_on_trade_date(price: float, currency: str | None, at: datetime | None, rates: dict) -> float:
    """cad_price_on for one trade, fetching (or reusing the cached) rate history only when it's backdated."""
    history = await fx_history(currency) if needs_trade_date_rate(currency, at) else None
    return cad_price_on(price, currency, at, rates, history)


async def _coingecko_series(symbol: str, range_code: str, coin_id: str | None = None) -> PriceSeries | None:
    """
    CoinGecko prices in CAD for coins Yahoo doesn't list (e.g. PEPE), same fallback as the /prices/history chart.
    With a `coin_id` (saved with the trade) that exact coin is used, otherwise the most popular coin with the ticker.
    Its demo key is rate limited, so answers (empty ones too, briefly) are cached.
    """
    range_code = "1Y" if range_code in ("5Y", "MAX") else range_code  # its free plan stops at 365 days either way

    async def fetch():
        """CoinGecko's history for the coin as a PriceSeries in CAD."""
        from backend.analyst import data as market_data  # imported here: analyst.data imports this module
        points = await market_data.coingecko_chart(symbol, range_code, "CAD", coin_id=coin_id)
        series = PriceSeries()
        for point in sorted(points, key=lambda p: _as_utc(p["time"])):
            price = float(point["price"])
            if not math.isfinite(price) or price <= 0:
                continue
            at = _as_utc(point["time"])
            series.labels.append(str(point["time"]))
            series.times.append(at)
            series.known.append(at)  # CoinGecko gives prices at a moment, not bars
            series.closes.append(price)
            series.volumes.append(None)
        return series if series.closes else None

    ident = f"id:{coin_id}" if coin_id else symbol.lower()  # a coin id and a ticker can be spelled the same
    return await _cached_series(("coingecko", ident, range_code),
                                COINGECKO_CACHE_SECONDS.get(range_code, 1800), fetch,
                                empty_ttl=COINGECKO_EMPTY_SECONDS)


async def _asset_series(api_id: str, asset_type: str, period: str, interval: str, coingecko: bool = True,
                        coin_id: str | None = None):
    """
    Price history of one asset as (series, to_cad, source), where close * to_cad is the price in CAD, or
    (None, None, source) when no source has prices. Crypto tries Yahoo's SYMBOL-CAD pair, then SYMBOL-USD, then
    CoinGecko (by `coin_id` when known), in that order everywhere, so the value card, holdings and charts all agree.
    """
    if asset_type == "crypto":
        base = str(api_id).upper()
        error = None
        for quote in ("CAD", "USD"):
            ticker = f"{base}-{quote}"
            try:
                series = await _yahoo_series(ticker, period, interval)
            except Exception as exc:
                error = exc
                continue
            if series:
                to_cad = 1.0 if quote == "CAD" else await get_native_to_cad_factor("USD")
                return series, to_cad, ticker
        if coingecko:
            try:
                series = await _coingecko_series(base, COINGECKO_RANGE.get(period, "1Y"), coin_id)
            except Exception as exc:
                error, series = exc, None
            if series:
                return series, 1.0, "CoinGecko"
        if error is not None:
            raise error
        return None, None, f"{base}-CAD"

    to_cad = await get_native_to_cad_factor(await get_ticker_currency(api_id))
    if to_cad is None:  # unknown listing currency (logged): unavailable rather than guessed
        return None, None, api_id
    series = await _yahoo_series(api_id, period, interval)
    return (series, to_cad, api_id) if series else (None, None, api_id)


async def get_prices_at(assets: dict[str, str], timestamp: datetime, currency: str,
                        coin_ids: dict[str, str] | None = None) -> dict[str, float | None]:
    """
    Price of each asset ({api_id: "stock" | "crypto"}) at `timestamp` in the user's currency, as {api_id: price}.
    None means no source has a price for it then: callers leave it out instead of counting it as worth 0.
    `coin_ids` ({api_id: CoinGecko id}) makes the CoinGecko fallback ask for that exact coin.
    """
    if not assets:
        return {}

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)
    period, interval = lookup_spec(datetime.now(timezone.utc) - timestamp)

    async def fetch_one(api_id, asset_type):
        """One asset's price at the timestamp, or None when no source has it."""
        try:
            series, to_cad, _ = await _asset_series(api_id, asset_type, period, interval,
                                                    coin_id=(coin_ids or {}).get(api_id))
        except Exception as exc:  # the price source is down and nothing is cached
            log.warning("No price for %s: %s", api_id, exc)
            return api_id, None
        close = series.close_at(timestamp) if series else None
        return api_id, close * to_cad * conversion if close is not None else None

    results = await asyncio.gather(*[fetch_one(api_id, asset_type) for api_id, asset_type in assets.items()])
    return dict(results)


async def get_crypto_prices_at(api_ids: list[str], timestamp: datetime, currency: str):
    """
    Functions that takes in a list of api_ids of cryptos with a timestamp and currency and returns a dictionary of the form,
    {api_id: price} (None when there's no price)
    """
    return await get_prices_at({api_id: "crypto" for api_id in api_ids}, timestamp, currency)


async def get_stock_prices_at(symbols: list[str], timestamp: datetime, currency: str):
    """
    Functions that takes in a list of symbols of stocks with a timestamp and currency and returns a dictionary of the form,
    {symbol: price} (None when there's no price)
    """
    return await get_prices_at({symbol: "stock" for symbol in symbols}, timestamp, currency)


async def get_latest_stock_quotes(symbols: list[str]) -> dict[str, dict[str, float]]:
    """
    Latest price and the previous daily close for each symbol from Yahoo, in the listing currency, as
    {symbol: {"close": ..., "previous_close": ...}}. Used by the stock search instead of TwelveData's quote endpoint,
    which costs one of the 8 free credits per minute for every symbol. Symbols Yahoo has no data for are left out.
    """
    async def fetch_one(symbol):
        """The latest close and the change since the one before, for one ticker."""
        hist = await run_yahoo(yf.Ticker(symbol).history, period="5d", interval="1d")
        closes = hist["Close"].dropna() if not hist.empty else []
        if len(closes) == 0:
            return symbol, None
        close = float(closes.iloc[-1])  # today's live price while the market is open
        previous = float(closes.iloc[-2]) if len(closes) > 1 else close
        return symbol, {"close": close, "previous_close": previous}

    async def safe_fetch(symbol):
        """fetch_one, with any error read as "no quote" so one ticker can't break the search."""
        try:
            return await fetch_one(symbol)
        except Exception:  # one bad ticker shouldn't empty the whole search
            return symbol, None

    results = await asyncio.gather(*[safe_fetch(symbol) for symbol in symbols])
    return {symbol: quote for symbol, quote in results if quote is not None}


def create_holding_filter(
        user_id: UUID,
        symbol: str | None = None,
        action: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        account_type: str | None = None,
):
    """
    create a query for the backend to use to query the database. `account_type` is one of ACCOUNT_TYPES, or
    ACCOUNT_UNSET for trades with no account set
    """
    query = select(Transaction).where(Transaction.user_id == user_id)

    # transactions are stored in UTC without a timezone, so convert filter dates the same way
    start_date = naive_utc(start_date) if start_date else None
    end_date = naive_utc(end_date) if end_date else None

    if symbol:
        # escape LIKE wildcards so typing "_" or "%" doesn't match everything
        escaped = symbol.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Transaction.symbol.ilike(f"{escaped}%", escape="\\"))

    if action:
        query = query.where(Transaction.action == action)

    if account_type == ACCOUNT_UNSET:
        query = query.where(Transaction.account_type.is_(None))
    elif account_type:
        query = query.where(Transaction.account_type == account_type)

    if start_date:
        query = query.where(Transaction.created_at >= start_date)

    if end_date:  # Will always be true
        query = query.where(Transaction.created_at <= end_date)
    else:
        query = query.where(Transaction.created_at <= datetime.now(timezone.utc))

    return query


class _Replay:
    """Running state while replaying one symbol's trades in date order (average cost method)."""

    def __init__(self):
        """An empty position: no quantity, no cost."""
        self.quantity = Decimal(0)
        self.avg_cad = Decimal(0)
        # Average cost in a currency C, written as a + b * rate: `a` comes from buys typed in C (their typed price)
        # and `b` from every other buy (CAD price, converted at the rate of whichever sale asks). Both follow the
        # same weighted average as avg_cad, so they're kept per currency seen; a missing C means (0, avg_cad).
        self.in_currency: dict[str, tuple[Decimal, Decimal]] = {}
        self.oversold = False


def _replay_ledger(transactions, set_profits: bool = True) -> _Replay:
    """
    Replay trades (already sorted oldest first): track quantity and average cost, set each sell's profit (in CAD)
    and flag the history as oversold if a sell ever takes more than was owned at that moment.

    A sell typed in some currency gets its profit worked out in that currency (a USD sale at $110 of a USD buy at
    $100 is +$10, whatever USD/CAD did in between) and stored in CAD at the sale's own rate. Older trades with no
    typed price keep the plain CAD maths.
    """
    state = _Replay()
    for t in transactions:
        qty = as_quantity(t.quantity)
        price_cad = Decimal(str(t.price_of_one))
        typed_in = _typed_currency(t)

        if str(t.action) == "BUY":
            if set_profits and getattr(t, "profit", None):
                t.profit = 0  # a sell edited into a buy kept the profit of the sale it used to be
            total = state.quantity + qty
            if typed_in and typed_in not in state.in_currency:
                state.in_currency[typed_in] = (Decimal(0), state.avg_cad)
            for code, (a, b) in state.in_currency.items():
                own = Decimal(str(t.price_entered)) if code == typed_in else Decimal(0)
                other = Decimal(0) if code == typed_in else price_cad
                state.in_currency[code] = ((state.quantity * a + qty * own) / total,
                                           (state.quantity * b + qty * other) / total)
            state.avg_cad = (state.quantity * state.avg_cad + qty * price_cad) / total
            state.quantity = total
            continue

        # SELL
        if qty > state.quantity + sell_tolerance(state.quantity):
            state.oversold = True
            return state

        if set_profits:
            if typed_in and price_cad > 0:
                typed_price = Decimal(str(t.price_entered))
                rate = typed_price / price_cad  # units of the typed currency per CAD on the day of the sale
                a, b = state.in_currency.get(typed_in, (Decimal(0), state.avg_cad))
                t.profit = (typed_price - (a + b * rate)) * qty / rate
            else:
                t.profit = (price_cad - state.avg_cad) * qty

        # within the tolerance this is "sell everything", so the position ends at exactly 0
        state.quantity = max(Decimal(0), state.quantity - qty)

    return state


async def rebuild_symbol_ledger(db: AsyncSession, user_id: UUID, symbol: str) -> bool:
    """
    Replay every transaction of one symbol in date order, recompute the profit of each sell from the average cost
    at that moment, and return False if the history ever sells more than was owned (e.g. after an edit, a delete
    or a backdated trade).
    """
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.symbol == symbol)
        .order_by(*LEDGER_ORDER)
    )

    return not _replay_ledger(result.scalars().all()).oversold


# ---------------------------------------------------------------------------------------------------------------------
# Per-account check. Holdings, average cost and the ledger stay per symbol across accounts; on top of that a sell
# mustn't sell more than its own account held (10 AAPL in a TFSA can't be sold 15 at a time just because a
# non-registered account has 6 more). The rule, chosen so older data stays editable:
#   - a sell tagged with an account may use that account's shares plus the "not set" ones (untagged buys could have
#     been in any account); anything past that is the sell's shortfall
#   - a sell with no account set is only checked across all accounts (rebuild_symbol_ledger)
#   - a create, edit or delete is refused (409) only when it makes some sell's shortfall bigger than it was before
#     (a new sell starts at 0). Older histories (sells tagged to another account than their buys, from before
#     accounts were checked) keep their shortfall and stay editable, as long as an edit doesn't make it worse.
# Past a shortfall the replay goes on like allocation.replay_accounts (the rest from "not set", then the largest
# other account), so the split matches the allocation view and the add form's "You own N" hint.
# ---------------------------------------------------------------------------------------------------------------------
ACCOUNT_OVERSOLD = "Insufficient holdings in that account"


def account_split(trades) -> tuple[dict[str, dict[str, Decimal]], dict[str, Decimal]]:
    """
    Replay trades (sorted oldest first, LEDGER_ORDER) per account. Returns ({api_id: {account or "UNSET": quantity}}
    for what is held at the end, {sell id: shortfall} for the tagged sells that took more than their account plus the
    "not set" shares held then).
    """
    positions: dict[str, dict[str, Decimal]] = {}
    shortfalls: dict[str, Decimal] = {}
    for t in trades:
        api_id = str(t.api_id)
        account = getattr(t, "account_type", None) or ACCOUNT_UNSET
        qty = as_quantity(t.quantity)

        if str(t.action) == "BUY":
            accounts = positions.setdefault(api_id, {})
            accounts[account] = accounts.get(account, Decimal(0)) + qty
            continue

        accounts = positions.get(api_id) or {}
        if account != ACCOUNT_UNSET:
            usable = accounts.get(account, Decimal(0)) + accounts.get(ACCOUNT_UNSET, Decimal(0))
            if qty > usable + sell_tolerance(usable):
                shortfalls[str(t.id)] = qty - usable
        if not accounts:
            continue
        total = sum(accounts.values())
        if qty >= total - sell_tolerance(total):
            del positions[api_id]  # sold out, like apply_trade
            continue

        rest = qty
        order = [account] + sorted((k for k in accounts if k != account),
                                   key=lambda k: (k != ACCOUNT_UNSET, -accounts[k], k))
        for key in order:
            if rest <= 0:
                break
            taken = min(rest, accounts.get(key, Decimal(0)))
            if key in accounts:
                accounts[key] -= taken
            rest -= taken
        for key in [k for k, q in accounts.items() if q <= 0]:
            del accounts[key]
    return positions, shortfalls


async def account_shortfalls(db: AsyncSession, user_id: UUID, symbols) -> dict[str, Decimal]:
    """{sell id: shortfall} over the given symbols' trades as they are in the session now (see account_split)."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.symbol.in_(list(symbols)))
        .order_by(*LEDGER_ORDER)
    )
    by_symbol: dict[str, list] = {}
    for t in result.scalars().all():
        by_symbol.setdefault(str(t.symbol), []).append(t)
    shortfalls: dict[str, Decimal] = {}
    for trades in by_symbol.values():
        shortfalls.update(account_split(trades)[1])
    return shortfalls


def account_oversell_added(before: dict[str, Decimal], after: dict[str, Decimal]) -> bool:
    """True when a change left some sell short of its account by more than it was before the change."""
    return any(short > before.get(tid, Decimal(0)) + QTY_STEP for tid, short in after.items())


def turn_list_to_dict(lst, conversion: float = 1.0, currency: str | None = None):
    """
    loop through a list of transactions and turn it into a list of dictionaries that are easier to use,
    with prices converted from CAD into the users currency (or shown as typed, when typed in `currency`)
    """
    transactions_data = []
    for trans in lst:
        transactions_data.append(
            {
                "id": str(trans.id),
                "user_id": str(trans.user_id),
                "action": str(trans.action),
                "profit": profit_in_currency(trans, currency, conversion),
                "asset_type": str(trans.asset_type),
                "symbol": str(trans.symbol),
                "api_ids": str(trans.api_id),
                "coin_id": getattr(trans, "coin_id", None),
                "price_of_one": price_in_currency(trans, currency, conversion),
                "quantity": float(as_quantity(trans.quantity)),
                "account_type": getattr(trans, "account_type", None),  # None = not set
                "created_at": trans.created_at.replace(tzinfo=timezone.utc).isoformat()
            }
        )
    return transactions_data


async def get_position_values_at(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime,
        currency: str
) -> dict[str, float | None]:
    """
    Value of each holding at a specific time in the user's currency, {api_id: value}, with None for a holding that
    has no price at that time.
    """
    holdings = await get_holdings_at_time(db, user_id, timestamp, currency)
    await end_read(db)  # only read routes use this
    prices = await get_prices_at({api_id: str(data["type"]) for api_id, data in holdings.items()}, timestamp, currency,
                                 coin_ids=holding_coin_ids(holdings))

    return {
        api_id: float(prices[api_id]) * float(data["quantity"]) if prices.get(api_id) is not None else None
        for api_id, data in holdings.items()
    }


async def get_history_of_prices(
        symbol: str,
        type: str,
        range: str,
        currency: str
):
    """
    Get historical prices of that specific symbol/holding on specific ranges, and turn it into a tuple returning the
    symbol and a list of prices. Yahoo only; /prices/history falls back to CoinGecko itself (get_coingecko_history).
    """
    period, interval = CHART_SPECS.get(range, CHART_SPECS["5Y"])  # Translate it into a form that yahoo finance can understand

    series, to_cad, s = await _asset_series(symbol, type, period, interval, coingecko=False)
    if not series:
        return [], s

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    data = []  # A list with each entry being a dictionary in the form {"time": str, "price": float}
    for label, close, volume in zip(series.labels, series.closes, series.volumes):
        data.append({
            "time": label,
            # "Closing" price on that interval in the listing currency -> CAD -> the user's currency
            "price": close * to_cad * conversion,
            "volume": volume,  # traded units (None when Yahoo has none)
        })

    return data, s


async def get_coingecko_history(symbol: str, range: str, currency: str,
                                coin_id: str | None = None) -> tuple[list[dict], str]:
    """
    Chart prices from CoinGecko for coins Yahoo doesn't list, in the user's currency, plus the range they really
    cover: CoinGecko's free plan stops at 365 days, so a "5Y" request only covers "1Y". `coin_id` picks the exact
    coin when several share the ticker.
    """
    covered = "1Y" if range in ("5Y", "MAX") else range
    series = await _coingecko_series(symbol, covered, coin_id)
    if not series:
        return [], covered

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)
    return [{"time": label, "price": close * conversion} for label, close in zip(series.labels, series.closes)], covered


def calculate_timespans_for_portfolio_history(ranges: int):
    """
    Helper function to calculate the timespans that we loop through to calculate the portfolios historical values.
    Returns a list of timedelta objects.
    """
    now = datetime.now(timezone.utc)
    end = now  # end at now so the last point matches the portfolio value card
    start = now - timedelta(days=ranges)

    if ranges == 1:
        points = 289
        t = "1D"
    elif ranges == 7:
        points = 169
        t = "1W"
    elif ranges in (30, 31):
        points = 121
        t = "1M"
    else:
        points = 366
        # longer than a year ("All") reads weekly history instead of stopping at one year
        t = "1Y" if ranges <= 365 else "5Y" if ranges <= 1825 else "MAX"

    step = (end - start) / (points - 1)

    # the last point is exactly `end`: step * (points - 1) can round to a few microseconds short of it, which left a
    # trade logged in the same clock tick out of the "now" point
    timestamps = [start + (step * i) for i in range(points - 1)] + [end]

    return timestamps, t


async def get_portfolio_value_history(
        db: AsyncSession,
        user_id: UUID,
        ranges: int,
        currency: str
):
    """
    return the data needed to graph the portfolios historical values, as [{"time", "value", "invested"}].
    Each value is the quantity held then times the latest close known then; a holding with no price at a point is
    left out of that point. The last point ("now") is priced exactly like the portfolio value card.
    `invested` is the cost basis of the same holdings at that time (what was paid for what was still held, average
    cost method, prices as typed via price_in_currency so it doesn't drift with FX): it only moves with buys and
    sells, so the gap between the two lines is the unrealized gain. It ends on the holdings' "price paid" total.
    """
    timestamps, _ = calculate_timespans_for_portfolio_history(ranges)
    now = timestamps[-1]

    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.created_at <= naive_utc(now))
        .order_by(*LEDGER_ORDER)  # same order as get_holdings_at_time
    )
    transactions = result.scalars().all()  # read once and replayed below, instead of one query per point
    await end_read(db)  # the rest is pricing; the trades loaded above stay usable

    data = []
    positions: dict[str, dict] = {}  # api_id -> {"avg_price", "qty", "type"}, as get_holdings_at_time builds them
    if transactions:
        types = {str(t.api_id): str(t.asset_type) for t in transactions}
        coin_ids = {str(t.api_id): t.coin_id for t in transactions if t.coin_id}  # the newest one wins
        rates = await get_all_conversion_rates()
        conversion = get_conversion_factor(rates, currency)
        period, interval = lookup_spec(now - timestamps[0])  # one history per holding that reaches the first point

        async def load(api_id):
            """One holding's series and its rate to CAD (None, None when no source has it)."""
            try:
                series, to_cad, _ = await _asset_series(api_id, types[api_id], period, interval,
                                                        coin_id=coin_ids.get(api_id))
            except Exception:  # price source down with nothing cached: chart it without this holding
                series, to_cad = None, None
            return api_id, series, to_cad

        histories = {api_id: (series, to_cad) for api_id, series, to_cad in
                     await asyncio.gather(*[load(api_id) for api_id in types])}

        i = 0
        for ts in timestamps[:-1]:
            while i < len(transactions) and naive_utc(transactions[i].created_at) <= naive_utc(ts):
                apply_trade(positions, transactions[i], currency, conversion)
                i += 1

            curr_total = 0.0
            invested = 0.0
            for api_id, position in positions.items():  # fully sold positions are already gone
                series, to_cad = histories[api_id]
                close = series.close_at(ts) if series else None
                if close is None:  # no price then: left out of both lines, so they cover the same holdings
                    continue
                curr_total += float(position["qty"]) * close * to_cad * conversion
                invested += float(position["avg_price"]) * float(position["qty"])
            data.append({"time": ts.isoformat(), "value": curr_total, "invested": invested})

        for t in transactions[i:]:  # the rest, up to now, for the last point
            apply_trade(positions, t, currency, conversion)
    else:
        data = [{"time": ts.isoformat(), "value": 0.0, "invested": 0.0} for ts in timestamps[:-1]]

    # same holdings and prices as the dashboard's value card, so the chart ends on the card's number
    final = await get_position_values_at(db, user_id, now, currency) if transactions else {}
    data.append({
        "time": now.isoformat(),
        "value": sum(v for v in final.values() if v is not None),
        "invested": sum(float(p["avg_price"]) * float(p["qty"]) for api_id, p in positions.items()
                        if final.get(api_id) is not None),
    })

    return data
