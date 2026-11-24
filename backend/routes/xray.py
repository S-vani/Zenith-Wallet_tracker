"""GET /portfolio/xray: Portfolio X-Ray (services/xray.py), limited per user because it reads a year of prices."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import User
from backend.routes.assets import _check_user_rate
from backend.services.alerts import money
from backend.services.xray import build_xray, cached_xray

router = APIRouter(tags=["portfolio"])

XRAY_RATE_LIMIT = 20  # per user per hour; a cached answer within 30 minutes is free
XRAY_RATE_WINDOW = 60 * 60
_xray_times: dict = {}


@router.get("/portfolio/xray")
async def portfolio_xray(session: AsyncSession = Depends(get_async_session),
                         user: User = Depends(current_active_user)):
    """
    {empty, currency, total, score {score, label, reasons}, concentration, holdings [{symbol, weight, beta}],
    exposure {sectors, regions, companies}, risk {volatility, max_drawdown, beta, ...}, stress_tests, findings,
    unpriced, limitations}. Weights are fractions of the priced total.
    """
    cached = cached_xray(user)
    if cached:
        return cached
    _check_user_rate(_xray_times, user.id, XRAY_RATE_LIMIT, XRAY_RATE_WINDOW,
                     "You've refreshed the X-Ray a lot this hour. Please try again a little later.")
    return await build_xray(session, user, lambda value: money(value, user.currency))
