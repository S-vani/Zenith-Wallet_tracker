import asyncio
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Literal
from dotenv import load_dotenv
import httpx
from decimal import Decimal

from fastapi import HTTPException, Depends, APIRouter, Query, Request
from fastapi_users import exceptions
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from backend.authentication.authentication import (auth_backend, bearer_transport, current_active_user,
                                                     get_user_manager, is_app_request, is_app_token)
from backend.authentication.cleanup import delete_users
from backend.authentication.schemas import ChangeEmail, ChangePassword, ConfirmPassword
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User, UserManager, send_notice_email
from backend.ratelimit import check_email_cooldown, check_reauth_allowed, record_reauth_failure
from backend.schemas.assets import AccountFilter, CreateTransaction, UpdateTransaction, UpdateUserInfo
from backend.services.asset_services import (current_quantity, create_holding_filter, \
                                             turn_list_to_dict, calculate_profit_for_one_transaction,
                                             get_curr_holdings_prices, \
                                             get_holdings_at_time, get_cash_flow_between,
                                             get_total_realized_profit, \
                                             get_holdings_at_time_list, get_history_of_prices,
                                             get_portfolio_value_history, \
                                             get_all_conversion_rates, get_conversion_factor,
                                             rebuild_symbol_ledger, get_latest_stock_quotes,
                                             get_position_values_at, get_buys_between, get_coingecko_history,
                                             end_read, to_cad_on_trade_date, get_ticker_currency,
                                             get_native_to_cad_factor, ACCOUNT_OVERSOLD,
                                             account_shortfalls, account_oversell_added)
from backend.services.imports import CANADIAN_SUFFIXES, listed_symbol, yahoo_class_share

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

# Every holdings / dashboard / chart request prices each distinct asset (up to 2 Yahoo calls each for a coin), so
# one account with hundreds of symbols could make a single request fan out to hundreds of Yahoo calls.
MAX_SYMBOLS_PER_USER = 200
TOO_MANY_SYMBOLS = (f"You can track up to {MAX_SYMBOLS_PER_USER} different assets. "
                    "Delete the trades of one you no longer follow to add a new one.")


async def check_symbol_limit(session: AsyncSession, user_id, api_id: str, ignore_trade: str | None = None) -> None:
    """
    422 when `api_id` would be one asset too many for the user. Assets they already trade are always fine.
    `ignore_trade` leaves out the trade being edited, so moving a trade to a new asset frees its old one.
    """
    trades = select(Transaction.api_id).where(Transaction.user_id == user_id)
    if ignore_trade is not None:
        trades = trades.where(Transaction.id != ignore_trade)
    known = await session.execute(trades.where(Transaction.api_id == api_id).limit(1))
    if known.first() is not None:
        return
    count = await session.execute(select(func.count()).select_from(trades.distinct().subquery()))
    if count.scalar_one() >= MAX_SYMBOLS_PER_USER:
        raise HTTPException(status_code=422, detail=TOO_MANY_SYMBOLS)


# Every holdings / dashboard / chart request replays all of a user's trades, so one account can't grow without limit
# (far more than anyone logs by hand; a script could otherwise fill the database and slow every page down).
MAX_TRANSACTIONS_PER_USER = 20_000


async def check_transaction_limit(session: AsyncSession, user_id) -> None:
    """422 when the user already has MAX_TRANSACTIONS_PER_USER trades."""
    count = await session.execute(select(func.count()).select_from(Transaction).where(Transaction.user_id == user_id))
    if count.scalar_one() >= MAX_TRANSACTIONS_PER_USER:
        raise HTTPException(status_code=422, detail=f"You can log up to {MAX_TRANSACTIONS_PER_USER:,} trades. "
                                                    "Delete some older ones to add new trades.")


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
    # Deleting a sell only leaves more shares, so it can't make another sale impossible. The per-account check is
    # skipped for it: untagged sells draw from the largest account, and removing one could shift a later untagged
    # sell onto another account and report a shortfall the user never caused.
    check_accounts = str(result.action) != "SELL"
    before = await account_shortfalls(session, current_user.id, {symbol}) if check_accounts else {}
    await session.delete(result)
    await session.flush()

    # e.g. deleting the buy behind a sell would leave a negative position, overall or in the sell's account
    if not await rebuild_symbol_ledger(session, current_user.id, symbol):
        await session.rollback()
        raise HTTPException(status_code=409, detail=OVERSOLD_AFTER_DELETE)
    if check_accounts and account_oversell_added(
            before, await account_shortfalls(session, current_user.id, {symbol})):
        await session.rollback()
        raise HTTPException(status_code=409, detail=ACCOUNT_OVERSOLD)

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
    old_api_id = transaction.api_id
    if updates.api_id and updates.api_id != old_api_id:
        await check_symbol_limit(session, current_user.id, updates.api_id, ignore_trade=transaction.id)

    # The CAD price depends on the typed price, its currency and (for a backdated trade) the trade's date, so it's
    # worked out again when any of them changes: a new price is typed in the user's currency, a new date re-converts
    # the price as typed. Done before anything is changed: end_read commits, and nothing may be saved half-edited.
    new_cad_price = None
    when = updates.created_at or transaction.created_at
    if updates.price_of_one:
        typed = (updates.price_of_one, current_user.currency.upper())
    elif updates.created_at and transaction.price_entered is not None and transaction.currency_entered:
        typed = (float(transaction.price_entered), str(transaction.currency_entered).upper())
    else:
        typed = None  # older trades with only a CAD price have nothing to convert
    if typed is not None:
        await end_read(session)  # no connection held while the rates (maybe Yahoo's history) load
        rates = await get_all_conversion_rates()
        new_cad_price = await to_cad_on_trade_date(typed[0], typed[1], when, rates)
        # end_read let go of the row: it may have been deleted (another tab, a sign out everywhere + account
        # deletion) while the rates loaded. Load it again so that's a 404, not a failed UPDATE (StaleDataError, 500)
        reloaded = await session.execute(
            select(Transaction)
            .where(Transaction.user_id == current_user.id, Transaction.id == trans_id)
            .execution_options(populate_existing=True)
        )
        transaction = reloaded.scalars().first()
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        old_symbol = transaction.symbol
        old_api_id = transaction.api_id

    new_symbol = updates.symbol or transaction.symbol
    before = await account_shortfalls(session, current_user.id, {old_symbol, new_symbol})

    # Check exactly what was sent in
    if updates.symbol:
        transaction.symbol = updates.symbol
    if updates.action:
        transaction.action = updates.action
    if updates.asset_type:
        transaction.asset_type = updates.asset_type
    if updates.price_of_one:
        # the new price was typed in the user's currency, keep it as typed so it doesn't drift with FX
        transaction.price_entered = updates.price_of_one
        transaction.currency_entered = current_user.currency.upper()
    if new_cad_price is not None:
        transaction.price_of_one = new_cad_price
    if updates.quantity:
        transaction.quantity = updates.quantity
    if updates.api_id:
        transaction.api_id = updates.api_id
    if "coin_id" in updates.model_fields_set:
        transaction.coin_id = updates.coin_id
    elif transaction.api_id != old_api_id:
        transaction.coin_id = None  # now a different asset, so the old coin no longer applies
    if transaction.asset_type != "crypto":
        transaction.coin_id = None  # only coins have a CoinGecko id
    if updates.created_at:
        transaction.created_at = updates.created_at  # already naive UTC and not in the future (schema)
    if "account_type" in updates.model_fields_set:
        transaction.account_type = updates.account_type  # an explicit null clears it; left out keeps it

    try:
        await session.flush()

        # replay the affected symbols: no selling more than owned (at any point in time, so moving a trade's date is
        # checked too), and sell profits follow the edited prices
        for symbol in {old_symbol, transaction.symbol}:
            if not await rebuild_symbol_ledger(session, current_user.id, symbol):
                await session.rollback()
                raise HTTPException(status_code=409, detail=OVERSOLD)
        # nor more than a sell's own account held (see account_split for the rule that keeps older data editable)
        after = await account_shortfalls(session, current_user.id, {old_symbol, transaction.symbol})
        if account_oversell_added(before, after):
            await session.rollback()
            raise HTTPException(status_code=409, detail=ACCOUNT_OVERSOLD)

        await session.commit()
    except StaleDataError:
        # deleted between loading it and saving (a very narrow window now, but still not a 500)
        await session.rollback()
        raise HTTPException(status_code=404, detail="Transaction not found")
    await session.refresh(transaction)
    return transaction


@router.get("/transactions")
async def return_holdings_with_filter(
        symbol: Optional[str] = Query(None),
        action: Optional[Literal["BUY", "SELL"]] = Query(None),
        start_date: Optional[datetime] = Query(None),
        end_date: Optional[datetime] = Query(None),
        # one of ACCOUNT_TYPES, or "UNSET" for trades with no account
        account_type: Optional[AccountFilter] = Query(None),

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
                "account_type": "TFSA" | ... | None,
                "created_at": trans.created_at.isoformat()
    Prices and profits are in the user's currency: as typed when typed in that currency, otherwise from CAD.
    """
    query = create_holding_filter(current_user.id, symbol, action, start_date, end_date, account_type)

    result = await session.execute(query.order_by(Transaction.created_at.desc()))
    result = result.scalars().all()
    await end_read(session)  # an exchange-rate refresh can be slow: don't hold a pooled connection meanwhile

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
    of the history would sell more than was owned, e.g. a backdated sell before the buy it needs. A new asset past
    MAX_SYMBOLS_PER_USER different ones, or a trade past MAX_TRANSACTIONS_PER_USER, is a 422.
    """
    # Prices are stored in CAD and converted on the way out, so convert what the user typed (in their currency) to CAD.
    # The typed price and currency are kept too, so the trade keeps showing exactly what was typed. A backdated trade
    # in USD / EUR is converted at the rate of its own date (to_cad_on_trade_date), which the ACB report relies on.
    await check_transaction_limit(session, current_user.id)
    await check_symbol_limit(session, current_user.id, data.api_id)
    # A new buy only adds shares, so it can't make a sale impossible: no per-account check (an untagged sell draws
    # from the largest account, and a buy that changes which one that is used to be refused as a "shortfall")
    check_accounts = data.action == "SELL"
    before = await account_shortfalls(session, current_user.id, {data.symbol}) if check_accounts else {}

    await end_read(session)  # nothing written yet; don't hold a connection while the rates (maybe Yahoo's) load
    rates = await get_all_conversion_rates()
    price_cad = await to_cad_on_trade_date(data.price_of_one, current_user.currency, data.created_at, rates)

    transaction = Transaction(
        action=data.action,
        profit=0,
        asset_type=data.asset_type,
        symbol=data.symbol,
        api_id=data.api_id,
        coin_id=data.coin_id if data.asset_type == "crypto" else None,
        price_of_one=price_cad,
        price_entered=data.price_of_one,
        currency_entered=current_user.currency.upper(),
        quantity=data.quantity,
        account_type=data.account_type,
        user_id=current_user.id
    )
    if data.created_at is not None:
        transaction.created_at = data.created_at  # already naive UTC and not in the future (schema)

    session.add(transaction)
    await session.flush()

    if not await rebuild_symbol_ledger(session, current_user.id, data.symbol):
        await session.rollback()
        raise HTTPException(status_code=409, detail=OVERSOLD)  # Error if you are trying to sell more than you have
    # a sell tagged with an account can't take more than that account (plus "not set" shares) held then
    if check_accounts and account_oversell_added(
            before, await account_shortfalls(session, current_user.id, {data.symbol})):
        await session.rollback()
        raise HTTPException(status_code=409, detail=ACCOUNT_OVERSOLD)

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
    await end_read(session)  # held since loading the user; the trades are read again after the exchange rates
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
    Holdings that no source has a price for are left out of all three and listed in `unpriced`. `has_trades` tells
    an empty chart for someone who sold everything apart from a brand new account.
    """
    now = datetime.now(timezone.utc)
    currency = current_user.currency

    has_trades = (await session.execute(
        select(Transaction.id).where(Transaction.user_id == current_user.id).limit(1))).first() is not None
    # The connection is given back before each wait on a price source (see end_read) and taken again for queries
    await end_read(session)
    holdings = await get_holdings_at_time(session,
                                          current_user.id,
                                          now,
                                          currency)  # returns dict which maps api_id to avg_price, quantity and type
    await end_read(session)

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
            "has_trades": has_trades,
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
        "has_trades": has_trades,
    }


@router.get("/prices/history")
async def get_price_history(
        symbol: Annotated[str, Query(min_length=1, max_length=64)],
        type: Annotated[Literal["stock", "crypto"], Query()],
        range: Literal["1D", "1W", "1M", "1Y", "5Y"],
        # crypto: the CoinGecko id (from search or the trades), so CoinGecko charts that exact coin
        coin_id: Annotated[Optional[str], Query(max_length=80, pattern=r"^[a-z0-9-]+$")] = None,

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    Get historical prices of that specific symbol/holding on specific ranges, to make a graph. For example lets say
    I want to see how much BTC has changed in price over the past day, I call get_price_history("BTC", "1D") and it
    returns all the data needed to generate a graph of its price.
    `source` says where the prices came from; when the data covers less than was asked for (CoinGecko's free plan
    stops at one year, so "5Y" is really "1Y") `covered_range` and `note` say so.
    Each user can ask PRICE_HISTORY_RATE_LIMIT times a minute (429 with Retry-After after that).
    """
    _check_user_rate(_price_history_times, current_user.id, PRICE_HISTORY_RATE_LIMIT, PRICE_HISTORY_RATE_WINDOW,
                     "You're loading charts very quickly. Please wait a moment and try again.")
    await end_read(session)  # nothing else is read from the database; don't hold a connection while Yahoo answers
    try:
        data, s = await get_history_of_prices(symbol, type, range, current_user.currency)
    except Exception:  # unknown ticker or the price source is down
        data, s = [], symbol

    source = "Yahoo Finance" if data else None
    covered = range
    if not data and type == "crypto":
        # Yahoo doesn't list every coin (e.g. PEPE), so fall back to CoinGecko (cached: its demo key is rate limited)
        try:
            data, covered = await get_coingecko_history(symbol, range, current_user.currency, coin_id)
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


MAX_HISTORY_DAYS = 3650  # 10 years: the longest chart Yahoo's weekly "MAX" history is read for


async def all_time_days(session: AsyncSession, user: User, now: datetime | None = None) -> int:
    """
    Days the "All" chart covers: back to the user's first trade, so backdated and imported history is included
    (it used to start at date_joined, which squashed years of imported trades into one day). With no trades it's the
    days since joining. At least 1, at most MAX_HISTORY_DAYS.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    first = (await session.execute(
        select(func.min(Transaction.created_at)).where(Transaction.user_id == user.id)
    )).scalar()
    start = first or user.date_joined
    if start is None:
        return 365
    if start.tzinfo is not None:  # stored as naive UTC, but be safe
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    # ceil, so the chart's first point is at or before the first trade
    days = -(-(now - start) // timedelta(days=1)) if now > start else 1
    return max(1, min(MAX_HISTORY_DAYS, days))


@router.get("/portfolio/history")
async def get_portfolio_history(
        # days (1 to 10 years), or "all" for the days since the user's first trade
        range: Annotated[str, Query(max_length=4, pattern=r"^(all|[0-9]{1,4})$")],

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user)
):
    """
    return a list of dictionaries which each have a time mapping to a string of time and also a value mapping to a float,
    to create a chart for frontend
    """
    if range == "all":
        days = await all_time_days(session, current_user)
    else:
        days = int(range)
        if not 1 <= days <= MAX_HISTORY_DAYS:
            raise HTTPException(status_code=422, detail=f"range must be 1 to {MAX_HISTORY_DAYS} days, or all")

    data = await get_portfolio_value_history(session, current_user.id, days, current_user.currency)

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

# Every chart request can reach Yahoo (and CoinGecko for coins Yahoo lacks), cached or not, so it's limited per user
# too: plenty for flipping through ranges and holdings, not enough for a script to hammer the providers.
PRICE_HISTORY_RATE_LIMIT = 60
PRICE_HISTORY_RATE_WINDOW = 60  # seconds
_price_history_times: dict = {}  # {user id: deque of the times of their recent /prices/history requests}


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


def _check_user_rate(times_by_user: dict, user_id, limit: int, window: float, message: str) -> None:
    """
    Sliding-window limit per user, in memory: count one request, or raise a 429 (with Retry-After) when the user
    already made `limit` in the last `window` seconds. `times_by_user` is {user id: deque of request times}.
    """
    now = time.monotonic()
    recent = times_by_user.get(user_id)
    if recent is None:
        if len(times_by_user) >= 10_000:  # forget users with nothing left in their window, so this stays small
            idle = [uid for uid, times in times_by_user.items() if not times or now - times[-1] >= window]
            for uid in idle:
                del times_by_user[uid]
        recent = times_by_user[user_id] = deque()
    while recent and now - recent[0] >= window:
        recent.popleft()
    if len(recent) >= limit:
        retry = max(1, int(window - (now - recent[0])) + 1)  # when the oldest request leaves the window
        raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(retry)})
    recent.append(now)


def _check_search_rate(user_id) -> None:
    """Count one new search for the user, or raise a 429 when they started too many in the last minute."""
    _check_user_rate(_search_times, user_id, SEARCH_RATE_LIMIT, SEARCH_RATE_WINDOW,
                     "You're searching very quickly. Please wait a minute and try again.")


def clean_search_query(asset: str) -> str:
    asset = asset.strip()
    if len(asset) > SEARCH_QUERY_MAX_LENGTH:
        raise HTTPException(status_code=422, detail=f"Search for {SEARCH_QUERY_MAX_LENGTH} characters or fewer, "
                                                    "e.g. a ticker like AAPL or a coin like BTC.")
    return asset


# TwelveData lists the same company on many exchanges; only US and Canadian listings are kept (the app prices
# stocks from Yahoo and promises "US and Canadian stocks"). The exchange is returned with each result so SHOP (NYSE)
# and SHOP.TO (TSX) can be told apart.
SEARCH_COUNTRIES = {"United States": "US", "Canada": "Canada"}
STOCK_SEARCH_RESULTS = 6
STOCK_SEARCH_CANDIDATES = 30  # unique listings kept per term, so "SHOP.TO" can be picked out of "SHOP"'s matches


def yahoo_listing(result: dict) -> str | None:
    """
    Yahoo's ticker for a TwelveData match, or None if it isn't a US or Canadian listing the app can price:
    US "BRK.B" -> "BRK-B"; TSX "SHOP" -> "SHOP.TO", "DLR.U" -> "DLR-U.TO"; TSXV -> ".V", NEO / Cboe Canada -> ".NE",
    CSE -> ".CN". Same mapping as the CSV import (services/imports.py), so a searched and an imported trade match.
    """
    symbol = str(result.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    country = result.get("country")
    if country == "United States":
        return yahoo_class_share(symbol)
    if country == "Canada":
        # the MIC (XTSE, XTSX, NEOE, XCNQ) is the most precise; the exchange name (TSX, TSXV, NEO, CSE) is the backup
        for exchange in (result.get("mic_code"), result.get("exchange")):
            if exchange:
                ticker = listed_symbol(symbol, str(exchange))
                if ticker.endswith(CANADIAN_SUFFIXES):
                    return ticker
    return None  # another country, or a Canadian exchange we don't know Yahoo's suffix for


def split_listing_query(query: str) -> tuple[str, str | None]:
    """
    What to ask TwelveData for, and the Canadian suffix the user typed, if any. TwelveData knows "SHOP", not
    "SHOP.TO", and writes share classes with a dot: "SHOP.TO" -> ("SHOP", ".TO"), "DLR-U.TO" -> ("DLR.U", ".TO"),
    "BRK-B" -> ("BRK.B", None).
    """
    base, dot, suffix = query.rpartition(".")
    wanted = f".{suffix}" if dot and base else None
    if wanted not in CANADIAN_SUFFIXES:
        base, wanted = query, None
    return base.replace("-", "."), wanted


async def find_stock_listings(term: str, user_id=None) -> list[dict]:
    """
    Unique US and Canadian stocks / ETFs matching `term` as {"symbol" (Yahoo ticker), "name", "exchange",
    "country"}, in TwelveData's relevance order, from its symbol search (1 credit; cached per term). Raises a 503 when
    TwelveData returns an error (usually the per-minute credit limit) so the user sees that instead of "no results",
    and a 429 when the user starts too many new searches.
    """
    cached = _cache_get(_stock_search_cache, term, STOCK_SEARCH_TTL)
    if cached is not None:
        return cached
    if user_id is not None:
        _check_search_rate(user_id)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.twelvedata.com/symbol_search",
                # more rows than the default 30: a popular ticker's listings on other continents came first and pushed
                # the Canadian one out
                params={"symbol": term, "outputsize": 120, "show_plan": True, "apikey": os.getenv("API_KEY")}
            )
        body = response.json()
    except (httpx.HTTPError, ValueError):  # network errors, timeouts, a non-JSON body (e.g. a proxy's HTML page)
        raise HTTPException(status_code=503, detail="Stock search is temporarily unavailable")

    # errors come back as {"code": 429, "status": "error", "message": ...} with no "data" key
    if not isinstance(body, dict) or body.get("status") == "error" or "data" not in body:
        code = body.get("code") if isinstance(body, dict) else None
        if code == 429 or response.status_code == 429:
            raise HTTPException(status_code=503,
                                detail="Stock search is busy right now. Please try again in a minute.")
        raise HTTPException(status_code=503, detail="Stock search is temporarily unavailable")

    matches, seen = [], set()
    for result in body["data"]:
        if not isinstance(result, dict) or result.get("instrument_type") not in ("Common Stock", "ETF"):
            continue
        ticker = yahoo_listing(result)
        if ticker is None or ticker in seen:  # another country, or a duplicate listing (e.g. other US venues)
            continue
        seen.add(ticker)
        matches.append({
            "symbol": ticker,
            "name": result.get("instrument_name") or "",
            "exchange": str(result.get("exchange") or ""),
            "country": SEARCH_COUNTRIES[result["country"]],
        })
        if len(matches) == STOCK_SEARCH_CANDIDATES:
            break

    _cache_put(_stock_search_cache, term, matches)
    return matches


async def listing_to_cad(match: dict) -> float | None:
    """CAD per unit of the listing's price. US listings trade in USD; a Canadian one asks Yahoo (DLR-U.TO is USD)."""
    currency = "USD" if match["country"] == "US" else await get_ticker_currency(match["symbol"])
    return await get_native_to_cad_factor(currency)


@router.get("/assets/search/stock")
async def search_assets_stocks(asset: Annotated[str, Query(max_length=200)],
                               current_user: User = Depends(current_active_user),
                               session: AsyncSession = Depends(get_async_session)):
    """
    Search US and Canadian stocks and ETFs. For example "AAP" returns up to 6 items like AAPL, AAPD, ..., and "SHOP"
    both SHOP (NYSE) and SHOP.TO (TSX), with their name, exchange, price and daily change in the user's currency.
    A typed exchange suffix ("SHOP.TO", "ABC.V") keeps only that exchange's listings. Matches come from TwelveData,
    prices from Yahoo (free) in the listing's currency, converted the same way as the holdings.
    """
    await end_read(session)  # the session only loaded the user; don't hold its connection while TwelveData answers
    asset = clean_search_query(asset).upper()
    if not asset:
        return []

    term, wanted_suffix = split_listing_query(asset)
    matches = await find_stock_listings(term, current_user.id)
    if wanted_suffix:
        matches = [m for m in matches if m["symbol"].endswith(wanted_suffix)]
    matches = matches[:STOCK_SEARCH_RESULTS]
    if not matches:
        return []

    rates = await get_all_conversion_rates()
    conversion = get_conversion_factor(rates, current_user.currency)

    quotes, to_cad = await asyncio.gather(
        get_latest_stock_quotes([m["symbol"] for m in matches]),
        asyncio.gather(*[listing_to_cad(m) for m in matches]),
    )
    if not quotes:
        raise HTTPException(status_code=503, detail="Stock prices are temporarily unavailable")

    final = []
    for match, factor in zip(matches, to_cad):  # keep TwelveData's relevance order
        symbol = match["symbol"]
        quote = quotes.get(symbol)
        if quote is None or factor is None:  # no prices on Yahoo (new / delisted), or an unknown listing currency
            continue
        native_to_user = factor * conversion
        change = quote["close"] - quote["previous_close"]
        final.append({
            "api_id": symbol,
            "symbol": symbol,
            "name": match["name"],  # company or fund name, shown under the ticker
            "exchange": match["exchange"],  # "NYSE", "TSX", ...: tells SHOP and SHOP.TO apart
            "country": match["country"],  # "US" or "Canada"
            "type": "stock",
            "image": "",
            "price": quote["close"] * native_to_user,
            "change": change * native_to_user,
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

    # without a key the header is left out (httpx refuses a None header value, which used to crash with a 500)
    key = os.getenv("API_KEY_COINEGECKO")
    headers = {"x-cg-demo-api-key": key} if key else {}
    unavailable = HTTPException(status_code=503, detail="Crypto prices are temporarily unavailable")

    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            res = await client.get("https://api.coingecko.com/api/v3/search", params={"query": query})
            if res.status_code != 200:  # rate limited or down: don't cache it as "no results"
                raise unavailable

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
    except (httpx.HTTPError, ValueError):  # network errors, timeouts, a non-JSON body
        raise unavailable

    if not isinstance(coins, list):  # coingecko returns an error dict when rate limited
        raise HTTPException(status_code=503, detail="Crypto prices are temporarily unavailable")

    _cache_put(_crypto_search_cache, query, coins)
    return coins


@router.get("/assets/search/crypto")
async def search_assets_crypto(asset: Annotated[str, Query(max_length=200)],
                               current_user: User = Depends(current_active_user),
                               session: AsyncSession = Depends(get_async_session)):
    """
    Use coingecko api to fetch crypto prices of assets, similar to the route above in format.
    """
    await end_read(session)  # as above: no connection held while CoinGecko answers
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
    if not await user_manager.check_password(user, password):
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
        current_user, hashed_password=await user_manager.hash_password(body.new_password), has_password=True,
    )
    await send_notice_email(
        str(user.email), "Your Zenith password was changed",
        "The password for your Zenith account was just changed and your other devices were signed out.\n\n"
        "If this wasn't you, use \"Forgot password\" on the login page right away to choose a new one.\n",
    )
    return {"message": "Password changed", "access_token": await strategy.write_token(user), "token_type": "bearer"}


@router.post("/user/token")
async def renew_token(
        request: Request,
        token: str = Depends(bearer_transport.scheme),
        current_user: User = Depends(current_active_user),
        strategy=Depends(auth_backend.get_strategy),
):
    """
    A fresh 30-day token for a still-valid app one. The iPhone app renews its token while it's in use, so a daily
    user is never sent back to the login screen (and the Face ID lock they turned on stays on). Only an app sign in
    asking as the app can renew: a website token (1 hour) could otherwise be turned into a 30-day one and kept
    alive for good. A revoked token can't be renewed either: those fail current_active_user.
    """
    if not (is_app_token(token) and is_app_request(request)):
        raise HTTPException(status_code=403, detail="Only the iPhone app's sign in can be renewed.")
    return {"access_token": await strategy.write_token(current_user), "token_type": "bearer"}


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
