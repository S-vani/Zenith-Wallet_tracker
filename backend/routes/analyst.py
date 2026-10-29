"""GET /analyst: the market analyst report for a stock or coin (rules-based, cached, rate limited)."""
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyst import service
from backend.analyst.schema import AnalystReport
from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import User

router = APIRouter(tags=["analyst"])

SUPPORTED_CURRENCIES = ("CAD", "USD", "EUR")


@router.get("/analyst", response_model=AnalystReport)
async def market_analyst(
        symbol: Annotated[str, Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-^=]+$")],
        type: Literal["stock", "crypto"],
        coin_id: Annotated[Optional[str], Query(max_length=80, pattern=r"^[a-z0-9-]+$")] = None,
        refresh: bool = False,

        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Built-in market analyst: a structured outlook (sentiment, insights, bull/base/bear scenarios, what to watch,
    main risk, bottom line) for one stock or crypto, calculated from market data. Cached per asset and currency.
    """
    currency = current_user.currency if current_user.currency in SUPPORTED_CURRENCIES else "CAD"
    return await service.get_report(session, str(current_user.id), symbol.strip(), type, currency,
                                    coin_id=coin_id, refresh=refresh)
