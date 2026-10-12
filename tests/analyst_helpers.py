"""
Synthetic market data for the Market Analyst tests. Everything is deterministic (no randomness, no network).
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.analyst.data import AssetData

# daily log drift per shape; the small sine wobble gives the series realistic up and down days
SHAPES = {
    "up": 0.003,
    "down": -0.003,
}


def make_closes(shape: str, n: int, start: float = 100.0) -> list[float]:
    if shape == "flat":
        # range-bound: a ±3% monthly wave around a constant level, no drift
        return [start * (1 + 0.03 * math.sin(2 * math.pi * i / 30)) for i in range(n)]
    if shape == "constant":
        return [start] * n
    drift = SHAPES[shape]
    return [start * math.exp(drift * i + 0.01 * math.sin(i)) for i in range(n)]


def make_data(shape: str = "up", n: int = 365, asset_type: str = "stock", currency: str = "USD",
              symbol: str = "NVDA", start: float = 100.0, end: Optional[datetime] = None,
              volumes: Optional[list] = None, **fields) -> AssetData:
    """
    AssetData with `n` daily points ending at `end` (default: an hour ago, i.e. fresh data).
    Extra keyword arguments (fundamentals, calendar, coin, btc_closes, name, ...) are set on the dataclass.
    """
    end = end or datetime.now(timezone.utc) - timedelta(hours=1)
    closes = make_closes(shape, n, start)
    times = [end - timedelta(days=n - 1 - i) for i in range(n)]
    data = AssetData(symbol=symbol, type=asset_type, currency=currency, name=fields.pop("name", None),
                     times=times, closes=closes,
                     volumes=volumes if volumes is not None else [1_000_000.0] * n)
    data.sources.append({"name": "Synthetic test data", "url": None, "as_of": end})
    for key, value in fields.items():
        setattr(data, key, value)
    return data


GOOD_FUNDAMENTALS = {
    "longName": "NVIDIA Corporation", "currency": "USD", "financialCurrency": "USD", "marketCap": 3.2e12,
    "revenueGrowth": 0.30, "earningsGrowth": 0.40, "profitMargins": 0.25, "operatingMargins": 0.30,
    "trailingPE": 25.0, "forwardPE": 18.0, "recommendationKey": "buy", "recommendationMean": 1.8,
    "targetMeanPrice": 120.0, "numberOfAnalystOpinions": 20, "currentPrice": 100.0,
}

BAD_FUNDAMENTALS = {"revenueGrowth": -0.30, "earningsGrowth": -0.40, "profitMargins": -0.10}

COIN = {
    "id": "solana", "market_cap": 8.0e10, "market_cap_rank": 5, "total_volume": 5.0e9,
    "circulating_supply": 4.5e8, "total_supply": 5.8e8, "ath": 300.0, "ath_change_percentage": -40.0,
}
