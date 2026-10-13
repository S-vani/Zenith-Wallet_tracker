import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Literal
from dotenv import load_dotenv
import httpx
from decimal import Decimal

from fastapi import HTTPException, Depends, APIRouter, Query
from fastapi_users import exceptions
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyst.data import coingecko_chart
from backend.authentication.authentication import current_active_user, get_user_manager
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User, UserManager
from backend.schemas.assets import CreateTransaction, UpdateTransaction, UpdateUserInfo, UpdateUserEmail
from backend.services.asset_services import (current_quantity, create_holding_filter, \
                                             turn_list_to_dict, calculate_profit_for_one_transaction,
                                             get_curr_holdings_prices, \
                                             get_holdings_at_time, get_portfolio_value_at, get_cash_flow_between,
                                             get_total_realized_profit, \
                                             get_holdings_at_time_list, get_history_of_prices,
                                             get_portfolio_value_history, \
                                             get_all_conversion_rates, get_conversion_factor,
                                             rebuild_symbol_ledger, get_latest_stock_quotes)

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

    symbol = result.symbol
    await session.delete(result)
    await session.flush()

    # e.g. deleting the buy behind a sell would leave a negative position
    if not await rebuild_symbol_ledger(session, current_user.id, symbol):
        await session.rollback()
        raise HTTPException(status_code=409, detail="Deleting this would leave you selling more than you owned")

    await session.commit()

    return {"id": trans_id, "deleted": True}


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
    old_symbol = transaction.symbol

    # Check exactly what was sent in
    if updates.symbol:
        transaction.symbol = updates.symbol
    if updates.action:
        transaction.action = updates.action
    if updates.asset_type:
        transaction.asset_type = updates.asset_type
    if updates.price_of_one:
        rates = await get_all_conversion_rates()
        transaction.price_of_one = updates.price_of_one / get_conversion_factor(rates, current_user.currency)
    if updates.quantity:
        transaction.quantity = updates.quantity
    if updates.api_id:
        transaction.api_id = updates.api_id

    await session.flush()

    # replay the affected symbols: no selling more than owned, and sell profits follow the edited prices
    for symbol in {old_symbol, transaction.symbol}:
        if not await rebuild_symbol_ledger(session, current_user.id, symbol):
            await session.rollback()
            raise HTTPException(status_code=409, detail="Insufficient holdings")

    await session.commit()
    await session.refresh(transaction)
    return transaction


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

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    return turn_list_to_dict(result, conversion)


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
    # Prices are stored in CAD and converted on the way out, so convert what the user typed (in their currency) to CAD
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)
    data = data.model_copy(update={"price_of_one": data.price_of_one / conversion})

    profit_calculated = 0.0
    if data.action == "SELL":
        curr_holdings = await current_quantity(session, current_user.id, data.symbol)
        # compare as Decimals at the database's 10 decimal places so selling "everything" isn't blocked by float error
        sell_quantity = Decimal(str(data.quantity)).quantize(Decimal("1e-10"))
        if sell_quantity > curr_holdings:
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
        current_timeperiod: Literal["day", "week", "month", "year", "all"] = "day",

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
        price = float(curr_prices.get(api_id) or 0.0)
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
        symbol: Annotated[str, Query(min_length=1, max_length=64)],
        type: Annotated[Literal["stock", "crypto"], Query()],
        range: Literal["1D", "1W", "1M", "1Y", "5Y"],

        current_user: User = Depends(current_active_user)
):
    """
    Get historical prices of that specific symbol/holding on specific ranges, to make a graph. For example lets say
    I want to see how much BTC has changed in price over the past day, I call get_price_history("BTC", "1D") and it
    returns all the data needed to generate a graph of its price
    """
    try:
        data, s = await get_history_of_prices(symbol, type, range, current_user.currency)
    except Exception:  # unknown ticker or the price source is down
        data, s = [], symbol

    if not data and type == "crypto":
        # Yahoo doesn't list every coin under "SYMBOL-USD" (e.g. PEPE), so fall back to CoinGecko
        try:
            data = await coingecko_chart(symbol, range, current_user.currency)
        except Exception:
            data = []

    if range == "1D" and data:
        if type == "crypto":
            # crypto trades 24/7, show a rolling 24 hours
            cutoff = datetime.now(timezone.utc) - timedelta(days=1)
            data = [p for p in data if datetime.fromisoformat(p["time"]) >= cutoff]
        else:
            # stocks: only the most recent trading session
            last_day = datetime.fromisoformat(data[-1]["time"]).date()
            data = [p for p in data if datetime.fromisoformat(p["time"]).date() == last_day]

    return {
        "symbol": s,
        "range": range,
        "data": data
    }


@router.get("/portfolio/history")
async def get_portfolio_history(
        range: int = Query(ge=1, le=3650),  # days; "All" is the days since joining, capped at 10 years

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    return a list of dictionaries which each have a time mapping to a string of time and also a value mapping to a float,
    to create a chart for frontend
    """
    data = await get_portfolio_value_history(session, current_user.id, range, current_user.currency)

    return data


# TwelveData's free plan allows 8 credits a minute, so matches for a query are kept for a while instead of being
# looked up again (e.g. when the user switches to crypto and back). {query: (time, [symbols])}
_stock_search_cache: dict[str, tuple[float, list[str]]] = {}
STOCK_SEARCH_TTL = 600


async def find_us_stock_symbols(query: str) -> list[str]:
    """
    Up to 6 unique US-listed stock / ETF symbols matching the query, from TwelveData's symbol search (1 credit).
    Raises a 503 when TwelveData returns an error (usually the per-minute credit limit) so the user sees that instead
    of "no results".
    """
    cached = _stock_search_cache.get(query)
    if cached and time.monotonic() - cached[0] < STOCK_SEARCH_TTL:
        return cached[1]

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.twelvedata.com/symbol_search",
            params={"symbol": query, "show_plan": True, "apikey": os.getenv("API_KEY")}
        )
    body = response.json()

    # errors come back as {"code": 429, "status": "error", "message": ...} with no "data" key
    if not isinstance(body, dict) or body.get("status") == "error" or "data" not in body:
        code = body.get("code") if isinstance(body, dict) else None
        if code == 429 or response.status_code == 429:
            raise HTTPException(status_code=503,
                                detail="Stock search is busy right now. Please try again in a minute.")
        raise HTTPException(status_code=503, detail="Stock search is temporarily unavailable")

    symbols = []
    for result in body["data"]:
        is_us = result.get("country") == "United States"
        is_valid_type = result.get("instrument_type") in ["Common Stock", "ETF"]
        if is_us and is_valid_type and result["symbol"] not in symbols:  # skip duplicate listings
            symbols.append(result["symbol"])
        if len(symbols) == 6:
            break

    _stock_search_cache[query] = (time.monotonic(), symbols)
    return symbols


@router.get("/assets/search/stock")
async def search_assets_stocks(asset: str, current_user: User = Depends(current_active_user)):
    """
    Search US stocks and ETFs. For example if asset is "AAP" this returns up to 6 items like AAPL, AAPD, etc. with
    their price and daily change in the user's currency. Matches come from TwelveData, prices from Yahoo (free).
    """
    asset = asset.strip().upper()
    if not asset:
        return []

    symbols = await find_us_stock_symbols(asset)
    if not symbols:
        return []

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)
    usd_to_user = float(rates["usd_to_cad"]) * conversion  # only US listings are kept, so prices are in USD

    quotes = await get_latest_stock_quotes(symbols)
    if not quotes:
        raise HTTPException(status_code=503, detail="Stock prices are temporarily unavailable")

    final = []
    for symbol in symbols:  # keep TwelveData's relevance order
        quote = quotes.get(symbol)
        if quote is None:  # Yahoo has no prices for it (e.g. a newly listed or delisted ticker)
            continue
        change = quote["close"] - quote["previous_close"]
        final.append({
            "api_id": symbol,
            "symbol": symbol,
            "type": "stock",
            "image": "",
            "price": quote["close"] * usd_to_user,
            "change": change * usd_to_user,
            "change_pct": change / quote["previous_close"] * 100 if quote["previous_close"] else 0.0,
        })

    return final


@router.get("/assets/search/crypto")
async def search_assets_crypto(asset: str, current_user: User = Depends(current_active_user)):
    """
    Use coingecko api to fetch crypto prices of assets, similar to the route above in format.
    """
    gecko = os.getenv("API_KEY_COINEGECKO")

    asset = asset.strip()
    if not asset:
        return []

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    headers = {
        "x-cg-demo-api-key": gecko
    }

    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        res = await client.get("https://api.coingecko.com/api/v3/search", params={"query": asset})

        data = res.json().get("coins", [])[:6]  # top 6 results and luckily coingecko sorts by popularity
        if not data:
            return []

        ids = ",".join(coin["api_symbol"] for coin in data)

        response = await client.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "cad",
                "ids": ids,
                "price_change_percentage": "24h",
            }
        )

    data_1 = response.json()
    if not isinstance(data_1, list):  # coingecko returns an error dict when rate limited
        raise HTTPException(status_code=503, detail="Crypto prices are temporarily unavailable")

    final = []
    seen = set()
    for coin in data_1:
        if (
                coin.get("current_price") is None
                or coin.get("price_change_24h") is None
                or coin.get("price_change_percentage_24h") is None
                or coin["symbol"] in seen  # different coins can share a ticker, keep the most popular one
        ):
            continue
        seen.add(coin["symbol"])
        final.append({
            "api_id": coin["symbol"],
            "symbol": coin["symbol"],
            "coin_id": coin.get("id"),  # CoinGecko id (e.g. "bitcoin"), used by the market analyst
            "type": "crypto",
            "image": coin["image"],  # may or may not use
            "price": coin["current_price"] * conversion,
            "change": coin["price_change_24h"] * conversion,
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
        "date_joined": current_user.date_joined.replace(tzinfo=timezone.utc).isoformat()
        if current_user.date_joined else None,
        # accounts made before signup sent a currency can have "" saved, fall back to CAD
        "currency": current_user.currency if current_user.currency in ("CAD", "USD", "EUR") else "CAD",
        "isVerified": current_user.is_verified
    }

    return information


@router.get("/users")
async def return_users_count(session: AsyncSession = Depends(get_async_session)):
    """
    Return the total number of users, shown on the home page.
    """
    result = await session.execute(select(func.count()).select_from(User))

    return result.scalar_one()


@router.put("/user/information")
async def edit_user_info(new_info: UpdateUserInfo,
                         current_user: User = Depends(current_active_user),
                         session: AsyncSession = Depends(get_async_session),
                         ):
    """
    Update the users name and preferred currency. Email changes go through /user/email so they get re-verified.
    """
    if new_info.name is not None:
        current_user.name = new_info.name.strip()
    if new_info.currency is not None:
        current_user.currency = new_info.currency

    await session.commit()
    await session.refresh(current_user)

    return await return_user_information(current_user)


@router.put("/user/email")
async def change_user_email(
        new_email: UpdateUserEmail,
        current_user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session),
        user_manager: UserManager = Depends(get_user_manager),
):
    """
    Change the users email, mark them as unverified and send a verification email to the new address.
    """
    email = str(new_email.email)

    if email.lower() != current_user.email.lower():
        try:
            await user_manager.get_by_email(email)
            raise HTTPException(status_code=409, detail="That email is already in use")
        except exceptions.UserNotExists:
            pass

        current_user.email = email
        current_user.is_verified = False

        await session.commit()
        await session.refresh(current_user)

    elif current_user.is_verified:
        return {"message": "This email is already verified"}

    await user_manager.request_verify(current_user)

    return {"message": "Verification email sent"}
