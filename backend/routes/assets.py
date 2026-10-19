import os
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Literal
from dotenv import load_dotenv
import httpx
from decimal import Decimal

from fastapi import HTTPException, Depends, APIRouter, Query
from fastapi_users import exceptions
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyst.service import forget_user
from backend.authentication.authentication import current_active_user, get_user_manager
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User, UserManager, OAuthAccount
from backend.schemas.assets import CreateTransaction, UpdateTransaction, UpdateUserInfo, UpdateUserEmail
from backend.services.asset_services import (current_quantity, create_holding_filter, \
                                             turn_list_to_dict, calculate_profit_for_one_transaction,
                                             get_curr_holdings_prices, \
                                             get_holdings_at_time, get_cash_flow_between,
                                             get_total_realized_profit, \
                                             get_holdings_at_time_list, get_history_of_prices,
                                             get_portfolio_value_history, \
                                             get_all_conversion_rates, get_conversion_factor,
                                             rebuild_symbol_ledger, get_latest_stock_quotes,
                                             get_position_values_at, get_buys_between, get_coingecko_history)

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


# 409 messages; the frontend turns these into a sentence about the trade being saved, edited or deleted
OVERSOLD = "Insufficient holdings"
OVERSOLD_AFTER_DELETE = "Deleting this would leave you selling more than you owned"


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
        raise HTTPException(status_code=409, detail=OVERSOLD_AFTER_DELETE)

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
        # the new price was typed in the user's currency, keep it as typed so it doesn't drift with FX
        transaction.price_entered = updates.price_of_one
        transaction.currency_entered = current_user.currency.upper()
    if updates.quantity:
        transaction.quantity = updates.quantity
    if updates.api_id:
        transaction.api_id = updates.api_id
    if updates.created_at:
        transaction.created_at = updates.created_at  # already naive UTC and not in the future (schema)

    await session.flush()

    # replay the affected symbols: no selling more than owned (at any point in time, so moving a trade's date is
    # checked too), and sell profits follow the edited prices
    for symbol in {old_symbol, transaction.symbol}:
        if not await rebuild_symbol_ledger(session, current_user.id, symbol):
            await session.rollback()
            raise HTTPException(status_code=409, detail=OVERSOLD)

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
    Prices and profits are in the user's currency: as typed when typed in that currency, otherwise from CAD.
    """
    query = create_holding_filter(current_user.id, symbol, action, start_date, end_date)

    result = await session.execute(query.order_by(Transaction.created_at.desc()))
    result = result.scalars().all()

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    return turn_list_to_dict(result, conversion, current_user.currency)


@router.post("/transactions")
async def make_transaction(
        data: CreateTransaction,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    The route used to make a transaction where the user enters the data manually. The trade is dated now unless
    `created_at` says otherwise (backdated trades). The symbol's history is then replayed in date order: that sets
    the profit of every sell (used later to add up realized profit) and rejects the trade with a 409 if any point
    of the history would sell more than was owned, e.g. a backdated sell before the buy it needs.
    """
    # Prices are stored in CAD and converted on the way out, so convert what the user typed (in their currency) to CAD.
    # The typed price and currency are kept too, so the trade keeps showing exactly what was typed.
    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    transaction = Transaction(
        action=data.action,
        profit=0,
        asset_type=data.asset_type,
        symbol=data.symbol,
        api_id=data.api_id,
        price_of_one=data.price_of_one / conversion,
        price_entered=data.price_of_one,
        currency_entered=current_user.currency.upper(),
        quantity=data.quantity,
        user_id=current_user.id
    )
    if data.created_at is not None:
        transaction.created_at = data.created_at  # already naive UTC and not in the future (schema)

    session.add(transaction)
    await session.flush()

    if not await rebuild_symbol_ledger(session, current_user.id, data.symbol):
        await session.rollback()
        raise HTTPException(status_code=409, detail=OVERSOLD)  # Error if you are trying to sell more than you have

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
    "current_price": float(current_price_of_holding * quantity), or None when no source has a price for it
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
    Return the total portfolio value, the profit in the time period sent in (daily, weekly, monthly, yearly or all
    time) and `basis`, what that profit is measured against for the return %: the value at the start of the period
    plus the money put in (buys) during it, which for all time is the cost of every buy.
    Holdings that no source has a price for are left out of all three and listed in `unpriced`.
    """
    now = datetime.now(timezone.utc)
    currency = current_user.currency

    holdings = await get_holdings_at_time(session,
                                          current_user.id,
                                          now,
                                          currency)  # returns dict which maps api_id to avg_price, quantity and type

    curr_prices = await get_curr_holdings_prices(
        holdings,
        currency
    ) if holdings else {}  # return dictionary mapping api_id to the current price of that holding (None = no price)

    unpriced = {api_id for api_id in holdings if curr_prices.get(api_id) is None}
    values_now = {  # Basically how much value of each holding the user owns
        api_id: float(curr_prices[api_id]) * float(data["quantity"])
        for api_id, data in holdings.items() if api_id not in unpriced
    }
    total_value = sum(values_now.values())

    # no early return when nothing is held: a sold-out portfolio still has realized profit and a period cash flow
    if current_timeperiod == "all":  # If the timeperiod is all time profit
        unrealized_profit = sum(  # Price right now minus the price paid
            value - float(holdings[api_id]["avg_price"]) * float(holdings[api_id]["quantity"])
            for api_id, value in values_now.items()
        )
        # This function goes through all the users sell transactions and adds up the profit variable
        realized_profit = await get_total_realized_profit(session, current_user.id, currency, exclude=unpriced)
        invested = await get_buys_between(session, current_user.id, None, now, currency, exclude=unpriced)

        return {
            "value": total_value,
            "curr_timeperiod": unrealized_profit + realized_profit,
            "basis": invested,
            "unpriced": sorted(unpriced),
        }

    time_map = {
        "day": 1,
        "week": 7,
        "month": 30,
        "year": 365
    }

    past_time = now - timedelta(
        days=time_map[current_timeperiod])  # start date that where calculating profit from up to now

    # one after the other: an AsyncSession can't run two queries at once
    past_values = await get_position_values_at(session, current_user.id, past_time, currency)

    # a holding needs a price at both ends of the period to have a return for it
    excluded = unpriced | {api_id for api_id, value in past_values.items() if value is None}
    past_value = sum(value for api_id, value in past_values.items() if api_id not in excluded)
    value_now = sum(value for api_id, value in values_now.items() if api_id not in excluded)

    # how much cash has flowed in from then to now (buys minus sells), and the money put in by buying
    cash_flow = await get_cash_flow_between(session, current_user.id, past_time, now, currency, exclude=excluded)
    inflows = await get_buys_between(session, current_user.id, past_time, now, currency, exclude=excluded)

    profit = (value_now - past_value) - cash_flow

    return {
        "value": total_value,
        "curr_timeperiod": profit,
        "basis": past_value + inflows,
        "unpriced": sorted(unpriced),
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
    returns all the data needed to generate a graph of its price.
    `source` says where the prices came from; when the data covers less than was asked for (CoinGecko's free plan
    stops at one year, so "5Y" is really "1Y") `covered_range` and `note` say so.
    """
    try:
        data, s = await get_history_of_prices(symbol, type, range, current_user.currency)
    except Exception:  # unknown ticker or the price source is down
        data, s = [], symbol

    source = "Yahoo Finance" if data else None
    covered = range
    if not data and type == "crypto":
        # Yahoo doesn't list every coin (e.g. PEPE), so fall back to CoinGecko (cached: its demo key is rate limited)
        try:
            data, covered = await get_coingecko_history(symbol, range, current_user.currency)
        except Exception:
            data, covered = [], range
        source = "CoinGecko" if data else None
        if not data:
            covered = range

    if range == "1D" and data:
        if type == "crypto":
            # crypto trades 24/7, show a rolling 24 hours
            cutoff = datetime.now(timezone.utc) - timedelta(days=1)
            data = [p for p in data if datetime.fromisoformat(p["time"]) >= cutoff]
        else:
            # stocks: only the most recent trading session
            last_day = datetime.fromisoformat(data[-1]["time"]).date()
            data = [p for p in data if datetime.fromisoformat(p["time"]).date() == last_day]

    body = {
        "symbol": s,
        "range": range,
        "data": data,
        "source": source,
    }
    if covered != range:
        body["covered_range"] = covered
        body["note"] = "Only the last year of prices is available for this coin."
    return body


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


@router.delete("/user")
async def delete_account(
        current_user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session),
):
    """
    Permanently delete the signed-in user's account: their transactions, any linked Google login and the user
    itself, all in one database transaction. There is no undo (the app stores require in-app account deletion).
    Analyst reports are shared per asset, not per user, so they stay.
    """
    user_id = current_user.id
    # bulk deletes, so the ORM doesn't try to null out the foreign keys of the user's children first
    await session.execute(delete(Transaction).where(Transaction.user_id == user_id))
    await session.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
    forget_user(str(user_id))

    return {"message": "Account deleted"}
