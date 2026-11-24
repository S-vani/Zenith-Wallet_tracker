"""
What a stock or ETF is, from Yahoo Finance, cached for a few hours: its name, sector, country, beta, the next
earnings and ex-dividend dates, and for funds what they hold (sector weights and top holdings). Used by Portfolio
X-Ray (services/xray.py) and the holding events of the daily briefing (services/alerts.py). Every Yahoo call goes
through run_yahoo like the rest of the app; a failure gives an empty profile, never an error.
"""
import asyncio
import logging
import time
from datetime import date, datetime

from backend.services import asset_services
from backend.services.asset_services import run_yahoo

log = logging.getLogger("uvicorn.error")

PROFILE_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, dict]] = {}
_inflight: dict[str, asyncio.Future] = {}

FUND_TYPES = ("ETF", "MUTUALFUND")


def _first_date(value):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _read_profile(symbol: str) -> dict:
    """Blocking Yahoo read of one ticker's profile (run through run_yahoo)."""
    ticker = asset_services.yf.Ticker(symbol)  # the module the rest of the app (and the tests' fake) uses
    info = ticker.info or {}
    profile = {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "quote_type": info.get("quoteType"),
        "beta": info.get("beta") if isinstance(info.get("beta"), (int, float)) else None,
        "category": info.get("category"),
        "earnings_date": None,
        "ex_dividend_date": None,
        "fund_sectors": {},
        "fund_holdings": [],
    }
    try:
        calendar = ticker.calendar or {}
    except Exception:
        calendar = {}
    if isinstance(calendar, dict):
        profile["earnings_date"] = _first_date(calendar.get("Earnings Date"))
        profile["ex_dividend_date"] = _first_date(calendar.get("Ex-Dividend Date"))
    if profile["quote_type"] in FUND_TYPES:
        try:
            funds = ticker.funds_data
            sectors = funds.sector_weightings or {}
            profile["fund_sectors"] = {str(k): float(v) for k, v in sectors.items() if isinstance(v, (int, float))}
            top = funds.top_holdings
            if top is not None and len(top):
                weight_col = "Holding Percent" if "Holding Percent" in top.columns else top.columns[-1]
                name_col = "Name" if "Name" in top.columns else None
                profile["fund_holdings"] = [
                    {"symbol": str(idx), "name": str(row[name_col]) if name_col else str(idx),
                     "weight": float(row[weight_col])}
                    for idx, row in top.head(15).iterrows()
                ]
        except Exception:
            pass  # no look-through for this fund: X-Ray counts it as one block
    return profile


EMPTY_PROFILE = {"name": None, "sector": None, "industry": None, "country": None, "quote_type": None, "beta": None,
                 "category": None, "earnings_date": None, "ex_dividend_date": None, "fund_sectors": {},
                 "fund_holdings": []}


async def stock_profile(symbol: str) -> dict:
    """The cached profile of a Yahoo ticker ("AAPL", "XEQT.TO"); concurrent misses share one read."""
    key = symbol.upper()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < PROFILE_TTL_SECONDS:
        return hit[1]
    if key in _inflight:
        return await asyncio.shield(_inflight[key])
    future = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        try:
            profile = await run_yahoo(_read_profile, key)
        except Exception as exc:
            log.warning("No profile for %s: %s", key, type(exc).__name__)
            profile = dict(EMPTY_PROFILE)
        _cache[key] = (time.monotonic(), profile)
        future.set_result(profile)
        return profile
    finally:
        _inflight.pop(key, None)
