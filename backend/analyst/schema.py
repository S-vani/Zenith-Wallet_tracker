"""
Response format of GET /analyst. The frontend's AnalystPanel renders exactly these fields.

Money values (scenario ranges) are numbers in the user's currency; everything the user reads as text is already
written out here, so the panel never has to invent wording.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Sentiment = Literal["bullish", "neutral", "bearish"]
Tone = Literal["positive", "negative", "neutral"]


class AssetInfo(BaseModel):
    symbol: str  # as shown to the user, e.g. "NVDA", "BTC"
    name: Optional[str] = None  # e.g. "NVIDIA Corporation", "Bitcoin"
    type: Literal["stock", "crypto"]
    currency: Literal["CAD", "USD", "EUR"]
    price: Optional[float] = None  # latest close used by the analysis, in `currency`


class Period(BaseModel):
    start: datetime  # first data point used
    end: datetime  # last data point used ("data as of")
    days: int  # calendar days covered


class Insight(BaseModel):
    title: str  # short headline, e.g. "Strong 90-day momentum"
    detail: str  # one or two sentences, every number in it comes from `metrics`
    kind: Literal["momentum", "trend", "volatility", "volume", "valuation", "fundamentals", "analysts", "supply",
                  "market", "correlation"]
    tone: Tone


class PriceRange(BaseModel):
    days: int  # 7 or 30 (calendar days)
    low: float
    high: float


class Scenario(BaseModel):
    case: Literal["bull", "base", "bear"]
    summary: str  # one sentence
    conditions: list[str] = Field(default_factory=list)  # what would have to happen
    ranges: list[PriceRange] = Field(default_factory=list)  # empty when there isn't enough data


class WatchItem(BaseModel):
    title: str
    detail: str
    kind: Literal["earnings", "dividend", "price_level", "momentum", "supply", "market"]
    date: Optional[datetime] = None  # only for verified, dated events (e.g. earnings from Yahoo Finance)


class Risk(BaseModel):
    title: str
    detail: str


class Metric(BaseModel):
    label: str  # e.g. "30-day return"
    value: str  # already formatted, e.g. "+12.4%", "CA$1.2T", "28.5x"
    group: Literal["performance", "trend", "risk", "volume", "fundamentals", "valuation", "analysts", "supply",
                   "market"]


class Source(BaseModel):
    name: str  # e.g. "Yahoo Finance (price history)", "CoinGecko"
    url: Optional[str] = None
    as_of: Optional[datetime] = None


class AnalystReport(BaseModel):
    status: Literal["ok", "insufficient_data"]
    asset: AssetInfo
    generated_at: datetime
    period: Optional[Period] = None
    stale: bool = False  # latest data point is older than expected (market closed is not stale)
    stale_reason: Optional[str] = None

    engine: Literal["rules", "gemini"]  # who wrote the text: built-in rules, or Gemini rewording of the same facts

    sentiment: Optional[Sentiment] = None
    confidence: Optional[Literal["low", "medium", "high"]] = None
    score: Optional[float] = None  # -1 (very bearish) .. +1 (very bullish)
    summary: str  # 2-4 sentence outlook (or explanation when status is insufficient_data)
    reasons: list[str] = Field(default_factory=list)  # primary reasons behind the sentiment

    insights: list[Insight] = Field(default_factory=list)  # 2-3 most relevant
    scenarios: list[Scenario] = Field(default_factory=list)  # bull, base, bear (in that order)
    range_method: Optional[str] = None  # how the price ranges were calculated + assumptions
    watch: list[WatchItem] = Field(default_factory=list)  # up to 3
    main_risk: Optional[Risk] = None
    bottom_line: Optional[str] = None

    metrics: list[Metric] = Field(default_factory=list)  # the factual data behind the analysis
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)  # missing / unavailable data the user should know about
    disclaimer: str

    cached: bool = False  # served from cache
    refresh_available_at: Optional[datetime] = None  # when a manual refresh is allowed again
