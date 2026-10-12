"""
Collects the market data the analyst works from. Every value keeps track of where it came from so the report can
cite its sources, and anything that couldn't be fetched is reported as a limitation instead of being guessed.
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import httpx
import yfinance as yf

from backend.services.asset_services import get_history_of_prices

log = logging.getLogger("uvicorn.error")

COINGECKO = "https://api.coingecko.com/api/v3"
_btc_cache: dict[str, tuple[float, list]] = {}  # currency -> (fetched_at, daily closes) for correlation
BTC_CACHE_SECONDS = 3600


class DataUnavailable(Exception):
    """The price source couldn't be reached at all (as opposed to an asset with little history)."""


@dataclass
class AssetData:
    symbol: str
    type: str  # "stock" | "crypto"
    currency: str
    name: Optional[str] = None
    times: list[datetime] = field(default_factory=list)  # daily, oldest first
    closes: list[float] = field(default_factory=list)  # in `currency`
    volumes: list[Optional[float]] = field(default_factory=list)
    btc_closes: list[float] = field(default_factory=list)  # crypto only, same currency, for correlation
    fundamentals: dict = field(default_factory=dict)  # stocks: from Yahoo Finance
    calendar: dict = field(default_factory=dict)  # stocks: earnings / dividend dates from Yahoo Finance
    coin: dict = field(default_factory=dict)  # crypto: CoinGecko market data
    sources: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def _coingecko_headers() -> dict:
    key = os.getenv("API_KEY_COINEGECKO")
    return {"x-cg-demo-api-key": key} if key else {}


def _parse_time(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------------------------------------- stocks
async def _stock_history(data: AssetData) -> None:
    try:
        history, _ = await get_history_of_prices(data.symbol, "stock", "1Y", data.currency)
    except Exception as exc:
        raise DataUnavailable("Price history is unavailable right now.") from exc

    for point in history:
        data.times.append(_parse_time(point["time"]))
        data.closes.append(float(point["price"]))
        data.volumes.append(point.get("volume"))

    data.sources.append({"name": "Yahoo Finance (daily prices & volume)",
                         "url": f"https://finance.yahoo.com/quote/{data.symbol}",
                         "as_of": data.times[-1] if data.times else None})


def _read_stock_details(symbol: str) -> tuple[dict, dict]:
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    try:
        calendar = ticker.calendar or {}
    except Exception:
        calendar = {}
    return info, calendar if isinstance(calendar, dict) else {}


async def _stock_details(data: AssetData) -> None:
    try:
        info, calendar = await asyncio.to_thread(_read_stock_details, data.symbol)
    except Exception:
        data.limitations.append("Company fundamentals couldn't be loaded, so the analysis uses price data only.")
        return

    keys = ["longName", "shortName", "sector", "industry", "currency", "financialCurrency", "marketCap",
            "trailingPE", "forwardPE", "priceToSalesTrailing12Months", "revenueGrowth", "earningsGrowth",
            "profitMargins", "operatingMargins", "freeCashflow", "totalRevenue", "debtToEquity",
            "recommendationKey", "recommendationMean", "targetMeanPrice", "numberOfAnalystOpinions",
            "currentPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "beta", "dividendYield", "quoteType"]
    data.fundamentals = {k: info.get(k) for k in keys if info.get(k) is not None}
    data.name = info.get("longName") or info.get("shortName")

    for key in ("Earnings Date", "Ex-Dividend Date", "Dividend Date"):
        value = calendar.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, (date, datetime)):
            data.calendar[key] = value
    for key in ("Earnings Average", "Earnings Low", "Earnings High"):  # consensus EPS estimates for that report
        value = calendar.get(key)
        if isinstance(value, (int, float)):
            data.calendar[key] = float(value)

    if data.fundamentals:
        data.sources.append({"name": "Yahoo Finance (fundamentals, analyst estimates & calendar)",
                             "url": f"https://finance.yahoo.com/quote/{data.symbol}/key-statistics",
                             "as_of": datetime.now(timezone.utc)})
    else:
        data.limitations.append("No company fundamentals were available for this ticker.")


# --------------------------------------------------------------------------------------------------------- crypto
async def resolve_coin_id(client: httpx.AsyncClient, symbol: str) -> Optional[str]:
    """Find the CoinGecko id for a ticker (most popular coin with that symbol)."""
    res = await client.get(f"{COINGECKO}/search", params={"query": symbol})
    if res.status_code == 429:
        raise DataUnavailable("The crypto data provider is rate limiting requests. Try again in a minute.")
    if res.status_code != 200:
        raise DataUnavailable("The crypto data provider couldn't be reached.")
    coins = res.json().get("coins", [])
    for coin in coins:
        if str(coin.get("symbol", "")).lower() == symbol.lower():
            return coin.get("id")
    return None


async def _market_chart(client: httpx.AsyncClient, coin_id: str, currency: str) -> tuple[list, list]:
    res = await client.get(f"{COINGECKO}/coins/{coin_id}/market_chart",
                           params={"vs_currency": currency.lower(), "days": 365, "interval": "daily"})
    if res.status_code == 429:
        raise DataUnavailable("The crypto data provider is rate limiting requests. Try again in a minute.")
    if res.status_code != 200:
        raise DataUnavailable("Crypto price history is unavailable right now.")
    body = res.json()
    return body.get("prices", []), body.get("total_volumes", [])


async def _btc_closes(client: httpx.AsyncClient, currency: str) -> list[float]:
    cached = _btc_cache.get(currency)
    if cached and time.time() - cached[0] < BTC_CACHE_SECONDS:
        return cached[1]
    prices, _ = await _market_chart(client, "bitcoin", currency)
    closes = [float(p[1]) for p in prices]
    _btc_cache[currency] = (time.time(), closes)
    return closes


async def _crypto(data: AssetData, coin_id: Optional[str]) -> None:
    async with httpx.AsyncClient(timeout=12, headers=_coingecko_headers()) as client:
        try:
            coin_id = coin_id or await resolve_coin_id(client, data.symbol)
        except httpx.HTTPError as exc:
            raise DataUnavailable("The crypto data provider couldn't be reached.") from exc
        if not coin_id:
            data.limitations.append(f"No coin called {data.symbol.upper()} was found on CoinGecko.")
            return

        try:
            prices, volumes = await _market_chart(client, coin_id, data.currency)
        except httpx.HTTPError as exc:
            raise DataUnavailable("The crypto data provider couldn't be reached.") from exc

        # the last point is the live price at request time; keep it, it's the "current" value
        volume_by_time = {int(v[0]): v[1] for v in volumes}
        for ms, price in prices:
            data.times.append(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))
            data.closes.append(float(price))
            data.volumes.append(volume_by_time.get(int(ms)))

        try:
            res = await client.get(f"{COINGECKO}/coins/{coin_id}", params={
                "localization": "false", "tickers": "false", "market_data": "true",
                "community_data": "false", "developer_data": "false", "sparkline": "false"})
            details = res.json() if res.status_code == 200 else {}
        except httpx.HTTPError:
            details = {}

        market = details.get("market_data") or {}
        cur = data.currency.lower()

        def in_currency(key):
            value = market.get(key)
            return value.get(cur) if isinstance(value, dict) else value

        data.name = details.get("name") or data.name
        # label the report with the coin's real ticker, even if the request's symbol didn't match the coin id
        data.symbol = details.get("symbol") or data.symbol
        data.coin = {
            "id": coin_id,
            "market_cap": in_currency("market_cap"),
            "market_cap_rank": details.get("market_cap_rank") or market.get("market_cap_rank"),
            "total_volume": in_currency("total_volume"),
            "fully_diluted_valuation": in_currency("fully_diluted_valuation"),
            "circulating_supply": market.get("circulating_supply"),
            "total_supply": market.get("total_supply"),
            "max_supply": market.get("max_supply"),
            "ath": in_currency("ath"),
            "ath_change_percentage": in_currency("ath_change_percentage"),
            "ath_date": in_currency("ath_date"),
            "last_updated": market.get("last_updated") or details.get("last_updated"),
        }
        data.coin = {k: v for k, v in data.coin.items() if v is not None}

        source_time = _parse_time(data.coin["last_updated"]) if data.coin.get("last_updated") else (
            data.times[-1] if data.times else None)
        data.sources.append({"name": "CoinGecko (prices, volume, market cap & supply)",
                             "url": f"https://www.coingecko.com/en/coins/{coin_id}", "as_of": source_time})
        if not market:
            data.limitations.append("Market cap and supply data weren't available for this coin.")

        if coin_id != "bitcoin":
            try:
                data.btc_closes = await _btc_closes(client, data.currency)
            except (DataUnavailable, httpx.HTTPError):
                data.limitations.append("Bitcoin prices were unavailable, so correlation with BTC isn't shown.")


# --------------------------------------------------------------------------------------------------------- entry
async def collect(symbol: str, asset_type: str, currency: str, coin_id: Optional[str] = None) -> AssetData:
    data = AssetData(symbol=symbol, type=asset_type, currency=currency)

    if asset_type == "stock":
        await asyncio.gather(_stock_history(data), _stock_details(data))
    else:
        await _crypto(data, coin_id)

    data.limitations.append("No news feed is connected, so recent headlines and announcements are not considered.")
    return data
