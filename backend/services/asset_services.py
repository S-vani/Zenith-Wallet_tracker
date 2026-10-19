import asyncio
import math
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import httpx
import yfinance as yf
from fastapi import HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models.assets import Transaction
from backend.schemas.assets import CreateTransaction
import logging
import time

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
log = logging.getLogger("uvicorn.error")

FX_CACHE_SECONDS = 3600  # open.er-api only updates once a day and asks callers not to poll it often
FX_RETRY_SECONDS = 300  # after a failed refresh the last good rates are served, and the api is retried this often

_symbol_currency_cache: dict[str, str | None] = {}
_rates_cache: dict = {}
_rates_cache_time: float = 0
_rates_retry_at: float = 0

# Yahoo ticker suffix -> listing currency, used when Yahoo doesn't say. No suffix means a US listing.
_SUFFIX_CURRENCY = {
    "TO": "CAD", "V": "CAD", "CN": "CAD", "NE": "CAD",
    "L": "GBp",  # London prices are quoted in pence
    "PA": "EUR", "DE": "EUR", "F": "EUR", "AS": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR", "LS": "EUR",
    "VI": "EUR", "HE": "EUR", "IR": "EUR",
    "SW": "CHF", "T": "JPY", "HK": "HKD", "AX": "AUD", "ST": "SEK", "OL": "NOK", "CO": "DKK",
}


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
        return _symbol_currency_cache[symbol]

    try:
        ticker = yf.Ticker(symbol)
        info = await asyncio.to_thread(lambda: ticker.info) or {}
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
    return currency


async def get_all_conversion_rates() -> dict:
    """
    Exchange rates, cached for an hour. If a refresh fails the last good rates are kept and served (retried every
    few minutes) instead of failing every money page; only with no rates at all is it a 503.
    """
    global _rates_cache, _rates_cache_time, _rates_retry_at

    now = time.time()
    if _rates_cache and ((now - _rates_cache_time) < FX_CACHE_SECONDS or now < _rates_retry_at):
        return _rates_cache

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
        log.error("Exchange rates are unavailable and none are cached: %s", exc)
        raise HTTPException(status_code=503,
                            detail="Exchange rates are temporarily unavailable. Please try again in a few minutes.")

    _rates_cache = fresh
    _rates_cache_time = now
    _rates_retry_at = 0

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


async def get_holdings_from_symbol(db: AsyncSession, user_id: UUID, symbol: str):
    """
    Return a list of Transactions objects of that specific symbol
    """
    result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.symbol == symbol
        )
    )

    return result.scalars().all()


async def get_curr_holdings_prices(holdings: dict[str, dict[str, float | str]], currency: str):
    """
    Return a dictionary in the form {api_id: curr_price}, with None for a holding no source has a price for
    """
    assets = {str(api_id): str(data["type"]) for api_id, data in holdings.items()}
    return await get_prices_at(assets, datetime.now(timezone.utc), currency)


def _naive_utc(value: datetime) -> datetime:
    """Transactions are stored as naive UTC, so compare against naive UTC."""
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


async def get_total_realized_profit(db: AsyncSession, user_id: UUID, currency: str, exclude=()):
    """
    Query the database with all the sell transactions and add up all the profit parameters in those sell transactions.
    `exclude` lists api_ids to leave out (holdings without a price are left out of the return maths entirely).
    """
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    query = select(func.coalesce(func.sum(Transaction.profit), 0.0)).where(
        Transaction.user_id == user_id,
        Transaction.action == "SELL"
    )
    if exclude:
        query = query.where(Transaction.api_id.notin_(list(exclude)))

    result = await db.execute(query)
    return float(result.scalar_one()) * conversion


async def get_cash_flow_between(
        db: AsyncSession,
        user_id: UUID,
        start: datetime,
        end: datetime,
        currency: str,
        exclude=()
):
    """
    Meant to calculate cash flow into the account, to be more specific imagine with 1 week ago someone portfolio value is 1000$,
    and now its 2000$, but they did not actually profit 1000$ but rather profited 100$ and then deposited another 900$, this function is
    meant to calculate that 900$ cash flow into the account so it's not accounted for in the profit
    """
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    query = select(
        func.coalesce(  # if there's no rows with these props return 0.0 instead of null
            func.sum(
                (Transaction.price_of_one * Transaction.quantity) *
                case(
                    # if the transaction is buy then we multiply the transactions value by 1, if its sell multiply by -1 then sum it together
                    (Transaction.action == "BUY", 1),
                    else_=-1
                )
            ),
            0.0
        )
    ).where(
        Transaction.user_id == user_id,
        Transaction.created_at > _naive_utc(start),
        Transaction.created_at <= _naive_utc(end)
    )
    if exclude:
        query = query.where(Transaction.api_id.notin_(list(exclude)))

    result = await db.execute(query)
    return float(result.scalar_one()) * conversion  # return 1 scalar float value


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
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    query = select(func.coalesce(func.sum(Transaction.price_of_one * Transaction.quantity), 0.0)).where(
        Transaction.user_id == user_id,
        Transaction.action == "BUY",
        Transaction.created_at <= _naive_utc(end)
    )
    if start is not None:
        query = query.where(Transaction.created_at > _naive_utc(start))
    if exclude:
        query = query.where(Transaction.api_id.notin_(list(exclude)))

    result = await db.execute(query)
    return float(result.scalar_one()) * conversion


async def get_holdings_at_time(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime,
        currency: str
):
    """
    Return a dictionary mapping an api id to another dictionary with average price, quantity  and type meant to be a dictionary
    of all the holdings at a certain time
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
        .order_by(Transaction.created_at.asc())
    )

    transactions = result.scalars().all()  # all transactions from timestamp and before

    for t in transactions:
        api_id = str(t.api_id)

        if str(t.action) == "BUY":
            if api_id in holdings_at_timestamp:  # if the api_id is already in the dictionary recalculate its values
                holdings_at_timestamp[api_id]["avg_price"] = get_holdings_helper(
                    holdings_at_timestamp[api_id]["avg_price"],
                    (float(t.price_of_one) * conversion),
                    holdings_at_timestamp[api_id]["quantity"],
                    t.quantity
                )
                holdings_at_timestamp[api_id]["quantity"] += float(t.quantity)
            else:
                holdings_at_timestamp[api_id] = {
                    "avg_price": float(t.price_of_one) * conversion,
                    "quantity": float(t.quantity),
                    "type": t.asset_type
                }

        else:  # SELL
            if api_id in holdings_at_timestamp:
                holdings_at_timestamp[api_id]["quantity"] -= float(t.quantity)

                if holdings_at_timestamp[api_id]["quantity"] <= 1e-9:  # fully sold, so it's no longer a holding
                    del holdings_at_timestamp[api_id]

    return holdings_at_timestamp


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
    prices = await get_curr_holdings_prices(result, currency)

    curr_holdings_list = []

    for key, value in result.items():
        price = prices.get(key)

        curr_holdings_list.append({
            "symbol": key,
            "price_paid": float(value["avg_price"]) * float(value["quantity"]),
            "quantity": float(value["quantity"]),
            "type": value["type"],
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


async def _refresh_usd_cross_rates() -> None:
    """Units of every currency per 1 USD, refreshed hourly; a failed refresh keeps the old table (retried later)."""
    now = time.time()
    fresh = _usd_rates_cache["rates"] and now - _usd_rates_cache["time"] < FX_CACHE_SECONDS
    if fresh or now < _usd_rates_cache.get("retry_at", 0.0):
        return
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


@dataclass
class PriceSeries:
    labels: list[str] = field(default_factory=list)  # bar times as the source gave them (for the charts)
    times: list[datetime] = field(default_factory=list)
    known: list[datetime] = field(default_factory=list)  # when each close was known (see above)
    closes: list[float] = field(default_factory=list)  # in the source's own currency
    volumes: list[float | None] = field(default_factory=list)

    def close_at(self, at: datetime) -> float | None:
        """The latest close known at `at`, or None if the history doesn't reach back that far."""
        i = bisect_right(self.known, at + LIVE_SLACK) - 1
        return self.closes[i] if i >= 0 else None


def lookup_spec(age: timedelta) -> tuple[str, str]:
    for max_age, period, interval in LOOKUP_SPECS:
        if age <= max_age:
            return period, interval
    return "max", "1wk"


def _as_utc(value) -> datetime:
    value = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _series_from_history(hist, bar: timedelta, fetched: datetime) -> PriceSeries | None:
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
    """
    now = time.time()
    entry = _series_cache.get(key)
    if entry and now - entry["checked"] < entry["ttl"]:
        if entry.get("error"):
            raise entry["error"]
        return entry["series"]

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
        requested_at = datetime.now(timezone.utc)
        hist = await asyncio.to_thread(yf.Ticker(ticker).history, period=period, interval=interval)
        return _series_from_history(hist, BAR_LENGTH[interval], requested_at)

    return await _cached_series(("yahoo", ticker.upper(), period, interval), SERIES_CACHE_SECONDS[interval], fetch)


async def _coingecko_series(symbol: str, range_code: str) -> PriceSeries | None:
    """
    CoinGecko prices in CAD for coins Yahoo doesn't list (e.g. PEPE), same fallback as the /prices/history chart.
    Its demo key is rate limited, so answers (empty ones too, briefly) are cached.
    """
    range_code = "1Y" if range_code in ("5Y", "MAX") else range_code  # its free plan stops at 365 days either way

    async def fetch():
        from backend.analyst import data as market_data  # imported here: analyst.data imports this module
        points = await market_data.coingecko_chart(symbol, range_code, "CAD")
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

    return await _cached_series(("coingecko", symbol.lower(), range_code),
                                COINGECKO_CACHE_SECONDS.get(range_code, 1800), fetch,
                                empty_ttl=COINGECKO_EMPTY_SECONDS)


async def _asset_series(api_id: str, asset_type: str, period: str, interval: str, coingecko: bool = True):
    """
    Price history of one asset as (series, to_cad, source), where close * to_cad is the price in CAD, or
    (None, None, source) when no source has prices. Crypto tries Yahoo's SYMBOL-CAD pair, then SYMBOL-USD, then
    CoinGecko, in that order everywhere, so the value card, holdings and charts all agree.
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
                series = await _coingecko_series(base, COINGECKO_RANGE.get(period, "1Y"))
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


async def get_prices_at(assets: dict[str, str], timestamp: datetime, currency: str) -> dict[str, float | None]:
    """
    Price of each asset ({api_id: "stock" | "crypto"}) at `timestamp` in the user's currency, as {api_id: price}.
    None means no source has a price for it then: callers leave it out instead of counting it as worth 0.
    """
    if not assets:
        return {}

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)
    period, interval = lookup_spec(datetime.now(timezone.utc) - timestamp)

    async def fetch_one(api_id, asset_type):
        try:
            series, to_cad, _ = await _asset_series(api_id, asset_type, period, interval)
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
        hist = await asyncio.to_thread(yf.Ticker(symbol).history, period="5d", interval="1d")
        closes = hist["Close"].dropna() if not hist.empty else []
        if len(closes) == 0:
            return symbol, None
        close = float(closes.iloc[-1])  # today's live price while the market is open
        previous = float(closes.iloc[-2]) if len(closes) > 1 else close
        return symbol, {"close": close, "previous_close": previous}

    async def safe_fetch(symbol):
        try:
            return await fetch_one(symbol)
        except Exception:  # one bad ticker shouldn't empty the whole search
            return symbol, None

    results = await asyncio.gather(*[safe_fetch(symbol) for symbol in symbols])
    return {symbol: quote for symbol, quote in results if quote is not None}


async def calculate_profit_for_one_transaction(db: AsyncSession, user_id: UUID, data: CreateTransaction, currency: str):
    """
    Calculate the amount a user profited from a certain sell transaction
    """
    result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.symbol == data.symbol
        )
        .order_by(Transaction.created_at.asc())
    )

    transactions = result.scalars().all()

    quantity = 0.0
    avg_cost = 0.0

    for t in transactions:
        if str(t.action) == "BUY":
            qty = float(t.quantity)
            price = float(t.price_of_one)

            new_qty = quantity + qty

            avg_cost = (  # recalculate the average price paid for that symbol
                (quantity * avg_cost + qty * price) / new_qty
                if new_qty > 0 else 0.0
            )

            quantity = new_qty

        elif str(t.action) == "SELL":
            qty = float(t.quantity)
            quantity -= qty

    sell_qty = float(data.quantity)
    sell_price = float(data.price_of_one)

    profit = (sell_price - avg_cost) * sell_qty

    return profit


def create_holding_filter(
        user_id: UUID,
        symbol: str | None = None,
        action: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None
):
    """
    create a query for the backend to use to query the database
    """
    query = select(Transaction).where(Transaction.user_id == user_id)

    # transactions are stored in UTC without a timezone, so convert filter dates the same way
    def to_utc(value: datetime) -> datetime:
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value

    start_date = to_utc(start_date) if start_date else None
    end_date = to_utc(end_date) if end_date else None

    if symbol:
        # escape LIKE wildcards so typing "_" or "%" doesn't match everything
        escaped = symbol.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Transaction.symbol.ilike(f"{escaped}%", escape="\\"))

    if action:
        query = query.where(Transaction.action == action)

    if start_date:
        query = query.where(Transaction.created_at >= start_date)

    if end_date:  # Will always be true
        query = query.where(Transaction.created_at <= end_date)
    else:
        query = query.where(Transaction.created_at <= datetime.now(timezone.utc))

    return query


async def rebuild_symbol_ledger(db: AsyncSession, user_id: UUID, symbol: str) -> bool:
    """
    Replay every transaction of one symbol in date order, recompute the profit of each sell from the average cost
    at that moment, and return False if the history ever sells more than was owned (e.g. after an edit or delete).
    """
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.symbol == symbol)
        .order_by(Transaction.created_at.asc())
    )

    quantity = Decimal(0)
    avg_cost = Decimal(0)
    for t in result.scalars().all():
        qty = Decimal(str(t.quantity))
        price = Decimal(str(t.price_of_one))
        if str(t.action) == "BUY":
            avg_cost = (quantity * avg_cost + qty * price) / (quantity + qty)
            quantity += qty
        else:
            if qty > quantity:
                return False
            t.profit = (price - avg_cost) * qty
            quantity -= qty

    return True


async def current_quantity(db: AsyncSession, user_id: UUID, symbol: str) -> Decimal:
    """
    Calculate how much of a specific symbol a user has, for example how much BTC is currently in their account.
    Quantities are summed as Decimals (how the database stores them) so 0.3 - 0.1 is exactly 0.2
    """
    lst = await get_holdings_from_symbol(db, user_id, symbol)
    selling = Decimal(0)
    buying = Decimal(0)
    for trans in lst:
        if str(trans.action) == "SELL":
            selling += trans.quantity
        else:
            buying += trans.quantity

    return buying - selling


def turn_list_to_dict(lst, conversion: float = 1.0):
    """
    loop through a list of transactions and turn it into a list of dictionaries that are easier to use,
    with prices converted from CAD into the users currency
    """
    transactions_data = []
    for trans in lst:
        transactions_data.append(
            {
                "id": str(trans.id),
                "user_id": str(trans.user_id),
                "action": str(trans.action),
                "profit": float(trans.profit or 0) * conversion,
                "asset_type": str(trans.asset_type),
                "symbol": str(trans.symbol),
                "api_ids": str(trans.api_id),
                "price_of_one": float(trans.price_of_one) * conversion,
                "quantity": float(trans.quantity),
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
    prices = await get_prices_at({api_id: str(data["type"]) for api_id, data in holdings.items()}, timestamp, currency)

    return {
        api_id: float(prices[api_id]) * float(data["quantity"]) if prices.get(api_id) is not None else None
        for api_id, data in holdings.items()
    }


async def get_portfolio_value_at(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime,
        currency: str
):
    """
    Get the portfolios value at a specific time in the form of a float. Holdings with no price are left out.
    """
    values = await get_position_values_at(db, user_id, timestamp, currency)
    return sum(value for value in values.values() if value is not None)


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


async def get_coingecko_history(symbol: str, range: str, currency: str) -> tuple[list[dict], str]:
    """
    Chart prices from CoinGecko for coins Yahoo doesn't list, in the user's currency, plus the range they really
    cover: CoinGecko's free plan stops at 365 days, so a "5Y" request only covers "1Y".
    """
    covered = "1Y" if range in ("5Y", "MAX") else range
    series = await _coingecko_series(symbol, covered)
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

    timestamps = [start + (step * i) for i in range(points)]

    return timestamps, t


async def get_portfolio_value_history(
        db: AsyncSession,
        user_id: UUID,
        ranges: int,
        currency: str
):
    """
    return the data needed to graph the portfolios historical values.
    Each point is the quantity held then times the latest close known then; a holding with no price at a point is
    left out of that point. The last point ("now") is priced exactly like the portfolio value card.
    """
    timestamps, _ = calculate_timespans_for_portfolio_history(ranges)
    now = timestamps[-1]

    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.created_at <= _naive_utc(now))
        .order_by(Transaction.created_at.asc())
    )
    transactions = result.scalars().all()  # read once and replayed below, instead of one query per point

    data = []
    if transactions:
        types = {str(t.api_id): str(t.asset_type) for t in transactions}
        rates = await get_all_conversion_rates()
        conversion = get_conversion_factor(rates, currency)
        period, interval = lookup_spec(now - timestamps[0])  # one history per holding that reaches the first point

        async def load(api_id):
            try:
                series, to_cad, _ = await _asset_series(api_id, types[api_id], period, interval)
            except Exception:  # price source down with nothing cached: chart it without this holding
                series, to_cad = None, None
            return api_id, series, to_cad

        histories = {api_id: (series, to_cad) for api_id, series, to_cad in
                     await asyncio.gather(*[load(api_id) for api_id in types])}

        quantities: dict[str, Decimal] = {}
        i = 0
        for ts in timestamps[:-1]:
            while i < len(transactions) and _naive_utc(transactions[i].created_at) <= _naive_utc(ts):
                t = transactions[i]
                qty = Decimal(str(t.quantity))
                quantities[str(t.api_id)] = quantities.get(str(t.api_id), Decimal(0)) + (
                    qty if str(t.action) == "BUY" else -qty)
                i += 1

            curr_total = 0.0
            for api_id, qty in quantities.items():
                series, to_cad = histories[api_id]
                if qty <= Decimal("1e-9") or not series:  # fully sold, or no price data for this holding
                    continue
                close = series.close_at(ts)
                if close is not None:
                    curr_total += float(qty) * close * to_cad * conversion
            data.append({"time": ts.isoformat(), "value": curr_total})
    else:
        data = [{"time": ts.isoformat(), "value": 0.0} for ts in timestamps[:-1]]

    # same holdings and prices as the dashboard's value card, so the chart ends on the card's number
    final = await get_position_values_at(db, user_id, now, currency) if transactions else {}
    data.append({"time": now.isoformat(), "value": sum(v for v in final.values() if v is not None)})

    return data
