"""
Orchestrates a report: cache lookup -> rate limits -> data collection -> rules engine -> optional Gemini rewording.

Reports are cached in the database (so they survive restarts) per asset and currency. Users can force a refresh,
but only once the cached report is a few minutes old, and each user can only trigger a limited number of fresh
reports per hour, as can all users together (cache hits are free).
"""
import asyncio
import json
import math
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyst import data as market_data
from backend.analyst.engine import build_report
from backend.analyst.gemini import reword
from backend.analyst.schema import AnalystReport
from backend.db_models.assets import Base

CACHE_TTL = {"stock": timedelta(hours=1), "crypto": timedelta(minutes=30)}  # crypto trades around the clock
REFRESH_COOLDOWN = timedelta(minutes=5)
GENERATIONS_PER_HOUR = 30  # fresh (uncached) reports a single user can trigger per hour
# fresh reports across all users per hour: each one costs several Yahoo / CoinGecko calls (CoinGecko's demo key
# allows about 30 a minute) and maybe a Gemini call, so many accounts together can't exhaust the providers
GLOBAL_GENERATIONS_PER_HOUR = 120
COLLECT_TIMEOUT_SECONDS = 30
WINDOW_SECONDS = 3600

USER_LIMIT_MESSAGE = "You've reached the hourly limit for new analyses. Please try again later."
GLOBAL_LIMIT_MESSAGE = ("The market analyst is very busy right now. Please try again in a few minutes, "
                        "or open an asset that was analysed recently.")


class AnalystCache(Base):
    __tablename__ = "analyst_reports"

    key = Column(String, primary_key=True)  # e.g. "stock:NVDA:CAD"
    payload = Column(Text, nullable=False)  # AnalystReport as JSON
    created_at = Column(DateTime, nullable=False)


# One generation per asset at a time. An entry only lives while someone holds or waits for it (see _asset_lock),
# so one lock per asset ever analysed doesn't pile up in memory.
_locks: dict[str, asyncio.Lock] = {}
_lock_users: dict[str, int] = {}
_user_generations: dict[str, deque] = defaultdict(deque)
_global_generations: deque = deque()  # times of every fresh report in the last hour, all users together


def cache_key(asset_type: str, symbol: str, currency: str, coin_id: Optional[str]) -> str:
    ident = (coin_id or symbol).lower() if asset_type == "crypto" else symbol.upper()
    return f"{asset_type}:{ident}:{currency}"


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _load(session: AsyncSession, key: str) -> Optional[tuple[AnalystReport, datetime]]:
    row = (await session.execute(select(AnalystCache).where(AnalystCache.key == key))).scalars().first()
    if row is None:
        return None
    try:
        return AnalystReport.model_validate(json.loads(row.payload)), _utc(row.created_at)
    except ValueError:
        return None  # an old/broken entry is simply regenerated


async def _save(session: AsyncSession, key: str, report: AnalystReport, created: datetime) -> None:
    row = await session.get(AnalystCache, key)
    payload = report.model_dump_json()
    if row is None:
        session.add(AnalystCache(key=key, payload=payload, created_at=created.replace(tzinfo=None)))
    else:
        row.payload, row.created_at = payload, created.replace(tzinfo=None)
    await session.commit()


def _with_cache_info(report: AnalystReport, created: datetime, cached: bool) -> AnalystReport:
    report = report.model_copy()
    report.cached = cached
    report.refresh_available_at = created + REFRESH_COOLDOWN
    return report


@asynccontextmanager
async def _asset_lock(key: str):
    """Hold the asset's lock; the last request to let go of it removes it again."""
    lock = _locks.setdefault(key, asyncio.Lock())
    _lock_users[key] = _lock_users.get(key, 0) + 1
    try:
        async with lock:
            yield
    finally:
        _lock_users[key] -= 1
        if _lock_users[key] <= 0:
            del _lock_users[key]
            if _locks.get(key) is lock:
                del _locks[key]


def _drop_older_than(window: deque, cutoff: float) -> None:
    while window and window[0] < cutoff:
        window.popleft()


def _take_generation_slot(user_id: str) -> Optional[HTTPException]:
    """
    Sliding one-hour windows of fresh reports: per user and for everyone together. Returns None when a slot was
    taken, otherwise the 429 to answer with.
    """
    now = time.time()
    cutoff = now - WINDOW_SECONDS
    if user_id not in _user_generations and len(_user_generations) >= 10_000:
        # forget users with nothing left in their window, so this stays small
        for idle in [uid for uid, times in _user_generations.items() if not times or times[-1] < cutoff]:
            del _user_generations[idle]
    window = _user_generations[user_id]
    _drop_older_than(window, cutoff)
    _drop_older_than(_global_generations, cutoff)

    if len(window) >= GENERATIONS_PER_HOUR:
        return HTTPException(status_code=429, detail=USER_LIMIT_MESSAGE)
    if len(_global_generations) >= GLOBAL_GENERATIONS_PER_HOUR:
        retry = max(1, int(_global_generations[0] + WINDOW_SECONDS - now) + 1)  # when the oldest one expires
        return HTTPException(status_code=429, detail=GLOBAL_LIMIT_MESSAGE, headers={"Retry-After": str(retry)})
    window.append(now)
    _global_generations.append(now)
    return None


def forget_user(user_id: str) -> None:
    """Drop a deleted account's rate-limit history (it's only kept in memory)."""
    _user_generations.pop(user_id, None)


def _refund_generation_slot(user_id: str) -> None:
    window = _user_generations.get(user_id)
    if window:
        window.pop()
    if _global_generations:
        _global_generations.pop()


async def get_report(session: AsyncSession, user_id: str, symbol: str, asset_type: str, currency: str,
                     coin_id: Optional[str] = None, refresh: bool = False) -> AnalystReport:
    key = cache_key(asset_type, symbol, currency, coin_id)
    now = datetime.now(timezone.utc)

    existing = await _load(session, key)
    # give the pooled connection back: what follows may wait on the asset's lock and on Yahoo / CoinGecko / Gemini
    # for up to half a minute (rows already read stay usable: the session maker sets expire_on_commit=False)
    await session.commit()
    if existing:
        report, created = existing
        age = now - created
        if refresh and age < REFRESH_COOLDOWN:
            # rounded up: exactly 5 minutes left (a refresh in the same clock tick as the report) is "5 min", not 6
            wait = max(1, math.ceil((REFRESH_COOLDOWN - age).total_seconds() / 60))
            raise HTTPException(status_code=429,
                                detail=f"This analysis was just updated. You can refresh it again in {wait} min.",
                                headers={"Retry-After": str(int((REFRESH_COOLDOWN - age).total_seconds()))})
        if not refresh and age < CACHE_TTL[asset_type]:
            return _with_cache_info(report, created, cached=True)

    async with _asset_lock(key):
        # another request may have generated it while we waited for the lock
        if not refresh:
            existing = await _load(session, key)
            await session.commit()  # as above
            if existing and now - existing[1] < CACHE_TTL[asset_type]:
                return _with_cache_info(existing[0], existing[1], cached=True)

        refused = _take_generation_slot(user_id)
        if refused is not None:
            if existing:  # over a limit: an older report (flagged as cached) beats an error
                return _with_cache_info(existing[0], existing[1], cached=True)
            raise refused

        try:
            collected = await asyncio.wait_for(
                market_data.collect(symbol, asset_type, currency, coin_id), COLLECT_TIMEOUT_SECONDS)
        except (market_data.DataUnavailable, asyncio.TimeoutError) as exc:
            _refund_generation_slot(user_id)
            if existing:  # better an older report (flagged as cached) than nothing
                return _with_cache_info(existing[0], existing[1], cached=True)
            message = str(exc) if isinstance(exc, market_data.DataUnavailable) and str(exc) else \
                "Market data took too long to load. Please try again."
            raise HTTPException(status_code=503, detail=message)

        report = build_report(collected)
        report = await reword(report)

        created = datetime.now(timezone.utc)
        await _save(session, key, report, created)
        return _with_cache_info(report, created, cached=False)
