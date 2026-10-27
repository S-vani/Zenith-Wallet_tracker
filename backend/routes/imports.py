"""
CSV export and import of trades. Export is Zenith's own template; import reads that template and broker exports
(Wealthsimple, Questrade) in two steps: a preview that saves nothing, then the import of the rows the user accepted,
validated again here and saved all together or not at all. Parsing lives in backend/services/imports.py.
"""
import asyncio
import time
import uuid
from collections import deque
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
from backend.services.asset_services import (LEDGER_ORDER, as_quantity, cad_price_on, end_read, fx_history,
                                             needs_trade_date_rate, rebuild_symbol_ledger, sell_tolerance)
from backend.services.imports import (MAX_ROWS, FileError, ImportRow, RowError, check_against_saved, clean_trade,
                                      export_row, mark_duplicates, parse_csv, resolve_tsx_listings, summarize,
                                      template_csv, write_csv)

router = APIRouter()

# Parsing a 2 MB file and matching it against 20,000 trades is real work, and nobody imports more than a handful of
# files in an hour; these keep a script from using the endpoints as a CPU sink. Counted separately, so previewing a
# few files doesn't use up the imports. Every option change on the page is a new preview, hence the higher number.
PREVIEW_RATE_LIMIT = 30
IMPORT_RATE_LIMIT = 10  # imports that went through; a refused one (409, 422) doesn't count, see COMMIT_ATTEMPT_LIMIT
COMMIT_ATTEMPT_LIMIT = 60  # every import request, refused or not
IMPORT_RATE_WINDOW = 3600  # seconds
_preview_times: dict = {}  # {user id: deque of the times of their recent previews}
_import_times: dict = {}  # {user id: deque of the times of their recent imports that went through}
_commit_attempts: dict = {}  # {user id: deque of the times of their recent import requests}
PREVIEW_RATE_MESSAGE = "You've previewed a lot of files in the last hour. Please wait a while and try again."
RATE_MESSAGE = "You've imported a lot of files in the last hour. Please wait a while and try again."

# An import can outlast the app's request timeout while the server still saves it, and the app's retry would then
# import everything twice. The page sends an id it made for this import; a repeat of a finished one gets the first
# answer back instead of importing again. In memory, like the rate limits (one server process).
IMPORT_ID_TTL = 3600  # seconds
IMPORT_ID_LIMIT = 10_000
_finished_imports: dict = {}  # {(user id, import id): (time.monotonic(), response)}
_running_imports: dict = {}  # {(user id, import id): asyncio.Event set when that import ends}


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
    # the file only had a day: duplicates then match any time that day (see DATE_ONLY_MATCH)
    date_only: bool = False
    action: Optional[str] = Field(default=None, max_length=16)
    asset_type: Optional[str] = Field(default=None, max_length=16)
    symbol: Optional[str] = Field(default=None, max_length=64)
    quantity: Optional[Union[float, str]] = None
    price: Optional[Union[float, str]] = None
    currency: Optional[str] = Field(default=None, max_length=8)
    account_type: Optional[str] = Field(default=None, max_length=32)
    coin_id: Optional[str] = Field(default=None, max_length=80)
    # the preview called it a duplicate and the user ticked it: import it anyway
    include_duplicate: bool = False


class ImportCommitRequest(BaseModel):
    rows: list[ImportRowIn]
    # made by the page once per preview; a retry of an import that already went through returns its first answer
    import_id: Optional[uuid.UUID] = None


async def _rates_or_none() -> dict | None:
    """Exchange rates for comparing prices across currencies, or None if there are none (duplicates then only match
    in the same currency); a preview shouldn't fail just for that."""
    try:
        return await asset_services.get_all_conversion_rates()
    except HTTPException:
        return None


async def _saved_trades(session: AsyncSession, user_id) -> list:
    """The user's trades as plain rows with just what duplicate and oversell checks need (safe to use in a thread)."""
    result = await session.execute(
        select(Transaction.id, Transaction.symbol, Transaction.action, Transaction.created_at, Transaction.quantity,
               Transaction.price_of_one, Transaction.price_entered, Transaction.currency_entered)
        .where(Transaction.user_id == user_id))
    return list(result.all())


@router.post("/transactions/import/preview")
async def preview_import(
        body: ImportPreviewRequest,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Read a CSV (Zenith template, Wealthsimple activities export or Questrade account activity) and say what each
    row would become, without saving anything: "ok", "duplicate" (matches a trade the user already has) or "error"
    with a message, including rows the import would refuse for selling more than was owned at the time (the saved
    trades and the file's ready rows are replayed in the order the import uses). Buys and sells only; other activity
    (dividends, deposits, fees...) is counted as skipped. At most 2 MB (413) and MAX_ROWS rows (422);
    PREVIEW_RATE_LIMIT previews per user per hour (429).
    """
    _check_user_rate(_preview_times, current_user.id, PREVIEW_RATE_LIMIT, IMPORT_RATE_WINDOW, PREVIEW_RATE_MESSAGE)
    try:
        # CPU work in a thread, so one big file doesn't stall every other request on this server
        parsed = await asyncio.to_thread(parse_csv, body.csv, body.format, body.default_account_type)
    except FileError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))

    await resolve_tsx_listings(parsed.rows)  # "XEQT" in CAD -> "XEQT.TO" when Yahoo knows it
    # duplicates are checked against the user's trades; rates (cached) let a USD row match a trade saved in CAD
    await end_read(session)  # don't hold the connection if the rates need refreshing
    rates = await _rates_or_none()
    existing = await _saved_trades(session, current_user.id)
    await end_read(session)
    await asyncio.to_thread(check_against_saved, parsed.rows, existing, rates)

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


def _clean_commit_rows(data_rows: list[ImportRowIn]) -> list[tuple[ImportRow, bool]]:
    """Every row validated again like the preview did ([(row, include even if a duplicate)]); a bad one is a 422."""
    rows = []
    for index, data in enumerate(data_rows):
        row = ImportRow(line=data.line if data.line is not None else index + 1)
        try:
            clean_trade(row, data.model_dump(), default_account=None, strict_account=True)
        except (RowError, ValueError, ArithmeticError) as err:
            reason = str(err) if isinstance(err, RowError) else "this row couldn't be read"
            raise HTTPException(status_code=422, detail=f"Line {row.line}: {reason}. Nothing was imported.")
        row.date_only = row.date_only or data.date_only
        rows.append((row, data.include_duplicate))
    return rows


def _check_import_quota(user_id) -> None:
    """429 when the user already finished IMPORT_RATE_LIMIT imports in the window (counted by _count_import)."""
    recent = _import_times.get(user_id)
    now = time.monotonic()
    while recent and now - recent[0] >= IMPORT_RATE_WINDOW:
        recent.popleft()
    if recent and len(recent) >= IMPORT_RATE_LIMIT:
        retry = max(1, int(IMPORT_RATE_WINDOW - (now - recent[0])) + 1)
        raise HTTPException(status_code=429, detail=RATE_MESSAGE, headers={"Retry-After": str(retry)})


def _count_import(user_id) -> None:
    """Count an import that went through (never raises: it's already saved)."""
    now = time.monotonic()
    if user_id not in _import_times and len(_import_times) >= 10_000:  # forget users with nothing in their window
        for idle in [uid for uid, times in _import_times.items() if not times or now - times[-1] >= IMPORT_RATE_WINDOW]:
            del _import_times[idle]
    _import_times.setdefault(user_id, deque()).append(now)


def _remember_import(key, response: dict) -> None:
    now = time.monotonic()
    for old in [k for k, (at, _) in _finished_imports.items() if now - at >= IMPORT_ID_TTL]:
        del _finished_imports[old]
    while len(_finished_imports) >= IMPORT_ID_LIMIT:
        _finished_imports.pop(next(iter(_finished_imports)))
    _finished_imports[key] = (now, response)


def _finished(key) -> dict | None:
    done = _finished_imports.get(key)
    if done and time.monotonic() - done[0] < IMPORT_ID_TTL:
        return done[1]
    return None


@router.post("/transactions/import")
async def commit_import(
        body: ImportCommitRequest,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Save the rows the user accepted from the preview. Every row is validated again (the browser's copy is never
    trusted), prices are stored like a manual trade (as typed, plus CAD at the rate of the trade's date, see
    to_cad_on_trade_date; one rate history per currency serves the whole file), and all rows go in one
    database transaction: if any symbol's history would sell more than was owned, nothing is saved (409 naming the
    symbol and line). MAX_TRANSACTIONS_PER_USER and MAX_SYMBOLS_PER_USER count the whole batch (422).

    Rows that are already in the user's trades are skipped unless they're marked `include_duplicate` (so a retry, or
    the same file imported twice, adds nothing), and a request with the `import_id` of an import that already went
    through returns that import's answer without saving anything (the app retries after a timeout).
    Answers {"imported": n, "skipped_duplicates": m}.
    """
    key = (current_user.id, body.import_id) if body.import_id else None
    if key is None:
        return await _commit(body, session, current_user)

    # the same import twice at once (a retry while the first is still saving): the second waits for the first
    while key in _running_imports:
        await _running_imports[key].wait()
    if (done := _finished(key)) is not None:
        return done
    _running_imports[key] = asyncio.Event()
    try:
        response = await _commit(body, session, current_user)
        _remember_import(key, response)
        return response
    finally:
        _running_imports.pop(key).set()


async def _commit(body: ImportCommitRequest, session: AsyncSession, current_user: User) -> dict:
    _check_user_rate(_commit_attempts, current_user.id, COMMIT_ATTEMPT_LIMIT, IMPORT_RATE_WINDOW, RATE_MESSAGE)
    _check_import_quota(current_user.id)
    if not body.rows:
        raise HTTPException(status_code=422, detail="There are no trades to import.")
    if len(body.rows) > MAX_ROWS:
        raise HTTPException(status_code=422, detail=f"You can import up to {MAX_ROWS:,} trades at a time.")

    cleaned = await asyncio.to_thread(_clean_commit_rows, body.rows)

    # rates first, while no connection is held (see end_read); nothing is written before this point. Backdated
    # foreign rows use the rate of their own date: one Yahoo history per currency (fetched together) covers them all
    await end_read(session)
    rates = await asset_services.get_all_conversion_rates()
    currencies = sorted({row.currency for row, _ in cleaned if needs_trade_date_rate(row.currency, row.date)})
    histories = dict(zip(currencies, await asyncio.gather(*(fx_history(code) for code in currencies))))

    # duplicates again: a retry, or the same file in two tabs, must not add the trades a second time
    existing = await _saved_trades(session, current_user.id)
    await asyncio.to_thread(mark_duplicates, [row for row, _ in cleaned], existing, rates)
    rows = [row for row, include in cleaned if row.status == "ok" or include]
    skipped = len(cleaned) - len(rows)
    if not rows:
        _count_import(current_user.id)
        return {"imported": 0, "skipped_duplicates": skipped}

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
            price_of_one=cad_price_on(price, row.currency, row.date, rates, histories.get(row.currency)),
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
            day = asset_services.toronto_date(culprit.created_at).isoformat()  # the date the user sees, not UTC's
            where = f"your existing {name} sell on {day} would be short (the file sells some of it earlier)"
        else:
            where = f"your {name} history would sell more than you owned"
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Nothing was imported: {where}. Check the file's {name} "
                                                    "buys and sells (and their dates), then try again.")

    await session.commit()
    _count_import(current_user.id)
    return {"imported": len(rows), "skipped_duplicates": skipped}
