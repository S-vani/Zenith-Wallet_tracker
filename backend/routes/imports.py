"""
CSV export and import of trades. Export is Zenith's own template; import reads that template and broker exports
(Wealthsimple, Questrade) in two steps: a preview that saves nothing, then the import of the rows the user accepted,
validated again here and saved all together or not at all. Parsing lives in backend/services/imports.py.
"""
from datetime import datetime, timezone
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import Transaction, User
from backend.routes.assets import (MAX_SYMBOLS_PER_USER, MAX_TRANSACTIONS_PER_USER, TOO_MANY_SYMBOLS,
                                   _check_user_rate)
from backend.schemas.assets import AccountType
from backend.services import asset_services
from backend.services.asset_services import (LEDGER_ORDER, as_quantity, end_read, get_conversion_factor,
                                             rebuild_symbol_ledger, sell_tolerance)
from backend.services.imports import (MAX_ROWS, FileError, ImportRow, RowError, clean_trade, export_row,
                                      mark_duplicates, parse_csv, summarize, template_csv, write_csv)

router = APIRouter()

# Parsing a 2 MB file and matching it against 20,000 trades is real work, and nobody imports more than a handful of
# files in an hour; this keeps a script from using the endpoints as a CPU sink. Counted separately, so previewing a
# few files doesn't use up the imports.
IMPORT_RATE_LIMIT = 10
IMPORT_RATE_WINDOW = 3600  # seconds
_preview_times: dict = {}  # {user id: deque of the times of their recent previews}
_import_times: dict = {}  # {user id: deque of the times of their recent imports}
RATE_MESSAGE = "You've imported a lot of files in the last hour. Please wait a while and try again."


def _csv_response(body: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Cache-Control": "no-store"},  # someone's whole trade history: never kept by a shared cache
    )


@router.get("/transactions/export")
async def export_transactions(
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Every trade of the user as a CSV in Zenith's template (oldest first), so their data is never locked in here.
    Prices are as typed (price + the currency typed in), or the stored CAD price for older trades. The file reads
    back in through the import below.
    """
    result = await session.execute(
        select(Transaction).where(Transaction.user_id == current_user.id).order_by(*LEDGER_ORDER))
    body = write_csv([export_row(trade) for trade in result.scalars().all()])
    today = datetime.now(timezone.utc).date().isoformat()
    return _csv_response(body, f"zenith-trades-{today}.csv")


@router.get("/transactions/import/template")
async def import_template(current_user: User = Depends(current_active_user)):
    """An empty Zenith template (the header and two example rows) for people filling one in by hand."""
    return _csv_response(template_csv(), "zenith-import-template.csv")


class ImportPreviewRequest(BaseModel):
    csv: str
    format: Literal["auto", "zenith", "wealthsimple", "questrade"] = "auto"
    # used for rows whose file doesn't say which account they were in
    default_account_type: Optional[AccountType] = None


class ImportRowIn(BaseModel):
    """A row as the preview returned it (extra fields like status and message are ignored)."""
    model_config = ConfigDict(extra="ignore")

    line: Optional[int] = None
    date: Optional[str] = Field(default=None, max_length=64)
    action: Optional[str] = Field(default=None, max_length=16)
    asset_type: Optional[str] = Field(default=None, max_length=16)
    symbol: Optional[str] = Field(default=None, max_length=64)
    quantity: Optional[Union[float, str]] = None
    price: Optional[Union[float, str]] = None
    currency: Optional[str] = Field(default=None, max_length=8)
    account_type: Optional[str] = Field(default=None, max_length=32)
    coin_id: Optional[str] = Field(default=None, max_length=80)


class ImportCommitRequest(BaseModel):
    rows: list[ImportRowIn]


async def _rates_or_none() -> dict | None:
    """Exchange rates for comparing prices across currencies, or None if there are none (duplicates then only match
    in the same currency); a preview shouldn't fail just for that."""
    try:
        return await asset_services.get_all_conversion_rates()
    except HTTPException:
        return None


@router.post("/transactions/import/preview")
async def preview_import(
        body: ImportPreviewRequest,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Read a CSV (Zenith template, Wealthsimple activities export or Questrade account activity) and say what each
    row would become, without saving anything: "ok", "duplicate" (matches a trade the user already has) or "error"
    with a message. Buys and sells only; other activity (dividends, deposits, fees...) is counted as skipped.
    At most 2 MB (413) and MAX_ROWS rows (422); IMPORT_RATE_LIMIT previews per user per hour (429).
    """
    _check_user_rate(_preview_times, current_user.id, IMPORT_RATE_LIMIT, IMPORT_RATE_WINDOW, RATE_MESSAGE)
    try:
        parsed = parse_csv(body.csv, body.format, body.default_account_type)
    except FileError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))

    # duplicates are checked against the user's trades; rates (cached) let a USD row match a trade saved in CAD
    await end_read(session)  # don't hold the connection if the rates need refreshing
    rates = await _rates_or_none()
    result = await session.execute(select(Transaction).where(Transaction.user_id == current_user.id))
    mark_duplicates(parsed.rows, result.scalars().all(), rates)

    return {
        "format_detected": parsed.format,
        "rows": [row.as_json() for row in parsed.rows],
        "summary": summarize(parsed),
    }


def _oversold_trade(trades) -> Optional[Transaction]:
    """The first sell in `trades` (in ledger order) that takes more than was owned at that moment."""
    owned = as_quantity(0)
    for trade in trades:
        quantity = as_quantity(trade.quantity)
        if str(trade.action) == "BUY":
            owned += quantity
        elif quantity > owned + sell_tolerance(owned):
            return trade
        else:
            owned = max(as_quantity(0), owned - quantity)
    return None


@router.post("/transactions/import")
async def commit_import(
        body: ImportCommitRequest,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Save the rows the user accepted from the preview. Every row is validated again (the browser's copy is never
    trusted), prices are stored like a manual trade (as typed, plus CAD at today's rate), and all rows go in one
    database transaction: if any symbol's history would sell more than was owned, nothing is saved (409 naming the
    symbol and line). MAX_TRANSACTIONS_PER_USER and MAX_SYMBOLS_PER_USER count the whole batch (422).
    """
    _check_user_rate(_import_times, current_user.id, IMPORT_RATE_LIMIT, IMPORT_RATE_WINDOW, RATE_MESSAGE)
    if not body.rows:
        raise HTTPException(status_code=422, detail="There are no trades to import.")
    if len(body.rows) > MAX_ROWS:
        raise HTTPException(status_code=422, detail=f"You can import up to {MAX_ROWS:,} trades at a time.")

    rows = []
    for index, data in enumerate(body.rows):
        row = ImportRow(line=data.line if data.line is not None else index + 1)
        try:
            clean_trade(row, data.model_dump(), default_account=None, strict_account=True)
        except RowError as err:
            raise HTTPException(status_code=422, detail=f"Line {row.line}: {err}. Nothing was imported.")
        rows.append(row)

    # rates first, while no connection is held (see end_read); nothing is written before this point
    await end_read(session)
    rates = await asset_services.get_all_conversion_rates()

    count = await session.execute(select(func.count()).select_from(Transaction)
                                  .where(Transaction.user_id == current_user.id))
    if count.scalar_one() + len(rows) > MAX_TRANSACTIONS_PER_USER:
        raise HTTPException(status_code=422, detail=f"You can log up to {MAX_TRANSACTIONS_PER_USER:,} trades, and "
                                                    "this import would go past that. Import fewer rows.")
    known = await session.execute(select(Transaction.api_id).where(Transaction.user_id == current_user.id)
                                  .distinct())
    assets = set(known.scalars().all()) | {row.symbol for row in rows}
    if len(assets) > MAX_SYMBOLS_PER_USER:
        raise HTTPException(status_code=422, detail=TOO_MANY_SYMBOLS)

    added = []  # (trade, its line in the file)
    for row in rows:
        price = float(row.price)
        transaction = Transaction(
            action=row.action,
            profit=0,
            asset_type=row.asset_type,
            symbol=row.symbol,
            api_id=row.symbol,  # what search would have given: the ticker, or a coin's lowercase symbol
            coin_id=row.coin_id if row.asset_type == "crypto" else None,
            # stored in CAD like every trade, kept as typed too so it never drifts with exchange rates
            price_of_one=price / get_conversion_factor(rates, row.currency),
            price_entered=price,
            currency_entered=row.currency,
            quantity=float(row.quantity),
            account_type=row.account_type,
            user_id=current_user.id,
            created_at=row.date,
        )
        session.add(transaction)
        added.append((transaction, row.line))
    await session.flush()
    line_of = {transaction.id: line for transaction, line in added}  # ids are given out by the flush

    for symbol in sorted({row.symbol for row in rows}):
        if await rebuild_symbol_ledger(session, current_user.id, symbol):
            continue
        history = await session.execute(select(Transaction).where(Transaction.user_id == current_user.id,
                                                                  Transaction.symbol == symbol)
                                        .order_by(*LEDGER_ORDER))
        culprit = _oversold_trade(history.scalars().all())
        name = symbol.upper()
        if culprit is not None and culprit.id in line_of:
            where = f"the sell on line {line_of[culprit.id]} is more {name} than you owned at that point"
        elif culprit is not None:
            day = culprit.created_at.date().isoformat()
            where = f"your existing {name} sell on {day} would be short (the file sells some of it earlier)"
        else:
            where = f"your {name} history would sell more than you owned"
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Nothing was imported: {where}. Check the file's {name} "
                                                    "buys and sells (and their dates), then try again.")

    await session.commit()
    return {"imported": len(rows)}
