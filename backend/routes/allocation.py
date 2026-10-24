from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User
from backend.services.allocation import build_allocation, replay_accounts
from backend.services.asset_services import LEDGER_ORDER, end_read, get_curr_holdings_prices, get_holdings_at_time

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio/allocation")
async def portfolio_allocation(
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    How the portfolio's current value splits up, in the user's currency:
    {
    "currency": "CAD", "total": float, "unpriced": [api_id, ...],
    "by_asset_type": [{"key": "stock" | "crypto", "value", "weight"}],
    "by_account": [{"key": "TFSA" | ... | "UNSET", "value", "weight"}],
    "by_holding": [{"symbol", "asset_type", "value", "weight"}],
    "by_currency": [{"key": listing currency ("CAD", "USD", ...) or "CRYPTO", "value", "weight"}]
    }
    Every list is sorted largest first and its weights add up to 1 (0 with nothing priced). Values are quantity x
    the same current price /holdings uses, so `total` is the dashboard's portfolio value; holdings without a price
    are only listed in `unpriced`. Accounts replay each holding's trades per account (see replay_accounts).
    """
    now = datetime.now(timezone.utc)
    currency = current_user.currency

    # The connection is given back before each wait on a price source (see end_read) and taken again for queries
    await end_read(session)
    holdings = await get_holdings_at_time(session, current_user.id, now, currency)  # same holdings as /holdings
    trades = await session.execute(
        select(Transaction)
        .where(Transaction.user_id == current_user.id, Transaction.created_at <= now)
        .order_by(*LEDGER_ORDER)
    )
    accounts = replay_accounts(trades.scalars().all())
    await end_read(session)

    prices = await get_curr_holdings_prices(holdings, currency) if holdings else {}
    return build_allocation(holdings, accounts, prices, currency)
