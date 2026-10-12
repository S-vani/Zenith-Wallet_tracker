"""
Orchestrates a report: cache lookup -> rate limits -> data collection -> rules engine -> optional Gemini rewording.

Reports are cached in the database (so they survive restarts) per asset and currency. Users can force a refresh,
but only once the cached report is a few minutes old, and each user can only trigger a limited number of fresh
reports per hour (cache hits are free).
"""
import asyncio
import json
import time
from collections import defaultdict, deque
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
COLLECT_TIMEOUT_SECONDS = 30


class AnalystCache(Base):
    __tablename__ = "analyst_reports"

    key = Column(String, primary_key=True)  # e.g. "stock:NVDA:CAD"
    payload = Column(Text, nullable=False)  # AnalystReport as JSON
    created_at = Column(DateTime, nullable=False)


_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # one generation per asset at a time
_user_generations: dict[str, deque] = defaultdict(deque)


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


def _take_generation_slot(user_id: str) -> bool:
    """Sliding one-hour window of fresh reports per user."""
    window = _user_generations[user_id]
    cutoff = time.time() - 3600
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= GENERATIONS_PER_HOUR:
        return False
    window.append(time.time())
    return True


def _refund_generation_slot(user_id: str) -> None:
    window = _user_generations[user_id]
    if window:
        window.pop()


async def get_report(session: AsyncSession, user_id: str, symbol: str, asset_type: str, currency: str,
                     coin_id: Optional[str] = None, refresh: bool = False) -> AnalystReport:
    key = cache_key(asset_type, symbol, currency, coin_id)
    now = datetime.now(timezone.utc)

    existing = await _load(session, key)
    if existing:
        report, created = existing
        age = now - created
        if refresh and age < REFRESH_COOLDOWN:
            wait = int((REFRESH_COOLDOWN - age).total_seconds() // 60) + 1
            raise HTTPException(status_code=429,
                                detail=f"This analysis was just updated. You can refresh it again in {wait} min.",
                                headers={"Retry-After": str(int((REFRESH_COOLDOWN - age).total_seconds()))})
        if not refresh and age < CACHE_TTL[asset_type]:
            return _with_cache_info(report, created, cached=True)

    async with _locks[key]:
        # another request may have generated it while we waited for the lock
        if not refresh:
            existing = await _load(session, key)
            if existing and now - existing[1] < CACHE_TTL[asset_type]:
                return _with_cache_info(existing[0], existing[1], cached=True)

        if not _take_generation_slot(user_id):
            if existing:
                return _with_cache_info(existing[0], existing[1], cached=True)
            raise HTTPException(status_code=429, detail="You've reached the hourly limit for new analyses. "
                                                        "Please try again later.")

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
