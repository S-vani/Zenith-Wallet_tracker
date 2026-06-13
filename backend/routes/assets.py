import asyncio
import os
from datetime import datetime, timedelta, timezone
from tkinter.tix import Select
from typing import Optional, Literal
import yfinance as yf
from dotenv import load_dotenv
import requests

from fastapi import HTTPException, Depends, APIRouter, Query
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User
from backend.schemas.assets import CreateTransaction, UpdateTransaction
from backend.services.asset_services import (current_quantity, create_holding_filter, \
                                             turn_list_to_dict, calculate_profit_for_one_transaction,
                                             get_curr_holdings_prices, \
                                             get_holdings_at_time, get_portfolio_value_at, get_cash_flow_between,
                                             get_total_realized_profit, \
                                             get_holdings_at_time_list, get_history_of_prices,
                                             get_portfolio_value_history, \
                                             get_all_conversion_rates, get_conversion_factor)

load_dotenv()
router = APIRouter()


@router.get("/transactions/{trans_id}")
async def return_transaction_with_id(
        trans_id: str,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    When given an id return exactly what transaction it is, if the id is not found return a 404 error.

    Note that the user won't actually be entering a transaction id, this is mainly used as a helper to
    fetch certain transactions and also so when the user is on the transactions page, they can select a specific transaction
    and based on what they click the front end will automatically send the id here to return the information of
    the transaction.
    """
    result = await session.execute(
        select(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.id == trans_id
        )
    )

    transaction = result.scalars().first()  # we use .first since obviously when we are querying based off a transaction id there should only be one
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return transaction


@router.delete("/transactions/{trans_id}")
async def delete_transaction_with_id(
        trans_id: str,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    When given an id delete the transaction from the users history.

    Note that the user won't actually be entering a transaction id, this is mainly used as a helper to
    fetch certain transactions and also so when the user is on the transactions page, they can select a specific transaction
    and based on what they click the front end will automatically send the id here to delete the transaction.
    """
    holding = await session.execute(
        select(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.id == trans_id
        )
    )
    result = holding.scalars().first()

    if result is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    await session.delete(result)
    await session.commit()

    return result


@router.put("/transactions/{trans_id}")
async def update_transaction_with_id(
        trans_id: str,
        updates: UpdateTransaction,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    When given an id update the transaction with the new information the user passes in.

    Note that the user won't actually be entering a transaction id, they will select buttons from the front end that will
    automatically call this route with the information inputted by the user.
    """
    transaction = await return_transaction_with_id(trans_id, session, current_user)

    # Check exactly what was sent in
    if updates.symbol:
        transaction.symbol = updates.symbol
    if updates.action:
        transaction.action = updates.action
    if updates.asset_type:
        transaction.asset_type = updates.asset_type
    if updates.price_of_one:
        transaction.price_of_one = updates.price_of_one
    if updates.quantity:
        transaction.quantity = updates.quantity
    if updates.api_id:
        transaction.api_id = updates.api_id


@router.get("/transactions")
async def return_holdings_with_filter(
        symbol: Optional[str] = Query(None),
        action: Optional[Literal["BUY", "SELL"]] = Query(None),
        start_date: Optional[datetime] = Query(None),
        end_date: Optional[datetime] = Query(None),

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    User can filter the transactions by sending specific information and seen in the parameters and it will return a
    list where each entry is a dictionary like this:
                "id": str(trans.id),
                "user_id": str(trans.user_id),
                "action": str(trans.action),
                "asset_type": str(trans.asset_type),
                "symbol": str(trans.symbol),
                "api_ids": str(trans.api_id),
                "price_of_one": float(trans.price_of_one),
                "quantity": float(trans.quantity),
                "created_at": trans.created_at.isoformat()
    """
    query = create_holding_filter(current_user.id, symbol, action, start_date, end_date)

    result = await session.execute(query.order_by(Transaction.created_at.desc()))
    result = result.scalars().all()

    return turn_list_to_dict(result)


@router.post("/transactions")
async def make_transaction(
        data: CreateTransaction,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    The route used to make a transaction where the user enters the data manually and then if it is a sell,
    the profit is calculated and set up. This variable profit that comes with every sell transaction is used later to
    calculate realized profit by simply looping through every sell and adding the profit made. A transaction instance is made
    the added to the database.
    """
    profit_calculated = 0.0
    if data.action == "SELL":
        curr_holdings = await current_quantity(session, current_user.id, data.symbol)
        if data.quantity > curr_holdings:
            raise HTTPException(status_code=409,
                                detail="Insufficient holdings")  # Error if you are trying to sell more than you have

        profit_calculated = await calculate_profit_for_one_transaction(session,
                                                                       current_user.id,
                                                                       data,
                                                                       current_user.currency)  # Calculate profit for the sell

    transaction = Transaction(
        action=data.action,
        profit=profit_calculated,
        asset_type=data.asset_type,
        symbol=data.symbol,
        api_id=data.api_id,
        price_of_one=data.price_of_one,
        quantity=data.quantity,
        user_id=current_user.id
    )
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)
    return transaction


@router.get("/holdings")
async def get_current_holdings(
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    Return a list of dictionaries in the form:
    {
    "symbol": str,
    "price_paid": float(avg_price * quantity),
    "quantity": float(quantity),
    "type": str,
    "current_price": float(current_price_of_holding * quantity)
    }

    this is a dictionary with all the current holdings that the user has
    """
    return await get_holdings_at_time_list(session, current_user.id, datetime.now(timezone.utc), current_user.currency)


@router.get("/dashboard")
async def portfolio_stats(
        current_timeperiod: Optional[Literal["day", "week", "month", "year", "all"]] = None,

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    Return a simple dictionary with 2 key value pairs, total portfolio value and the profit in the time period sent in,
    either daily, weekly, monthly, yearly or all time profit.
    """
    now = datetime.now(timezone.utc)

    holdings = await get_holdings_at_time(session,
                                          current_user.id,
                                          now,
                                          current_user.currency)  # returns dict which maps api_id to avg_price, quantity and type

    if holdings == {}:  # If we have no holdings
        return {"value": 0.0, "curr_timeperiod": 0.0}

    curr_prices = await get_curr_holdings_prices(
        holdings,
        current_user.currency
    )  # return dictionary mapping api_id to the current price of that holding

    total_value = 0.0
    unrealized_profit = 0.0

    for api_id, data in holdings.items():
        price = float(curr_prices[api_id])
        qty = float(data["quantity"])
        avg = float(data["avg_price"])

        position_value = price * qty  # Basically how much value of that holding the user owns
        total_value += position_value
        unrealized_profit += (position_value - (avg * qty))  # Price right now minus the price paid

    if current_timeperiod == "all":  # If the timeperiod is all time profit
        realized_profit = await get_total_realized_profit(session,
                                                          current_user.id,
                                                          current_user.currency)  # This function goes through all the users sell transactions and adds up the profit variable

        return {
            "value": total_value,
            "curr_timeperiod": unrealized_profit + realized_profit
        }

    time_map = {
        "day": 1,
        "week": 7,
        "month": 30,
        "year": 365
    }

    past_time = now - timedelta(
        days=time_map[current_timeperiod])  # start date that where calculating profit from up to now

    value_task = get_portfolio_value_at(session, current_user.id, past_time,
                                        current_user.currency)  # portfolio value at that pastime
    cash_task = get_cash_flow_between(session, current_user.id, past_time,
                                      now,
                                      current_user.currency)  # how much cash has flowed in from then to now (user buys new holdings)

    past_value, cash_flow = await asyncio.gather(
        value_task,
        cash_task
    )  # asynchronously run both tasks together for efficiency and unpack the result

    profit = (total_value - past_value) - cash_flow

    return {
        "value": total_value,
        "curr_timeperiod": profit
    }


@router.get("/prices/history")
async def get_price_history(
        symbol: str,
        type: str,
        range: Literal["1D", "1W", "1M", "1Y", "5Y"],

        current_user: User = Depends(current_active_user)
):
    """
    Get historical prices of that specific symbol/holding on specific ranges, to make a graph. For example lets say
    I want to see how much BTC has changed in price over the past day, I call get_price_history("BTC", "1D") and it
    returns all the data needed to generate a graph of its price
    """
    data, s = await get_history_of_prices(symbol, type, range, current_user.currency)

    return {
        "symbol": s,
        "range": range,
        "data": data
    }


@router.get("/portfolio/history")
async def get_portfolio_history(
        range: int,

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    return a list of dictionaries which each have a time mapping to a string of time and also a value mapping to a float,
    to create a chart for frontend
    """
    data = await get_portfolio_value_history(session, current_user.id, range, current_user.currency)

    return data


@router.get("/assets/search/stock")
async def search_assets_stocks(asset: str, current_user: User = Depends(current_active_user)):
    """
    Use twelvedata api to fetch a list of dictionaries with all the information about all the search results based on
    what asset is. For example is asset is "AAP" then this would return a max of 6 items in a list with each being a
    stock, like AAPL, AAPD, etc.
    """
    asset = asset.upper()
    twelve = os.getenv("API_KEY")

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)
    conversion_to_cad = rates["usd_to_cad"]

    url = (
        f"https://api.twelvedata.com/symbol_search"
    )

    params = {
        "symbol": asset,
        "show_plan": True,
        "apiKey": twelve
    }

    search_response = requests.get(url, params=params)

    # Data is returned as a dict and the key "data" is basically all the important stuff
    all_results = search_response.json()["data"]

    filtered = []
    seen = set()
    for result in all_results:  # unpack results
        symbol = result["symbol"]
        is_us = result.get("country") == "United States"
        is_valid_type = result.get("instrument_type") in ["Common Stock", "ETF"]
        is_new = symbol not in seen  # ensure there aren't any duplicates

        if is_us and is_valid_type and is_new:
            seen.add(symbol)
            filtered.append(result)

        if len(filtered) == 6:
            break

    symbols = ",".join(result["symbol"] for result in filtered)  # get symbols in a form AAPL,GOOG,UAL

    url = (
        f"https://api.twelvedata.com/quote"
    )

    params = {
        "symbol": symbols,
        "apikey": twelve
    }

    response = requests.get(url, params=params)

    res = response.json()

    final = []
    if "symbol" in res:
        final.append({
            "api_id": res["symbol"],
            "symbol": res["symbol"],
            "type": "stock",
            "image": "",
            "price": float(res["close"]) * float(conversion_to_cad) * conversion,
            "change": float(res["change"]) * float(conversion_to_cad) * conversion,
            "change_pct": float(res["percent_change"])
        })
    else:
        for data in res:
            final.append({
                "api_id": res[data]["symbol"],
                "symbol": res[data]["symbol"],
                "type": "stock",
                "image": "",
                "price": float(res[data]["close"]) * float(conversion_to_cad) * conversion,
                "change": float(res[data]["change"]) * float(conversion_to_cad) * conversion,
                "change_pct": float(res[data]["percent_change"])
            })
            print(final)

    return final


@router.get("/assets/search/crypto")
async def search_assets_crypto(asset: str, current_user: User = Depends(current_active_user)):
    """
    Use coingecko api to fetch crypto prices of assets, similar to the route above in format.
    """
    gecko = os.getenv("API_KEY_COINEGECKO")

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    url = (
        f"https://api.coingecko.com/api/v3/search"
    )

    params = {
        "query": asset
    }

    headers = {
        "x-cg-demo-api-key": gecko
    }

    res = requests.get(url, params=params, headers=headers)

    data = res.json()["coins"][:6]  # top 6 results and luckely coingecko sorts by popularity

    ids = ",".join(coin["api_symbol"] for coin in data)

    url = (
        f"https://api.coingecko.com/api/v3/coins/markets"
    )

    params = {
        "vs_currency": conversion,
        "ids": ids,
        "price_change_percentage": "24h",
    }

    response = requests.get(url, params=params, headers=headers)

    data_1 = response.json()

    final = []
    for coin in data_1:
        if (
                coin.get("current_price") is None
                or coin.get("price_change_24h") is None
                or coin.get("price_change_percentage_24h") is None
        ):
            continue
        final.append({
            "api_id": coin["symbol"],
            "symbol": coin["symbol"],
            "type": "crypto",
            "image": coin["image"],  # may or may not use
            "price": coin["current_price"],
            "change": coin["price_change_24h"],
            "change_pct": coin["price_change_percentage_24h"]
        })

    return final


@router.get("/user")
async def return_user_information(
        current_user: User = Depends(current_active_user)
):
    """
    return a dictionary with users information used in the frontend to fetch information to display.
    """
    information = {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "date_joined": current_user.date_joined,
        "currency": current_user.currency
    }

    return information

@router.get("/users")
async def return_users_count(session: AsyncSession = Depends(get_async_session),):
    """

    """
    result = await session.execute(select(User))
    users = result.scalars().all()

    return len(users)
