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
