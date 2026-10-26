"""
Canadian capital gains (ACB) report. Built only from the stored trades (prices already in CAD): no price or
exchange-rate source is called, so there's nothing slow to wait on and no end_read needed. The maths is in
backend/services/reports.py.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User
from backend.services.asset_services import LEDGER_ORDER
from backend.services.reports import capital_gains, report_csv, taxable_sale_years

router = APIRouter(prefix="/reports", tags=["reports"])

FIRST_YEAR = 2000


class Sale(BaseModel):
    id: str
    date: str  # YYYY-MM-DD, the trade date in Toronto
    settlement_date: str  # decides the tax year (stocks T+1 / T+2 business days, crypto the trade date)
    symbol: str
    asset_type: str
    quantity: float
    proceeds: float
    acb: float
    outlays: float
    gain: float
    currency_entered: Optional[str]
    foreign_currency: bool
    superficial_loss: bool
    superficial_amount: float  # the part of the loss CRA may deny (CRA's formula, 0 when not flagged), positive
    acb_may_rise: bool  # an earlier possible superficial loss would be added to this sale's ACB
    interlisted: bool  # also traded under its other listing (SHOP / SHOP.TO): see the report's warnings
    oversold: bool
    notes: list[str]


class Totals(BaseModel):
    proceeds: float
    acb: float
    net: float
    gains: float
    losses: float
    possibly_superficial: float  # how much of `losses` is possibly superficial (flagged, still included)
    taxable_at_50pct: float


class CapitalGainsReport(BaseModel):
    year: int
    currency: str
    sales: list[Sale]
    totals: Totals
    warnings: list[str]  # e.g. interlisted shares kept in separate ACB pools
    notes: list[str]
    superficial_loss_url: str


class ReportYears(BaseModel):
    years: list[int]


def _check_year(year: int) -> int:
    # a stock sold on the last trading day of the year settles (and counts) in the next one
    current = datetime.now(timezone.utc).year + 1
    if not FIRST_YEAR <= year <= current:
        raise HTTPException(status_code=422, detail=f"Choose a year between {FIRST_YEAR} and {current}.")
    return year


async def _all_trades(session: AsyncSession, user: User):
    # every year and every account: ACB carries over from earlier years, and registered buys still count for
    # the superficial loss check
    result = await session.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(*LEDGER_ORDER))
    return result.scalars().all()


@router.get("/capital-gains/years", response_model=ReportYears)
async def capital_gains_years(
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """The tax years (by settlement date) with a sale in a non-registered (or not set) account, newest first."""
    return {"years": taxable_sale_years(await _all_trades(session, current_user))}


@router.get("/capital-gains", response_model=CapitalGainsReport)
async def capital_gains_report(
        year: int = Query(),
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """Taxable sales settling in one year with proceeds, ACB and gain in CAD, the year's totals and notes."""
    year = _check_year(year)
    return capital_gains(await _all_trades(session, current_user), year)


@router.get("/capital-gains.csv")
async def capital_gains_csv(
        year: int = Query(),
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """The same report as a CSV download (one row per sale plus a totals row)."""
    year = _check_year(year)
    report = capital_gains(await _all_trades(session, current_user), year)
    return Response(
        content=report_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="zenith-capital-gains-{year}.csv"',
            "Cache-Control": "no-store",  # personal tax data: no shared cache should keep a copy
        },
    )
