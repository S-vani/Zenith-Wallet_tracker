import asyncio
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


async def get_curr_holdings_prices(holdings: dict[str, dict[str, float | str]]):
    """
    Return a list of dictionaries in the form {"api_id": curr_price}
    """
    crypto = []
    stocks = []

    for ids in holdings:
        if str(holdings[ids]["type"]) == "crypto":
            crypto.append(str(ids).upper())  # .upper for yahoo finance
        elif str(holdings[ids]["type"]) == "stock":
            stocks.append(str(ids))

    # The 2 variables below are dicts like {api_id: curr_price}
    crypto_prices = await get_crypto_prices_at(crypto, datetime.now(timezone.utc))
    stock_prices = await get_stock_prices_at(stocks, datetime.now(timezone.utc))

    return crypto_prices | stock_prices


async def get_total_realized_profit(db: AsyncSession, user_id: UUID):
    """
    Query the database with all the sell transactions and add up all the profit parameters in those sell transactions
    """
    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.profit), 0.0))
        .where(
            Transaction.user_id == user_id,
            Transaction.action == "SELL"
        )
    )

    return float(result.scalar_one())


async def get_cash_flow_between(
        db: AsyncSession,
        user_id: UUID,
        start: datetime,
        end: datetime
):
    """
    Meant to calculate cash flow into the account, to be more specific imagine with 1 week ago someone portfolio value is 1000$,
    and now its 2000$, but they did not actually profit 1000$ but rather profited 100$ and then deposited another 900$, this function is
    meant to calculate that 900$ cash flow into the account so it's not accounted for in the profit
    """
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

    return float(result.scalar_one())  # return 1 scalar float value


async def get_holdings_at_time(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime
):
    """
    Return a dictionary mapping an api id to another dictionary with average price, quantity  and type meant to be a dictionary
    of all the holdings at a certain time
    """
    holdings_at_timestamp = {}

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
                    t.price_of_one,
                    holdings_at_timestamp[api_id]["quantity"],
                    t.quantity
                )
                holdings_at_timestamp[api_id]["quantity"] += t.quantity
            else:
                holdings_at_timestamp[api_id] = {
                    "avg_price": t.price_of_one,
                    "quantity": t.quantity,
                    "type": t.asset_type
                }

        else:  # SELL
            if api_id in holdings_at_timestamp:
                holdings_at_timestamp[api_id]["quantity"] -= t.quantity

    return holdings_at_timestamp


async def get_holdings_at_time_list(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime
):
    """
    Take the dictionary that get_holdings_at_time returns and turn it into a list to be more easily used by the frontend
    """
    result = await get_holdings_at_time(db, user_id, timestamp)
    now = datetime.now(timezone.utc)

    stocks = []
    crypto = []

    for key, value in result.items():
        if value["type"] == "stock":
            stocks.append(key)
        else:
            crypto.append(key)

    stock_prices = await get_stock_prices_at(stocks, now)
    crypto_prices = await get_crypto_prices_at(crypto, now)

    curr_holdings_list = []

    for key, value in result.items():
        prices = stock_prices if value["type"] == "stock" else crypto_prices
        current_price = float(prices[key])

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
    total_cost = (curr_avg * curr_quantity) + (new_price * new_quantity)
    return total_cost / (curr_quantity + new_quantity)


async def get_usd_to_cad():
    """
    use an api to get the current usd to cad value since the entire app will be only in cad
    """
    url = "https://open.er-api.com/v6/latest/USD"

    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()

    cad = data.get("rates", {}).get("CAD")

    return float(cad)

async def get_crypto_prices_at(api_ids: list[str], timestamp: datetime):
    if not api_ids:
        return {}

    async def fetch_one(api_id):
        ticker_symbol = f"{api_id.upper()}-CAD"
        ticker = yf.Ticker(ticker_symbol)
        now = datetime.now(timezone.utc)
        start = timestamp - timedelta(minutes=5)
        end = min(timestamp + timedelta(minutes=5), now)

        hist = ticker.history(start=start, end=end, interval="1m")
        if hist.empty:
            return api_id, None
        closest_row = hist.iloc[np.abs(hist.index - timestamp).argmin()]
        return api_id, float(closest_row["Close"])

    results = await asyncio.gather(*[fetch_one(api_id) for api_id in api_ids])
    return dict(results)

async def get_stock_prices_at(symbols: list[str], timestamp: datetime):
    if not symbols:
        return {}

    conversion = await get_usd_to_cad()

    async def fetch_one(symbol):
        ticker = yf.Ticker(symbol)
        now = datetime.now(timezone.utc)
        narrow_start = timestamp - timedelta(minutes=5)
        narrow_end = min(timestamp + timedelta(minutes=5), now)

        hist = ticker.history(start=narrow_start, end=narrow_end, interval="1m")
        if not hist.empty:
            closest_row = hist.iloc[np.abs(hist.index - timestamp).argmin()]
            price = float(closest_row["Close"])
        else:
            fallback_start = timestamp - timedelta(days=5)
            fallback_end = min(timestamp, now)
            hist_fallback = ticker.history(start=fallback_start, end=fallback_end, interval="1d")
            hist_before = hist_fallback[hist_fallback.index <= timestamp]
            price = float(hist_before.iloc[-1]["Close"])

        return symbol, price * conversion

    results = await asyncio.gather(*[fetch_one(symbol) for symbol in symbols])
    return dict(results)


async def calculate_profit_for_one_transaction(db: AsyncSession, user_id: UUID, data: CreateTransaction):
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

    if symbol:
        query = query.where(Transaction.symbol.ilike(f"{symbol}%"))

    if action:
        query = query.where(Transaction.action == action)

    if start_date:
        query = query.where(Transaction.created_at >= start_date)

    if end_date:  # Will always be true
        query = query.where(Transaction.created_at <= end_date)
    else:
        query = query.where(Transaction.created_at <= datetime.now(timezone.utc))

    return query


async def current_quantity(db: AsyncSession, user_id: UUID, symbol: str) -> float:
    """
    Calculate how much of a specific symbol a user has, for example how much BTC is currently in their account
    """
    lst = await get_holdings_from_symbol(db, user_id, symbol)
    selling = 0
    buying = 0
    for trans in lst:
        if str(trans.action) == "SELL":
            selling += trans.quantity
        else:
            buying += trans.quantity

    return buying - selling


def turn_list_to_dict(lst):
    """
    loop through a list of transactions and turn it into a list of dictionaries that are easier to use
    """
    transactions_data = []
    for trans in lst:
        transactions_data.append(
            {
                "id": str(trans.id),
                "user_id": str(trans.user_id),
                "action": str(trans.action),
                "profit": float(trans.profit),
                "asset_type": str(trans.asset_type),
                "symbol": str(trans.symbol),
                "api_ids": str(trans.api_id),
                "price_of_one": float(trans.price_of_one),
                "quantity": float(trans.quantity),
                "created_at": trans.created_at.isoformat()
            }
        )
    return transactions_data


async def get_portfolio_value_at(
        db: AsyncSession,
        user_id: UUID,
        timestamp: datetime
):
    """
    Get the portfolios value at a specific time in the form of a float
    """
    holdings = await get_holdings_at_time(db, user_id, timestamp)

    if not holdings:
        return 0.0

    crypto = []
    stocks = []

    for api_id, data in holdings.items():
        if data["type"] == "crypto":
            crypto.append(api_id)
        else:
            stocks.append(api_id)

    crypto_prices = await get_crypto_prices_at(crypto, timestamp)
    stock_prices = await get_stock_prices_at(stocks, timestamp)

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
        range: Literal["1D", "1W", "1M", "1Y", "5Y"]
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
        period = "1d"
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

    currency = ticker.info.get("currency")
    conversion = await get_usd_to_cad()

    hist = ticker.history(
        period=period,
        interval=interval
    )  # fetch its historical prices as a dataframe(SQL) table over a time period with specific intervals

    if hist.empty:
        return {
            "symbol": s,
            "range": range,
            "data": []
        }

    data = []  # A list with each entry being a dictionary in the form {"time": str, "price": float}

    for index, row in hist.iterrows():  # iterate row by row with index being the specific row label (date)
        price = float(row["Close"])

        if currency == "USD" or type == "crypto":
            price *= conversion

        data.append({
            "time": str(index),
            "price": price
            # "Closing" price on that interval, for example if time is 10:15:00, then it fetches price at 10:15:59
        })

    return data, s


def calculate_timespans_for_portfolio_history(
        ranges: Literal[1, 7, 31, 365]
):
    """
    Helper function to calculate the timespans that we loop through to calculate the portfolios historical values.
    Returns a list of timedelta objects.
    """
    now = datetime.now(timezone.utc)

    start = now - timedelta(days=ranges)

    # translate it to a way that my other functions can understand
    # Note that points is how many points in time were splitting by so 289 points in 1 day should be 5-minute intervals
    # its actually 288 splits but we add one to account for start and finish
    if ranges == 1:
        points = 289
        t = "1D"

    elif ranges == 7:
        points = 169
        t = "1W"

    elif ranges == 31:
        points = 121
        t = "1M"

    else:
        points = 366
        t = "1Y"

    #
    step = (now - start) / (points - 1)

    timestamps = []

    for i in range(points):
        timestamps.append(start + (step * i))

    return timestamps, t


async def get_portfolio_value_history(
        db: AsyncSession,
        user_id: UUID,
        ranges: Literal[1, 7, 31, 365]
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
            time
        )  # Dictionary of holdings with api_id mapping to another dictionary with information needed

        for symbol, holding in holdings.items():

            if symbol not in cached_histories:

                history, _ = await get_history_of_prices(
                    symbol,
                    holding["type"],
                    t
                )  # List of prices mapping {api_id: price}

                parsed = []

                for item in history:
                    parsed.append({
                        "time": datetime.fromisoformat(item["time"]),
                        "price": float(item["price"])
                    })

                cached_histories[symbol] = parsed  # store the information into our cached history

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


def is_valid_symbol(item, asset):
    symbol = item["symbol"].upper()
    symbol_starts_with_query = symbol.startswith(asset.upper())
    no_foreign_exchange_suffix = "." not in item["symbol"]
    type_is_supported = item.get("type") == "Common Stock"
    return symbol_starts_with_query and no_foreign_exchange_suffix and type_is_supported
