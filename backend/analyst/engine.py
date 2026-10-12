"""
Rules engine: turns AssetData into an AnalystReport.

Each signal (trend, momentum, fundamentals, ...) gets a score between -1 and +1 and a weight. The weighted average
decides the sentiment, the strongest signals become the reasons and insights, and every sentence is written from
numbers that also appear in the report's metrics, so nothing is invented.
"""
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from backend.analyst import indicators as ind
from backend.analyst.data import AssetData
from backend.analyst.schema import (AnalystReport, AssetInfo, Insight, Metric, Period, PriceRange, Risk,
                                    Scenario, Source, WatchItem)

DISCLAIMER = ("Generated automatically from market data for information only. It is not financial advice, and past "
              "price movements don't guarantee future results.")
MIN_POINTS = 30  # below this there isn't enough history to say anything meaningful
MIN_POINTS_FOR_RANGES = 60
CURRENCY_SYMBOL = {"CAD": "CA$", "USD": "$", "EUR": "€"}


# --------------------------------------------------------------------------------------------------------- formatting
def fmt_pct(value: float, signed: bool = True, digits: int = 1) -> str:
    text = f"{abs(value) * 100:.{digits}f}%"
    if not signed or round(abs(value) * 100, digits) == 0:
        return text  # no sign on 0.0%
    return ("+" if value > 0 else "−") + text


def fmt_money(value: float, currency: str) -> str:
    sym = CURRENCY_SYMBOL.get(currency, "")
    v = abs(value)
    if v >= 1e12:
        body = f"{v / 1e12:.2f}T"
    elif v >= 1e9:
        body = f"{v / 1e9:.2f}B"
    elif v >= 1e6:
        body = f"{v / 1e6:.2f}M"
    elif v >= 1:
        body = f"{v:,.2f}"
    elif v == 0:
        body = "0.00"
    else:
        decimals = min(12, max(2, math.ceil(-math.log10(v)) + 3))  # keep ~4 significant digits for tiny prices
        body = f"{v:.{decimals}f}".rstrip("0")
    return ("−" if value < 0 else "") + sym + body


def fmt_compact(value: float) -> str:
    v = abs(value)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= size:
            return f"{value / size:.2f}{suffix}"
    return f"{value:,.0f}"


def fmt_date(value) -> str:
    return value.strftime("%b %d, %Y").replace(" 0", " ")


def clamp(value: float, limit: float = 1.0) -> float:
    return max(-limit, min(limit, value))


# --------------------------------------------------------------------------------------------------------- signals
@dataclass
class Signal:
    key: str
    score: float  # -1 .. +1
    weight: float
    reason: str  # short phrase used in the reasons list
    insight: Optional[Insight] = None

    @property
    def impact(self) -> float:
        return self.score * self.weight


@dataclass
class Facts:
    """Everything calculated from the data, shared by the text builders."""
    price: float
    ppy: int  # periods per year: 252 trading days (stocks) or 365 (crypto)
    r7: Optional[float]
    r30: Optional[float]
    r90: Optional[float]
    r1y: Optional[float]
    r1y_days: Optional[int]
    sma50: Optional[float]
    sma200: Optional[float]
    rsi: Optional[float]
    vol: Optional[float]
    drawdown: Optional[float]
    volume_trend: Optional[float]
    high: float
    low: float
    btc_corr: Optional[float] = None
    btc_r30: Optional[float] = None


def points(days: int, ppy: int) -> int:
    """How many daily data points cover `days` calendar days."""
    return days if ppy == 365 else max(1, round(days * 252 / 365))


def calculate_facts(data: AssetData) -> Facts:
    closes = data.closes
    ppy = 365 if data.type == "crypto" else 252
    year = closes[-points(365, ppy):]

    r1y_days = None
    r1y = None
    if len(closes) >= points(300, ppy):
        r1y = closes[-1] / closes[0] - 1 if closes[0] > 0 else None
        r1y_days = (data.times[-1] - data.times[0]).days

    facts = Facts(
        price=closes[-1], ppy=ppy,
        r7=ind.pct_return(closes, points(7, ppy)),
        r30=ind.pct_return(closes, points(30, ppy)),
        r90=ind.pct_return(closes, points(90, ppy)),
        r1y=r1y, r1y_days=r1y_days,
        sma50=ind.sma(closes, 50), sma200=ind.sma(closes, 200),
        rsi=ind.rsi(closes),
        vol=ind.annualized_volatility(closes, points(90, ppy), ppy),
        drawdown=ind.max_drawdown(year),
        volume_trend=ind.volume_trend(data.volumes),
        high=max(year), low=min(year),
    )

    if data.btc_closes:
        own = ind.log_returns(closes[-91:])
        btc = ind.log_returns(data.btc_closes[-91:])
        facts.btc_corr = ind.correlation(own, btc)
        facts.btc_r30 = ind.pct_return(data.btc_closes, 30)
    return facts


def trend_signal(f: Facts, data: AssetData) -> Optional[Signal]:
    if f.sma50 is None:
        return None
    def side(value: float, reference: float) -> int:
        # within 0.1% counts as "at" the level, so a flat price isn't called a downtrend
        if value > reference * 1.001:
            return 1
        if value < reference * 0.999:
            return -1
        return 0

    parts = [side(f.price, f.sma50)]
    if f.sma200 is not None:
        parts.append(side(f.price, f.sma200))
        parts.append(side(f.sma50, f.sma200))
    score = sum(parts) / len(parts)
    if score == 0:
        return Signal("trend", 0.0, 1.5, "Trading at its moving averages", Insight(
            title="No clear trend", kind="trend", tone="neutral",
            detail=f"The price ({fmt_money(f.price, data.currency)}) is sitting at its moving averages, "
                   "so there is no trend in either direction."))

    cur = data.currency
    if f.sma200 is not None:
        where = "above" if f.price > f.sma200 else "below"
        cross = "above" if f.sma50 > f.sma200 else "below"
        detail = (f"The price ({fmt_money(f.price, cur)}) is {where} its 200-day average ({fmt_money(f.sma200, cur)}), "
                  f"and the 50-day average is {cross} the 200-day.")
        title = {1: "Uptrend intact", -1: "Downtrend in place"}.get(round(score), "Mixed trend signals")
    else:
        where = "above" if f.price > f.sma50 else "below"
        detail = f"The price ({fmt_money(f.price, cur)}) is {where} its 50-day average ({fmt_money(f.sma50, cur)})."
        title = "Short-term uptrend" if score > 0 else "Short-term downtrend"

    reason = (f"Trading {'above' if f.price > (f.sma200 or f.sma50) else 'below'} its "
              f"{'200' if f.sma200 else '50'}-day average")
    tone = "positive" if score > 0.3 else "negative" if score < -0.3 else "neutral"
    return Signal("trend", score, 1.5, reason, Insight(title=title, detail=detail, kind="trend", tone=tone))


def momentum_signal(f: Facts) -> Optional[Signal]:
    if f.r90 is None and f.r30 is None:
        return None
    score = 0.0
    weights = 0.0
    if f.r90 is not None:
        score += clamp(f.r90 / 0.25) * 0.6
        weights += 0.6
    if f.r30 is not None:
        score += clamp(f.r30 / 0.10) * 0.4
        weights += 0.4
    score /= weights

    bits = []
    if f.r30 is not None:
        bits.append(f"{fmt_pct(f.r30)} over 30 days")
    if f.r90 is not None:
        bits.append(f"{fmt_pct(f.r90)} over 90 days")
    if f.r1y is not None:
        bits.append(f"{fmt_pct(f.r1y)} over the past year")
    title = ("Strong momentum" if score > 0.5 else "Positive momentum" if score > 0.15
             else "Weak momentum" if score < -0.5 else "Negative momentum" if score < -0.15 else "Flat momentum")
    candidates = [(days, r) for days, r in (("90", f.r90), ("30", f.r30)) if r is not None]
    matching = [(days, r) for days, r in candidates if (r > 0) == (score > 0) and r != 0]
    days, main = (matching or candidates)[0]
    if abs(score) <= 0.15 or not matching:
        reason = "Flat momentum"
    else:
        reason = f"{'Up' if main > 0 else 'Down'} {fmt_pct(main, signed=False)} over {days} days"
    tone = "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"
    detail = "The price is " + ", ".join(bits) + "."
    return Signal("momentum", score, 1.5, reason, Insight(title=title, detail=detail, kind="momentum", tone=tone))


def rsi_signal(f: Facts) -> Optional[Signal]:
    if f.rsi is None or 30 <= f.rsi <= 70:
        return None
    if f.rsi > 70:
        return Signal("rsi", -0.4, 0.5, f"Overbought (RSI {f.rsi:.0f})", Insight(
            title="Looks stretched", kind="momentum", tone="negative",
            detail=f"The 14-day RSI is {f.rsi:.0f} (above 70), which often comes before a pause or pullback."))
    return Signal("rsi", 0.4, 0.5, f"Oversold (RSI {f.rsi:.0f})", Insight(
        title="Oversold", kind="momentum", tone="positive",
        detail=f"The 14-day RSI is {f.rsi:.0f} (below 30); sellers may be exhausted, though downtrends can persist."))


def volume_signal(f: Facts) -> Optional[Signal]:
    if f.volume_trend is None or f.r30 is None or abs(f.volume_trend) < 0.2:
        return None
    rising = f.volume_trend > 0
    if rising:
        score = 0.5 if f.r30 > 0 else -0.5
        title = "Buying interest rising" if f.r30 > 0 else "Selling pressure building"
        detail = (f"Average daily volume over the last 20 days is {fmt_pct(f.volume_trend)} vs the prior 90 days, "
                  f"while the price moved {fmt_pct(f.r30)} over 30 days.")
    else:
        score = -0.2 if f.r30 > 0 else 0.1
        title = "Participation fading"
        detail = (f"Average daily volume over the last 20 days is {fmt_pct(f.volume_trend)} vs the prior 90 days, "
                  "so recent moves have less conviction behind them.")
    tone = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    return Signal("volume", score, 0.8, title, Insight(title=title, detail=detail, kind="volume", tone=tone))


def fundamentals_signal(data: AssetData) -> Optional[Signal]:
    fu = data.fundamentals
    rg, eg, pm = fu.get("revenueGrowth"), fu.get("earningsGrowth"), fu.get("profitMargins")
    if rg is None and eg is None and pm is None:
        return None
    parts, bits = [], []
    if rg is not None:
        parts.append(clamp(rg / 0.2))
        bits.append(f"revenue growth of {fmt_pct(rg)} year over year")
    if eg is not None:
        parts.append(clamp(eg / 0.25))
        bits.append(f"earnings growth of {fmt_pct(eg)}")
    if pm is not None:
        parts.append(0.4 if pm > 0.15 else -0.6 if pm < 0 else 0.0)
        bits.append(f"a {fmt_pct(pm, signed=False)} profit margin")
    score = sum(parts) / len(parts)
    title = ("Strong fundamentals" if score > 0.4 else "Solid fundamentals" if score > 0.1
             else "Weak fundamentals" if score < -0.3 else "Mixed fundamentals")
    tone = "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"
    detail = "Latest reported figures show " + ", ".join(bits) + "."
    reason = bits[0][0].upper() + bits[0][1:]
    return Signal("fundamentals", score, 1.2, reason,
                  Insight(title=title, detail=detail, kind="fundamentals", tone=tone))


def valuation_signal(data: AssetData) -> Optional[Signal]:
    fu = data.fundamentals
    pe, fpe = fu.get("trailingPE"), fu.get("forwardPE")
    if not pe or pe <= 0:
        return None
    score = 0.0
    if pe > 60:
        score -= 0.5
    elif pe > 35:
        score -= 0.2
    elif pe < 15:
        score += 0.2
    growth_note = ""
    if fpe and 0 < fpe < pe * 0.8:
        score += 0.3
        growth_note = f" The forward P/E of {fpe:.1f}x is lower, meaning analysts expect earnings to grow."
    elif fpe and fpe > pe * 1.1:
        score -= 0.2
        growth_note = f" The forward P/E of {fpe:.1f}x is higher, meaning earnings are expected to shrink."
    level = "high" if pe > 35 else "moderate" if pe > 15 else "low"
    detail = f"It trades at {pe:.1f}x trailing earnings, a {level} multiple.{growth_note}"
    tone = "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"
    return Signal("valuation", clamp(score), 0.8, f"{level.capitalize()} valuation ({pe:.0f}x earnings)",
                  Insight(title=f"{level.capitalize()} valuation", detail=detail, kind="valuation", tone=tone))


def native_to_user(data: AssetData, amount: float) -> Optional[float]:
    """Convert an amount quoted in the stock's own currency (Yahoo fundamentals) into the user's currency, using the
    ratio between the converted price history and Yahoo's current price."""
    current = data.fundamentals.get("currentPrice")
    if not current or not data.closes:
        return None
    return amount * data.closes[-1] / current


def analysts_signal(data: AssetData) -> Optional[Signal]:
    fu = data.fundamentals
    n, target, current = fu.get("numberOfAnalystOpinions"), fu.get("targetMeanPrice"), fu.get("currentPrice")
    rec = fu.get("recommendationMean")
    if not n or n < 3 or not target or not current:
        return None
    upside = target / current - 1
    score = clamp(upside / 0.2) * 0.6 + (clamp((3 - rec) / 1.5) * 0.4 if rec else 0)
    target_user = native_to_user(data, target)
    target_text = fmt_money(target_user, data.currency) if target_user else f"{target:,.2f} {fu.get('currency', '')}"
    rating = str(fu.get("recommendationKey") or "").replace("_", " ")
    detail = (f"The average target of {n} analysts is {target_text} ({fmt_pct(upside)} from the last price)"
              + (f", with a consensus rating of \"{rating}\"." if rating and rating != "none" else "."))
    tone = "positive" if upside > 0.05 else "negative" if upside < -0.05 else "neutral"
    return Signal("analysts", score, 0.7, f"Analyst targets {fmt_pct(upside)} away",
                  Insight(title="Analyst targets", detail=detail, kind="analysts", tone=tone))


def crypto_signals(f: Facts, data: AssetData) -> list[Signal]:
    coin, cur = data.coin, data.currency
    signals = []

    mcap, volume = coin.get("market_cap"), coin.get("total_volume")
    if mcap and volume:
        turnover = volume / mcap
        if turnover < 0.01:
            signals.append(Signal("liquidity", -0.4, 0.6, "Thin trading volume", Insight(
                title="Thin liquidity", kind="volume", tone="negative",
                detail=(f"24h volume of {fmt_money(volume, cur)} is only {fmt_pct(turnover, signed=False, digits=2)} "
                        f"of its {fmt_money(mcap, cur)} market cap, so large orders can move the price."))))
        elif turnover > 0.05:
            signals.append(Signal("liquidity", 0.2, 0.4, "Actively traded", Insight(
                title="Deep liquidity", kind="volume", tone="positive",
                detail=(f"24h volume of {fmt_money(volume, cur)} is "
                        f"{fmt_pct(turnover, signed=False, digits=2 if turnover < 0.01 else 1)} of its "
                        f"{fmt_money(mcap, cur)} market cap."))))

    ath_change = coin.get("ath_change_percentage")
    if ath_change is not None and coin.get("ath"):
        from_ath = ath_change / 100
        score = 0.2 if from_ath > -0.1 else -0.3 if from_ath < -0.7 else 0.0
        title = "Near all-time high" if from_ath > -0.1 else "Far below all-time high" if from_ath < -0.7 \
            else "Below all-time high"
        signals.append(Signal("ath", score, 0.5, title, Insight(
            title=title, kind="market", tone="positive" if score > 0 else "negative" if score < 0 else "neutral",
            detail=f"It is {fmt_pct(from_ath)} from its all-time high of {fmt_money(coin['ath'], cur)}.")))

    if f.btc_corr is not None and f.btc_r30 is not None and f.btc_corr > 0.5:
        score = clamp(f.btc_r30 / 0.1) * 0.5
        signals.append(Signal("btc", score, 0.7, f"Moves with Bitcoin (correlation {f.btc_corr:.2f})", Insight(
            title="Tied to Bitcoin", kind="correlation",
            tone="positive" if score > 0.1 else "negative" if score < -0.1 else "neutral",
            detail=(f"Daily moves have a {f.btc_corr:.2f} correlation with Bitcoin over 90 days, and Bitcoin is "
                    f"{fmt_pct(f.btc_r30)} over 30 days."))))
    return signals


# --------------------------------------------------------------------------------------------------------- report
def _future_date(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        return None
    return dt if dt.date() >= datetime.now(timezone.utc).date() else None


def build_metrics(f: Facts, data: AssetData) -> list[Metric]:
    cur = data.currency
    m: list[Metric] = [Metric(label="Last price", value=fmt_money(f.price, cur), group="performance")]
    for label, value in (("7-day return", f.r7), ("30-day return", f.r30), ("90-day return", f.r90)):
        if value is not None:
            m.append(Metric(label=label, value=fmt_pct(value), group="performance"))
    if f.r1y is not None:
        label = "1-year return" if 350 <= (f.r1y_days or 0) <= 380 else f"{f.r1y_days}-day return"
        m.append(Metric(label=label, value=fmt_pct(f.r1y), group="performance"))
    m.append(Metric(label="52-week range", value=f"{fmt_money(f.low, cur)} – {fmt_money(f.high, cur)}",
                    group="performance"))
    if f.sma50 is not None:
        m.append(Metric(label="50-day average", value=fmt_money(f.sma50, cur), group="trend"))
    if f.sma200 is not None:
        m.append(Metric(label="200-day average", value=fmt_money(f.sma200, cur), group="trend"))
    if f.rsi is not None:
        m.append(Metric(label="RSI (14-day)", value=f"{f.rsi:.0f}", group="trend"))
    if f.vol is not None:
        m.append(Metric(label="Volatility (annualized, 90-day)", value=fmt_pct(f.vol, signed=False), group="risk"))
    if f.drawdown is not None:
        m.append(Metric(label="Max drawdown (1 year)", value=fmt_pct(f.drawdown), group="risk"))
    if f.volume_trend is not None:
        m.append(Metric(label="Volume, 20-day vs prior 90-day", value=fmt_pct(f.volume_trend), group="volume"))

    fu = data.fundamentals
    native = fu.get("financialCurrency") or fu.get("currency") or ""
    if fu.get("marketCap"):
        m.append(Metric(label=f"Market cap ({fu.get('currency', native)})", value=fmt_compact(fu["marketCap"]),
                        group="fundamentals"))
    for key, label, kind in (("revenueGrowth", "Revenue growth (YoY)", "fundamentals"),
                             ("earningsGrowth", "Earnings growth (YoY)", "fundamentals"),
                             ("profitMargins", "Profit margin", "fundamentals"),
                             ("operatingMargins", "Operating margin", "fundamentals")):
        if fu.get(key) is not None:
            m.append(Metric(label=label, value=fmt_pct(fu[key], signed=key.endswith("Growth")), group=kind))
    if fu.get("freeCashflow"):
        m.append(Metric(label=f"Free cash flow ({native})", value=fmt_compact(fu["freeCashflow"]),
                        group="fundamentals"))
    for key, label in (("trailingPE", "P/E (trailing)"), ("forwardPE", "P/E (forward)"),
                       ("priceToSalesTrailing12Months", "Price / sales")):
        if fu.get(key):
            m.append(Metric(label=label, value=f"{fu[key]:.1f}x", group="valuation"))
    if fu.get("targetMeanPrice") and fu.get("numberOfAnalystOpinions"):
        target_user = native_to_user(data, fu["targetMeanPrice"])
        m.append(Metric(label="Analyst mean target",
                        value=fmt_money(target_user, cur) if target_user else f"{fu['targetMeanPrice']:,.2f}",
                        group="analysts"))
        m.append(Metric(label="Analysts covering", value=str(fu["numberOfAnalystOpinions"]), group="analysts"))
    if fu.get("targetMeanPrice") and fu.get("currentPrice") and fu.get("numberOfAnalystOpinions"):
        m.append(Metric(label="Analyst target vs price", value=fmt_pct(fu["targetMeanPrice"] / fu["currentPrice"] - 1),
                        group="analysts"))
    if fu.get("recommendationKey") and fu["recommendationKey"] != "none":
        m.append(Metric(label="Consensus rating", value=fu["recommendationKey"].replace("_", " "), group="analysts"))

    coin = data.coin
    if coin.get("market_cap"):
        rank = f" (#{coin['market_cap_rank']})" if coin.get("market_cap_rank") else ""
        m.append(Metric(label="Market cap", value=fmt_money(coin["market_cap"], cur) + rank, group="market"))
    if coin.get("total_volume"):
        m.append(Metric(label="24h volume", value=fmt_money(coin["total_volume"], cur), group="volume"))
    if coin.get("ath"):
        m.append(Metric(label="All-time high", value=fmt_money(coin["ath"], cur), group="market"))
    if coin.get("ath_change_percentage") is not None and coin.get("ath"):
        m.append(Metric(label="Distance from all-time high", value=fmt_pct(coin["ath_change_percentage"] / 100),
                        group="market"))
    if coin.get("market_cap") and coin.get("total_volume"):
        turnover = coin["total_volume"] / coin["market_cap"]
        m.append(Metric(label="24h volume / market cap",
                        value=fmt_pct(turnover, signed=False, digits=2 if turnover < 0.01 else 1), group="volume"))
    if coin.get("circulating_supply"):
        m.append(Metric(label="Circulating supply", value=fmt_compact(coin["circulating_supply"]), group="supply"))
    if coin.get("max_supply"):
        m.append(Metric(label="Max supply", value=fmt_compact(coin["max_supply"]), group="supply"))
    elif coin.get("circulating_supply"):
        m.append(Metric(label="Max supply", value="No fixed cap", group="supply"))
    if f.btc_corr is not None:
        m.append(Metric(label="Correlation with BTC (90-day)", value=f"{f.btc_corr:.2f}", group="market"))
    if f.btc_r30 is not None:
        m.append(Metric(label="Bitcoin 30-day return", value=fmt_pct(f.btc_r30), group="market"))
    return m


def build_watch(f: Facts, data: AssetData) -> list[WatchItem]:
    cur, items = data.currency, []
    earnings = _future_date(data.calendar.get("Earnings Date"))
    if earnings and earnings - datetime.now(timezone.utc) < timedelta(days=90):
        est = data.calendar.get("Earnings Average")
        lo, hi = data.calendar.get("Earnings Low"), data.calendar.get("Earnings High")
        detail = "Results and guidance often cause the biggest single-day moves for a stock."
        if est is not None:
            detail = (f"Analysts expect earnings per share of about {est:.2f}"
                      + (f" (range {lo:.2f}–{hi:.2f})" if lo is not None and hi is not None else "") + ". " + detail)
        items.append(WatchItem(title=f"Earnings report on {fmt_date(earnings)}", detail=detail, kind="earnings",
                               date=earnings))

    ex_div = _future_date(data.calendar.get("Ex-Dividend Date"))
    if ex_div and ex_div - datetime.now(timezone.utc) < timedelta(days=60):
        items.append(WatchItem(title=f"Ex-dividend date {fmt_date(ex_div)}", kind="dividend", date=ex_div,
                               detail="Shares bought on or after this date don't receive the next dividend."))

    # key price level: the nearest important level above or below
    levels = []
    if f.sma200 is not None:
        levels.append(("200-day average", f.sma200))
    if f.sma50 is not None:
        levels.append(("50-day average", f.sma50))
    levels.append(("52-week high", f.high))
    nearest = min(levels, key=lambda lv: abs(lv[1] / f.price - 1))
    distance = nearest[1] / f.price - 1
    side = "support below" if distance < 0 else "resistance above"
    items.append(WatchItem(
        title=f"{nearest[0].capitalize()} at {fmt_money(nearest[1], cur)}", kind="price_level",
        detail=(f"The nearest key level, {fmt_pct(distance)} from the current price. Holding it as {side} "
                "would support the current outlook; a decisive break would challenge it.")))

    coin = data.coin
    circ, max_supply = coin.get("circulating_supply"), coin.get("max_supply")
    if data.type == "crypto" and circ and max_supply and circ / max_supply < 0.7:
        items.append(WatchItem(
            title="Future token supply", kind="supply",
            detail=(f"{fmt_pct(circ / max_supply, signed=False)} of the maximum supply is circulating, so new "
                    "tokens entering the market could add selling pressure.")))
    elif data.type == "crypto" and f.btc_corr is not None and f.btc_corr > 0.6:
        items.append(WatchItem(title="Bitcoin's direction", kind="market",
                               detail=f"With a {f.btc_corr:.2f} correlation, a big move in Bitcoin is likely to "
                                      "carry this asset with it."))

    if f.rsi is not None and (f.rsi > 70 or f.rsi < 30) and len(items) < 3:
        items.append(WatchItem(title=f"RSI at {f.rsi:.0f}", kind="momentum",
                               detail="Watch whether momentum cools back into the 30–70 range."))
    return items[:3]


def build_risk(f: Facts, data: AssetData, sentiment: str, signals: list[Signal]) -> Risk:
    earnings = _future_date(data.calendar.get("Earnings Date"))
    if earnings and earnings - datetime.now(timezone.utc) < timedelta(days=21):
        return Risk(title="Upcoming earnings",
                    detail=f"The earnings report on {fmt_date(earnings)} could move the price sharply in either "
                           "direction and reset the outlook.")

    high_vol = 0.8 if data.type == "crypto" else 0.45
    if f.vol is not None and f.vol > high_vol:
        monthly = f.vol * math.sqrt(points(30, f.ppy) / f.ppy)
        return Risk(title="High volatility",
                    detail=f"With {fmt_pct(f.vol, signed=False)} annualized volatility, a typical month can swing "
                           f"about ±{fmt_pct(monthly, signed=False)}, enough to erase the current trend quickly.")

    pe = data.fundamentals.get("trailingPE")
    if pe and pe > 50 and sentiment != "bearish":
        return Risk(title="Rich valuation",
                    detail=f"At {pe:.0f}x earnings, the price assumes strong growth continues; any slowdown could "
                           "lead to a sharp re-rating.")

    if data.type == "crypto" and f.btc_corr is not None and f.btc_corr > 0.6:
        return Risk(title="Bitcoin dependence",
                    detail=f"Its {f.btc_corr:.2f} correlation with Bitcoin means a broad crypto sell-off would "
                           "likely override its own story.")

    opposing = [s for s in signals if (s.score < 0 if sentiment != "bearish" else s.score > 0)]
    if opposing:
        worst = max(opposing, key=lambda s: abs(s.impact))
        return Risk(title=worst.insight.title if worst.insight else worst.reason,
                    detail=(worst.insight.detail if worst.insight else worst.reason)
                    + " This works against the current outlook.")

    return Risk(title="Trend reversal",
                detail="All signals currently point the same way; a sudden change in market sentiment would be "
                       "the main thing to invalidate them.")


def build_scenarios(f: Facts, data: AssetData, sentiment: str) -> tuple[list[Scenario], Optional[str]]:
    cur = data.currency
    support = f.sma200 or f.sma50
    support_name = "200-day average" if f.sma200 else "50-day average"
    earnings = _future_date(data.calendar.get("Earnings Date"))
    earnings_soon = earnings and earnings - datetime.now(timezone.utc) < timedelta(days=30)

    bull_conditions, bear_conditions = [], []
    if support:
        bull_conditions.append(f"The price stays above the {support_name} ({fmt_money(support, cur)})")
        bear_conditions.append(f"A sustained break below the {support_name} ({fmt_money(support, cur)})")
    bull_conditions.append(f"A move through the 52-week high of {fmt_money(f.high, cur)}"
                           if f.high > f.price * 1.01 else "Momentum continues at new highs")
    if earnings_soon:
        bull_conditions.append(f"Earnings on {fmt_date(earnings)} beat expectations")
        bear_conditions.append(f"Earnings on {fmt_date(earnings)} disappoint")
    if data.type == "crypto" and f.btc_corr is not None and f.btc_corr > 0.5:
        bull_conditions.append("Bitcoin strengthens")
        bear_conditions.append("Bitcoin weakens")
    if f.volume_trend is not None:
        bull_conditions.append("Volume rises on up days")
        bear_conditions.append("Volume rises on down days")

    lean = {"bullish": "leans higher", "bearish": "leans lower", "neutral": "is balanced"}[sentiment]
    base_summary = (f"The evidence {lean}, so the most likely path is a continuation of recent behaviour within "
                    "the typical range below.")
    scenarios = [
        Scenario(case="bull", summary="Buyers stay in control and the price pushes toward the top of its range.",
                 conditions=bull_conditions[:3]),
        Scenario(case="base", summary=base_summary,
                 conditions=["No major surprise or change in trend", "Volatility stays near recent levels"]),
        Scenario(case="bear", summary="Sellers take over and the price falls toward the bottom of its range.",
                 conditions=bear_conditions[:3]),
    ]

    if f.vol is None or len(data.closes) < MIN_POINTS_FOR_RANGES:
        return scenarios, None

    for days in (7, 30):
        ranges = ind.scenario_ranges(f.price, f.vol, days, f.ppy)
        for scenario in scenarios:
            low, high = ranges[scenario.case]
            scenario.ranges.append(PriceRange(days=days, low=low, high=high))

    method = (f"Ranges assume the price keeps moving like it did over the last 90 days ({fmt_pct(f.vol, signed=False)} "
              "annualized volatility) with no built-in trend. Base = the middle 50% of outcomes; bull and bear = the "
              "75th–95th and 5th–25th percentiles. They describe typical swings, not predictions, and real moves can "
              "be larger.")
    return scenarios, method


def build_report(data: AssetData) -> AnalystReport:
    now = datetime.now(timezone.utc)
    asset = AssetInfo(symbol=data.symbol.upper(), name=data.name, type=data.type, currency=data.currency,
                      price=data.closes[-1] if data.closes else None)
    sources = [Source(**s) for s in data.sources]

    if len(data.closes) < MIN_POINTS:
        return AnalystReport(
            status="insufficient_data", asset=asset, generated_at=now, engine="rules",
            summary=(f"There isn't enough price history for {asset.name or asset.symbol} to produce a reliable "
                     f"outlook ({len(data.closes)} daily data points; at least {MIN_POINTS} are needed)."),
            sources=sources, limitations=data.limitations, disclaimer=DISCLAIMER)

    f = calculate_facts(data)
    signals = [s for s in (
        trend_signal(f, data), momentum_signal(f), rsi_signal(f), volume_signal(f),
        *( [fundamentals_signal(data), valuation_signal(data), analysts_signal(data)] if data.type == "stock"
           else crypto_signals(f, data) ),
    ) if s is not None]

    total_weight = sum(s.weight for s in signals)
    score = clamp(sum(s.impact for s in signals) / total_weight) if total_weight else 0.0
    sentiment = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"

    direction = 1 if score > 0 else -1
    agreeing = sum(s.weight for s in signals if s.score * direction > 0.05)
    agreement = agreeing / total_weight if total_weight else 0
    if len(signals) >= 4 and abs(score) > 0.35 and agreement >= 0.7:
        confidence = "high"
    elif abs(score) < 0.1 or agreement < 0.5 or len(signals) < 3:
        confidence = "low"
    else:
        confidence = "medium"

    if sentiment == "neutral":
        supporting = sorted(signals, key=lambda s: abs(s.impact), reverse=True)
    else:
        supporting = sorted([s for s in signals if s.score * direction > 0], key=lambda s: abs(s.impact),
                            reverse=True)
    reasons = [s.reason for s in supporting[:3]]

    ranked = sorted(signals, key=lambda s: abs(s.impact), reverse=True)
    insights, kinds = [], set()
    for s in ranked:
        if s.insight and s.insight.kind not in kinds:
            insights.append(s.insight)
            kinds.add(s.insight.kind)
        if len(insights) == 3:
            break

    name = asset.name or asset.symbol
    word = {"bullish": "a bullish", "bearish": "a bearish", "neutral": "a neutral"}[sentiment]
    sentences = [f"The data points to {word} outlook for {name} ({confidence} confidence)."]
    if f.r90 is not None:
        sentences.append(f"It is {fmt_pct(f.r90)} over 90 days"
                         + (f" and trades {'above' if f.price > f.sma200 else 'below'} its 200-day average."
                            if f.sma200 else "."))
    if supporting:
        lead = supporting[0]
        if lead.key not in ("trend", "momentum") and lead.insight:
            sentences.append(lead.insight.detail)
    opposing = [s for s in ranked if s.score * direction < -0.05 and sentiment != "neutral"]
    if opposing and opposing[0].insight:
        sentences.append(f"On the other side: {opposing[0].insight.title.lower()}.")
    summary = " ".join(sentences[:4])

    scenarios, range_method = build_scenarios(f, data, sentiment)
    risk = build_risk(f, data, sentiment, signals)

    change_level = f.sma200 or f.sma50
    if sentiment == "bullish" and change_level:
        change = f"a sustained drop below the {fmt_money(change_level, data.currency)} average level"
    elif sentiment == "bearish" and change_level:
        change = f"a recovery above the {fmt_money(change_level, data.currency)} average level"
    else:
        change = f"a decisive move out of the {fmt_money(f.low, data.currency)}–{fmt_money(f.high, data.currency)} range"
    lean_word = {"bullish": "favourable", "bearish": "unfavourable", "neutral": "mixed"}[sentiment]
    driver = (reasons[0][0].lower() + reasons[0][1:]) if reasons else "the price trend"
    bottom_line = (f"On balance the evidence is {lean_word}, driven mainly by {driver}. "
                   f"The view would change with {change}; the main risk to monitor is "
                   f"{risk.title[0].lower() + risk.title[1:]}.")

    last = data.times[-1]
    max_age = timedelta(days=2 if data.type == "crypto" else 4)
    stale = now - last > max_age
    return AnalystReport(
        status="ok", asset=asset, generated_at=now,
        period=Period(start=data.times[0], end=last, days=(last - data.times[0]).days),
        stale=stale,
        stale_reason=(f"The latest price data is from {fmt_date(last)}, so this analysis may not reflect recent moves."
                      if stale else None),
        engine="rules", sentiment=sentiment, confidence=confidence, score=round(score, 3),
        summary=summary, reasons=reasons, insights=insights, scenarios=scenarios, range_method=range_method,
        watch=build_watch(f, data), main_risk=risk, bottom_line=bottom_line,
        metrics=build_metrics(f, data), sources=sources, limitations=data.limitations, disclaimer=DISCLAIMER,
    )
