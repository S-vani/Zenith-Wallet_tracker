import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import httpx
import yfinance as yf
from sqlalchemy import select, func, case
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
import numpy as np
from typing import Literal

from backend.db_models.assets import Transaction
from backend.schemas.assets import CreateTransaction
import logging
import time

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_symbol_currency_cache: dict[str, str] = {}
_rates_cache: dict = {}
_rates_cache_time: float = 0


async def get_ticker_currency(symbol: str) -> str:
    """
    A function used to cache the ticker currency so it is only called once since ticker.info is expensive to call many times.
    """
    if symbol in _symbol_currency_cache:  # If we already have this symbol cached
        return _symbol_currency_cache[symbol]

    try:
        ticker = yf.Ticker(symbol)
        info = await asyncio.to_thread(lambda: ticker.info)
        currency = info.get("currency") or "USD"  # not uppercased: "GBp" (pence) and "GBP" (pounds) differ 100x
    except Exception:
        currency = "USD"

    _symbol_currency_cache[symbol] = currency
    return currency


async def get_all_conversion_rates() -> dict:
    """
    Cache conversion rates with TTL of 60 seconds
    """
    global _rates_cache, _rates_cache_time

    now = time.time()
    if _rates_cache and (now - _rates_cache_time) < 60:
        return _rates_cache

    usd_to_cad, usd, eur = await asyncio.gather(
        get_usd_to_cad(),
        get_usd(),
        get_eur()
    )

    _rates_cache = {
        "usd_to_cad": usd_to_cad,
        "usd": usd,
        "eur": eur
    }
    _rates_cache_time = now

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
    Return a list of dictionaries in the form {"api_id": curr_price}
    """
    crypto = []
    stocks = []

    for ids in holdings:
        if str(holdings[ids]["type"]) == "crypto":
            crypto.append(str(ids))  # keep the stored id as the key, get_crypto_prices_at uppercases it for yahoo
        elif str(holdings[ids]["type"]) == "stock":
            stocks.append(str(ids))

    # The 2 variables below are dicts like {api_id: curr_price}
    crypto_prices = await get_crypto_prices_at(crypto, datetime.now(timezone.utc), currency)
    stock_prices = await get_stock_prices_at(stocks, datetime.now(timezone.utc), currency)

    return crypto_prices | stock_prices


async def get_total_realized_profit(db: AsyncSession, user_id: UUID, currency: str):
    """
    Query the database with all the sell transactions and add up all the profit parameters in those sell transactions
    """
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.profit), 0.0))
        .where(
            Transaction.user_id == user_id,
            Transaction.action == "SELL"
        )
    )

    return float(result.scalar_one()) * conversion


async def get_cash_flow_between(
        db: AsyncSession,
        user_id: UUID,
        start: datetime,
        end: datetime,
        currency: str
):
    """
    Meant to calculate cash flow into the account, to be more specific imagine with 1 week ago someone portfolio value is 1000$,
    and now its 2000$, but they did not actually profit 1000$ but rather profited 100$ and then deposited another 900$, this function is
    meant to calculate that 900$ cash flow into the account so it's not accounted for in the profit
    """
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    result = await db.execute(
        select(
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
            Transaction.created_at > start,
            Transaction.created_at <= end
        )
    )

    return float(result.scalar_one()) * conversion  # return 1 scalar float value


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
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
    )

    transactions = result.scalars().all()  # all transactions from timestamp and before

    for t in transactions:
        api_id = str(t.api_id)
        qty = as_quantity(t.quantity)  # exact sums, so "Sell all" offers exactly what is owned

        if str(t.action) == "BUY":
            price = price_in_currency(t, currency, conversion)
            if api_id in holdings_at_timestamp:  # if the api_id is already in the dictionary recalculate its values
                holding = holdings_at_timestamp[api_id]
                holding["avg_price"] = get_holdings_helper(holding["avg_price"], price, holding["qty"], qty)
                holding["qty"] += qty
            else:
                holdings_at_timestamp[api_id] = {"avg_price": price, "qty": qty, "type": t.asset_type}

        else:  # SELL
            if api_id in holdings_at_timestamp:
                holding = holdings_at_timestamp[api_id]
                if qty >= holding["qty"] - sell_tolerance(holding["qty"]):
                    del holdings_at_timestamp[api_id]  # fully sold, so it's no longer a holding
                else:
                    holding["qty"] -= qty

    return {
        api_id: {"avg_price": h["avg_price"], "quantity": float(h["qty"]), "type": h["type"]}
        for api_id, h in holdings_at_timestamp.items()
    }


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
    now = datetime.now(timezone.utc)

    stocks = []
    crypto = []

    for key, value in result.items():
        if value["type"] == "stock":
            stocks.append(key)
        else:
            crypto.append(key)

    stock_prices = await get_stock_prices_at(stocks, now, currency)
    crypto_prices = await get_crypto_prices_at(crypto, now, currency)

    curr_holdings_list = []

    for key, value in result.items():
        prices = stock_prices if value["type"] == "stock" else crypto_prices
        current_price = float(prices.get(key) or 0.0)

        curr_holdings_list.append({
            "symbol": key,
            "price_paid": float(value["avg_price"]) * float(value["quantity"]),
            "quantity": float(value["quantity"]),
            "type": value["type"],
            "current_price": current_price * float(value["quantity"])
        })

    return curr_holdings_list


def get_holdings_helper(curr_avg: float, new_price: float, curr_quantity: float, new_quantity: float):
    """
    Calculate the average price paid for a certain holding
    """
    total_cost = (float(curr_avg) * float(curr_quantity)) + (float(new_price) * float(new_quantity))
    return total_cost / float((float(curr_quantity) + float(new_quantity)))


_usd_rates_cache: dict = {"time": 0.0, "rates": {}}


async def get_native_to_cad_factor(currency: str) -> float:
    """
    Multiplier that turns a price quoted in `currency` (a stock's listing currency from Yahoo) into CAD.
    Handles any currency (EUR, GBP, JPY, ...) via USD cross rates; London prices quoted in pence ("GBp") are / 100.
    """
    if currency in ("GBp", "GBX", "GBx"):
        return (await get_native_to_cad_factor("GBP")) / 100
    code = (currency or "USD").upper()
    if code == "CAD":
        return 1.0
    rates = await get_all_conversion_rates()
    if code == "USD":
        return float(rates["usd_to_cad"])

    # other currencies: CAD per 1 unit = (CAD per USD) / (units per USD), cached for an hour
    if not _usd_rates_cache["rates"] or time.time() - _usd_rates_cache["time"] > 3600:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get("https://open.er-api.com/v6/latest/USD")
            _usd_rates_cache["rates"] = res.json().get("rates", {})
            _usd_rates_cache["time"] = time.time()
        except Exception:
            pass
    per_usd = _usd_rates_cache["rates"].get(code)
    if not per_usd:
        logging.getLogger("uvicorn.error").warning("No exchange rate for %s, treating it as USD", code)
        return float(rates["usd_to_cad"])
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


async def get_crypto_prices_at(api_ids: list[str], timestamp: datetime, currency: str):
    """
    Functions that takes in a list of api_ids of cryptos with a timestamp and currency and returns a dictionary of the form,
    {api_id: price}
    """
    if not api_ids:
        return {}

    async def fetch_one(api_id):
        ticker_symbol = f"{api_id.upper()}-CAD"  # crypto form for yahoo finance
        ticker = yf.Ticker(ticker_symbol)
        now = datetime.now(timezone.utc)

        rates = await get_all_conversion_rates()
        conversion = get_conversion_factor(rates, currency)

        # Create the start and end windows around the timestamp given
        start = timestamp - timedelta(minutes=5)
        end = min(timestamp + timedelta(minutes=5), now)

        hist = await asyncio.to_thread(ticker.history, start=start, end=end,
                                       interval="1m")  # fetch historical candle data from yf in 1 minute intervals

        if not hist.empty:
            closest_row = hist.iloc[np.abs(hist.index.tz_convert(
                "UTC") - timestamp).argmin()]  # fetches row closest to our desired timestamp since hist will return a ton of data
            price = float(closest_row["Close"])  # get closing price of that row
            return api_id, price * conversion

        # FALLBACK SECTION - IF NO MINUTE DATA EXISTS
        fallback_start = timestamp - timedelta(days=5)
        fallback_end = min(timestamp + timedelta(days=1), now)
        hist_fallback = await asyncio.to_thread(ticker.history, start=fallback_start, end=fallback_end,
                                                interval="1d")

        if hist_fallback.empty:
            return api_id, 0.0

        hist_before = hist_fallback[
            hist_fallback.index.tz_convert("UTC") <= timestamp]  # only get dates before our target timestamp

        if hist_before.empty:
            return api_id, 0.0

        price = float(hist_before.iloc[-1]["Close"])  # closest daily close price
        return api_id, price * conversion

    async def safe_fetch(api_id):
        try:
            return await fetch_one(api_id)
        except Exception:  # unknown coin: count it as 0 instead of failing every page
            return api_id, 0.0

    results = await asyncio.gather(
        *[safe_fetch(api_id) for api_id in api_ids])  # create coroutine of tasks in a list then run them concurrently
    return dict(results)  # convert list of tuples to dicts


async def get_stock_prices_at(symbols: list[str], timestamp: datetime, currency: str):
    """
    Functions that takes in a list of symbols of stocks with a timestamp and currency and returns a dictionary of the form,
    {symbol: price}
    """
    if not symbols:
        return {}

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    async def fetch_one(symbol):
        ticker_currency = await get_ticker_currency(symbol)  # cached after first call
        to_cad = await get_native_to_cad_factor(ticker_currency)  # listing currency -> CAD (1.0 for CAD listings)

        ticker = yf.Ticker(symbol)
        now = datetime.now(timezone.utc)

        # get the start and end windows around the timestamp
        narrow_start = timestamp - timedelta(minutes=5)
        narrow_end = min(timestamp + timedelta(minutes=5), now)

        hist = await asyncio.to_thread(ticker.history, start=narrow_start, end=narrow_end,
                                       interval="1m")  # 1 minute interval data with time mapping to price

        if not hist.empty:
            closest_row = hist.iloc[np.abs(hist.index.tz_convert(
                "UTC") - timestamp).argmin()]  # fetch the closest row out of all the date returned
            price = float(closest_row["Close"]) * to_cad
            return symbol, price * conversion

        # FALLBACK SECTION - IF NO MINUTE DATA EXISTS
        fallback_start = timestamp - timedelta(days=5)
        fallback_end = min(timestamp + timedelta(days=1), now)
        hist_fallback = await asyncio.to_thread(ticker.history, start=fallback_start, end=fallback_end,
                                                interval="1d")

        if hist_fallback.empty:
            return symbol, 0.0

        hist_before = hist_fallback[hist_fallback.index.tz_convert("UTC") <= timestamp]

        if hist_before.empty:
            return symbol, 0.0

        price = float(hist_before.iloc[-1]["Close"]) * to_cad
        return symbol, price * conversion

    async def safe_fetch(symbol):
        try:
            return await fetch_one(symbol)
        except Exception:  # unknown / delisted ticker: count it as 0 instead of failing every page
            return symbol, 0.0

    results = await asyncio.gather(*[safe_fetch(symbol) for symbol in symbols])
    return dict(results)


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
    Calculate the amount (in CAD) a user would profit from selling `data` (price in CAD) after their logged trades
    of that symbol, from the average cost at that point (or at data.created_at for a backdated sell).
    The routes use rebuild_symbol_ledger, which also handles prices typed in USD/EUR; this is the plain CAD version.
    """
    query = select(Transaction).where(Transaction.user_id == user_id, Transaction.symbol == data.symbol)
    if data.created_at is not None:
        query = query.where(Transaction.created_at <= data.created_at)
    result = await db.execute(query.order_by(Transaction.created_at.asc(), Transaction.id.asc()))

    replay = _replay_ledger(result.scalars().all(), set_profits=False)
    return float((Decimal(str(data.price_of_one)) - replay.avg_cad) * as_quantity(data.quantity))


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


class _Replay:
    """Running state while replaying one symbol's trades in date order (average cost method)."""

    def __init__(self):
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
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
    )

    return not _replay_ledger(result.scalars().all()).oversold


async def current_quantity(db: AsyncSession, user_id: UUID, symbol: str) -> Decimal:
    """
    Calculate how much of a specific symbol a user has, for example how much BTC is currently in their account.
    Quantities are summed as exact Decimals (see as_quantity) so 0.3 - 0.1 is exactly 0.2
    """
    lst = await get_holdings_from_symbol(db, user_id, symbol)
    selling = Decimal(0)
    buying = Decimal(0)
    for trans in lst:
        if str(trans.action) == "SELL":
            selling += as_quantity(trans.quantity)
        else:
            buying += as_quantity(trans.quantity)

    return buying - selling


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
                "price_of_one": price_in_currency(trans, currency, conversion),
                "quantity": float(as_quantity(trans.quantity)),
                "created_at": trans.created_at.replace(tzinfo=timezone.utc).isoformat()
            }
        )
    return transactions_data


async def get_portfolio_value_at(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime,
        currency: str
):
    """
    Get the portfolios value at a specific time in the form of a float
    """
    holdings = await get_holdings_at_time(db, user_id, timestamp, currency)

    if not holdings:
        return 0.0

    crypto = []
    stocks = []

    for api_id, data in holdings.items():
        if data["type"] == "crypto":
            crypto.append(api_id)
        else:
            stocks.append(api_id)

    crypto_prices = await get_crypto_prices_at(crypto, timestamp, currency)
    stock_prices = await get_stock_prices_at(stocks, timestamp, currency)

    prices = crypto_prices | stock_prices

    total_value = 0.0

    for api_id, data in holdings.items():
        price = float(prices.get(api_id, 0.0))
        quantity = float(data["quantity"])
        total_value += price * quantity

    return total_value


async def get_history_of_prices(
        symbol: str,
        type: str,
        range: str,
        currency: str
):
    """
    Get historical prices of that specific symbol/holding on specific ranges, and turn it into a tuple returning the
    symbol and a list of prices.
    """
    now = datetime.now(timezone.utc)

    if type == "crypto":
        s = f"{symbol}-USD"
    else:
        s = symbol

    # Translate it into a form that yahoo finance can understand
    if range == "1D":
        period = "2d"
        interval = "5m"
    elif range == "1W":
        period = "7d"
        interval = "60m"
    elif range == "1M":
        period = "1mo"
        interval = "1d"
    elif range == "1Y":
        period = "1y"
        interval = "1d"
    else:
        period = "5y"
        interval = "1wk"

    ticker = yf.Ticker(s)  # create object representing the specific stock or crypto

    currency_1 = "USD" if type == "crypto" else await get_ticker_currency(s)
    to_cad = await get_native_to_cad_factor(currency_1)
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, currency)

    hist = await asyncio.to_thread(
        ticker.history,
        period=period,
        interval=interval
    )  # fetch its historical prices as a dataframe(SQL) table over a time period with specific intervals

    if hist.empty:
        return [], s

    data = []  # A list with each entry being a dictionary in the form {"time": str, "price": float}

    for index, row in hist.iterrows():  # iterate row by row with index being the specific row label (date)
        price = float(row["Close"])
        if price != price or price <= 0:  # Yahoo sometimes returns today's row with a missing (NaN) close
            continue

        price *= to_cad  # listing currency -> CAD, then CAD -> the user's currency below

        volume = row.get("Volume") if hasattr(row, "get") else None
        data.append({
            "time": str(index),
            "price": price * conversion,
            # "Closing" price on that interval, for example if time is 10:15:00, then it fetches price at 10:15:59
            "volume": float(volume) if volume is not None and volume == volume else None,  # traded units (NaN -> None)
        })

    return data, s


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
        t = "1Y"

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
    """
    timestamps, t = calculate_timespans_for_portfolio_history(ranges)
    data = []

    cached_histories = {}  # Cache the historical prices for each holding to not have to fetch it everytime

    for time in timestamps:

        curr_total = 0.0

        holdings = await get_holdings_at_time(
            db,
            user_id,
            time,
            currency
        )  # Dictionary of holdings with api_id mapping to another dictionary with information needed

        for symbol, holding in holdings.items():

            if symbol not in cached_histories:

                try:
                    history, _ = await get_history_of_prices(
                        symbol,
                        holding["type"],
                        t,
                        currency
                    )  # List of prices mapping {api_id: price}
                except Exception:  # bad ticker, chart it as 0 instead of failing
                    history = []

                parsed = []

                for item in history:
                    parsed.append({
                        "time": datetime.fromisoformat(item["time"]),
                        "price": float(item["price"])
                    })

                cached_histories[symbol] = parsed  # store the information into our cached history

            if not cached_histories[symbol]:  # no price data for this holding
                continue

            # find closest candle
            closest = min(
                cached_histories[symbol],
                key=lambda x: abs(x["time"] - time)
            )

            curr_total += float(holding["quantity"]) * float(
                closest["price"])  # total of the specific holding at a specific time

        data.append({
            "time": time.isoformat(),
            "value": curr_total
        })

    return data
