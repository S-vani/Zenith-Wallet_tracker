import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Literal
from dotenv import load_dotenv
import httpx
from decimal import Decimal

from fastapi import HTTPException, Depends, APIRouter, Query
from fastapi_users import exceptions
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import auth_backend, current_active_user, get_user_manager
from backend.authentication.cleanup import delete_users
from backend.authentication.schemas import ChangeEmail, ChangePassword, ConfirmPassword
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User, UserManager, send_notice_email
from backend.ratelimit import check_email_cooldown, check_reauth_allowed, record_reauth_failure
from backend.schemas.assets import CreateTransaction, UpdateTransaction, UpdateUserInfo
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


# Search is the one place where a user makes the server call rate-limited providers on demand (TwelveData's free plan
# allows 8 credits a minute, CoinGecko's demo plan about 30 calls a minute). So queries are short, matches are cached
# for a while, and each user can only start a limited number of new (uncached) searches a minute.
SEARCH_QUERY_MAX_LENGTH = 20  # longer than any ticker or coin name people actually type
SEARCH_CACHE_SIZE = 256  # queries kept per cache; the least recently used one is dropped first
STOCK_SEARCH_TTL = 600  # TwelveData matches hardly change, keep them 10 minutes
CRYPTO_SEARCH_TTL = 300  # CoinGecko results include prices, so only 5 minutes
SEARCH_RATE_LIMIT = 20  # new (uncached) searches per user per window
SEARCH_RATE_WINDOW = 60  # seconds

# {query: (time stored, results)}. Dicts keep insertion order, so the first key is the least recently used
_stock_search_cache: dict[str, tuple[float, list[dict]]] = {}
_crypto_search_cache: dict[str, tuple[float, list[dict]]] = {}
_search_times: dict = {}  # {user id: deque of the times of their recent uncached searches}


def _cache_get(cache: dict, key: str, ttl: float):
    """The cached value for `key`, or None when it's missing or older than `ttl` seconds."""
    entry = cache.get(key)
    if entry is None:
        return None
    if time.monotonic() - entry[0] >= ttl:
        cache.pop(key, None)
        return None
    cache[key] = cache.pop(key)  # move it to the end: most recently used
    return entry[1]


def _cache_put(cache: dict, key: str, value) -> None:
    cache.pop(key, None)
    cache[key] = (time.monotonic(), value)
    while len(cache) > SEARCH_CACHE_SIZE:
        cache.pop(next(iter(cache)))  # least recently used


def _check_search_rate(user_id) -> None:
    """Count one new search for the user, or raise a 429 when they started too many in the last minute."""
    now = time.monotonic()
    recent = _search_times.get(user_id)
    if recent is None:
        if len(_search_times) >= 10_000:  # forget users who haven't searched in the last minute, so this stays small
            idle = [uid for uid, times in _search_times.items() if not times or now - times[-1] >= SEARCH_RATE_WINDOW]
            for uid in idle:
                del _search_times[uid]
        recent = _search_times[user_id] = deque()
    while recent and now - recent[0] >= SEARCH_RATE_WINDOW:
        recent.popleft()
    if len(recent) >= SEARCH_RATE_LIMIT:
        raise HTTPException(status_code=429,
                            detail="You're searching very quickly. Please wait a minute and try again.")
    recent.append(now)


def clean_search_query(asset: str) -> str:
    asset = asset.strip()
    if len(asset) > SEARCH_QUERY_MAX_LENGTH:
        raise HTTPException(status_code=422, detail=f"Search for {SEARCH_QUERY_MAX_LENGTH} characters or fewer, "
                                                    "e.g. a ticker like AAPL or a coin like BTC.")
    return asset


async def find_us_stock_symbols(query: str, user_id=None) -> list[dict]:
    """
    Up to 6 unique US-listed stocks / ETFs matching the query as {"symbol", "name"}, from TwelveData's symbol search
    (1 credit). Raises a 503 when TwelveData returns an error (usually the per-minute credit limit) so the user sees
    that instead of "no results", and a 429 when the user starts too many new searches.
    """
    cached = _cache_get(_stock_search_cache, query, STOCK_SEARCH_TTL)
    if cached is not None:
        return cached
    if user_id is not None:
        _check_search_rate(user_id)

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

    matches, seen = [], set()
    for result in body["data"]:
        is_us = result.get("country") == "United States"
        is_valid_type = result.get("instrument_type") in ["Common Stock", "ETF"]
        if is_us and is_valid_type and result["symbol"] not in seen:  # skip duplicate listings
            seen.add(result["symbol"])
            matches.append({"symbol": result["symbol"], "name": result.get("instrument_name") or ""})
        if len(matches) == 6:
            break

    _cache_put(_stock_search_cache, query, matches)
    return matches


@router.get("/assets/search/stock")
async def search_assets_stocks(asset: Annotated[str, Query(max_length=200)],
                               current_user: User = Depends(current_active_user)):
    """
    Search US stocks and ETFs. For example if asset is "AAP" this returns up to 6 items like AAPL, AAPD, etc. with
    their name, price and daily change in the user's currency. Matches come from TwelveData, prices from Yahoo (free).
    """
    asset = clean_search_query(asset).upper()
    if not asset:
        return []

    matches = await find_us_stock_symbols(asset, current_user.id)
    if not matches:
        return []

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)
    usd_to_user = float(rates["usd_to_cad"]) * conversion  # only US listings are kept, so prices are in USD

    quotes = await get_latest_stock_quotes([m["symbol"] for m in matches])
    if not quotes:
        raise HTTPException(status_code=503, detail="Stock prices are temporarily unavailable")

    final = []
    for match in matches:  # keep TwelveData's relevance order
        symbol = match["symbol"]
        quote = quotes.get(symbol)
        if quote is None:  # Yahoo has no prices for it (e.g. a newly listed or delisted ticker)
            continue
        change = quote["close"] - quote["previous_close"]
        final.append({
            "api_id": symbol,
            "symbol": symbol,
            "name": match["name"],  # company or fund name, shown under the ticker
            "type": "stock",
            "image": "",
            "price": quote["close"] * usd_to_user,
            "change": change * usd_to_user,
            "change_pct": change / quote["previous_close"] * 100 if quote["previous_close"] else 0.0,
        })

    return final


async def find_coins(query: str, user_id) -> list[dict]:
    """
    CoinGecko market data (prices in CAD) for the top 6 coins matching the query, cached per query because CoinGecko
    is rate limited. Raises a 503 when CoinGecko returns an error instead of prices.
    """
    cached = _cache_get(_crypto_search_cache, query, CRYPTO_SEARCH_TTL)
    if cached is not None:
        return cached
    _check_search_rate(user_id)

    headers = {
        "x-cg-demo-api-key": os.getenv("API_KEY_COINEGECKO")
    }

    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        res = await client.get("https://api.coingecko.com/api/v3/search", params={"query": query})

        data = res.json().get("coins", [])[:6]  # top 6 results and luckily coingecko sorts by popularity
        if not data:
            _cache_put(_crypto_search_cache, query, [])
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

    coins = response.json()
    if not isinstance(coins, list):  # coingecko returns an error dict when rate limited
        raise HTTPException(status_code=503, detail="Crypto prices are temporarily unavailable")

    _cache_put(_crypto_search_cache, query, coins)
    return coins


@router.get("/assets/search/crypto")
async def search_assets_crypto(asset: Annotated[str, Query(max_length=200)],
                               current_user: User = Depends(current_active_user)):
    """
    Use coingecko api to fetch crypto prices of assets, similar to the route above in format.
    """
    asset = clean_search_query(asset)
    if not asset:
        return []

    coins = await find_coins(asset.lower(), current_user.id)
    if not coins:
        return []

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    final = []
    seen = set()
    for coin in coins:
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
            "name": coin.get("name") or "",  # e.g. "Bitcoin", shown under the ticker
            "coin_id": coin.get("id"),  # CoinGecko id (e.g. "bitcoin"), used by the market analyst
            "type": "crypto",
            "image": coin.get("image") or "",  # some coins have no logo; the page then shows none
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
        "isVerified": current_user.is_verified,
        # False for Google accounts without a password of their own: the Account page then points to Forgot password
        "hasPassword": bool(current_user.has_password),
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


NO_PASSWORD_MESSAGE = ("Your account doesn't have a password yet because you signed in with Google. "
                       "Use Forgot password to set one first.")


async def require_current_password(user: User, password: str, user_manager: UserManager) -> None:
    """
    Sensitive changes need the current password, not just a (possibly stolen) login token.
    Errors are 400s on purpose: a 401/403 would make the frontend sign the user out.
    """
    check_reauth_allowed(user.id)  # a stolen token mustn't become a way to guess the password
    if not user.has_password:
        raise HTTPException(status_code=400, detail=NO_PASSWORD_MESSAGE)
    if not user_manager.check_password(user, password):
        record_reauth_failure(user.id)
        message = "Your current password is incorrect."
        if user.oauth_accounts:
            message += " If you signed up with Google, use Forgot password to set one first."
        raise HTTPException(status_code=400, detail=message)


@router.put("/user/email")
async def change_user_email(
        body: ChangeEmail,
        current_user: User = Depends(current_active_user),
        user_manager: UserManager = Depends(get_user_manager),
):
    """
    Change the user's email (current password required). The account becomes unverified, every device is signed
    out, a verification link goes to the new address and a notice goes to the old one, so the owner finds out if
    someone else did this.
    """
    await require_current_password(current_user, body.current_password, user_manager)
    email = str(body.email)
    old_email = str(current_user.email)

    if email.lower() == old_email.lower():
        return {"message": "This email is already verified"}

    try:
        await user_manager.get_by_email(email)
        raise HTTPException(status_code=409, detail="That email is already in use")
    except exceptions.UserNotExists:
        pass

    check_email_cooldown(email)
    user = await user_manager.sign_out_everywhere(current_user, email=email, is_verified=False)
    await user_manager.request_verify(user)
    await send_notice_email(
        old_email, "Your Zenith email was changed",
        f"The email address on your Zenith account was just changed from {old_email} to {email}.\n\n"
        f"If you did this, there's nothing else to do. If you didn't, reply to this email so we can help you get "
        f"your account back.\n",
    )

    return {"message": "Verification email sent"}


@router.post("/user/password")
async def change_password(
        body: ChangePassword,
        current_user: User = Depends(current_active_user),
        user_manager: UserManager = Depends(get_user_manager),
        strategy=Depends(auth_backend.get_strategy),
):
    """
    Change the password (current password required). Every other device is signed out; this one gets a fresh token
    back so the person changing it stays signed in.
    """
    await require_current_password(current_user, body.current_password, user_manager)
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="Choose a new password that's different from your current one.")
    try:
        await user_manager.validate_password(body.new_password, current_user)
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(status_code=400, detail=e.reason)

    user = await user_manager.sign_out_everywhere(
        current_user, hashed_password=user_manager.password_helper.hash(body.new_password), has_password=True,
    )
    await send_notice_email(
        str(user.email), "Your Zenith password was changed",
        "The password for your Zenith account was just changed and your other devices were signed out.\n\n"
        "If this wasn't you, use \"Forgot password\" on the login page right away to choose a new one.\n",
    )
    return {"message": "Password changed", "access_token": await strategy.write_token(user), "token_type": "bearer"}


@router.post("/user/logout-all")
async def log_out_everywhere(
        current_user: User = Depends(current_active_user),
        user_manager: UserManager = Depends(get_user_manager),
):
    """Sign out every device, this one included (e.g. after losing a phone)."""
    await user_manager.sign_out_everywhere(current_user)
    return {"message": "Signed out of all devices"}


@router.delete("/user")
async def delete_account(
        body: ConfirmPassword,
        current_user: User = Depends(current_active_user),
        session: AsyncSession = Depends(get_async_session),
        user_manager: UserManager = Depends(get_user_manager),
):
    """
    Permanently delete the signed-in user's account (current password required): their transactions, any linked
    Google login and the user itself, all in one database transaction. There is no undo (the app stores require
    in-app account deletion). Analyst reports are shared per asset, not per user, so they stay.
    """
    await require_current_password(current_user, body.current_password, user_manager)
    await delete_users(session, [current_user.id])

    return {"message": "Account deleted"}
