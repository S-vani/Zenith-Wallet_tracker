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

DISCLAIMER = ("Generated automatically by software from third-party market data, for information only. It is not "
              "financial or investment advice or a recommendation to buy or sell, and past price movements don't "
              "guarantee future results.")
MIN_POINTS = 30  # below this there isn't enough history to say anything meaningful
MIN_POINTS_FOR_RANGES = 60
MIN_RETURNS_FOR_CORRELATION = 60
SHORT_HISTORY_DAYS = 120  # less history than this caps confidence at "low"
CURRENCY_SYMBOL = {"CAD": "CA$", "USD": "$", "EUR": "€"}
MINUS = "−"


# --------------------------------------------------------------------------------------------------------- formatting
def _ok(value) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def fmt_pct(value: float, signed: bool = True, digits: int = 1) -> str:
    if not _ok(value):
        return "n/a"
    text = f"{abs(value) * 100:.{digits}f}%"
    if round(abs(value) * 100, digits) == 0:
        return text  # no sign on 0.0%
    if not signed:
        return text  # magnitude only, e.g. "32.9% below"
    return ("+" if value > 0 else MINUS) + text


def fmt_money(value: float, currency: str) -> str:
    if not _ok(value):
        return "n/a"
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
        body = f"{v:.{decimals}f}"
    return (MINUS if value < 0 else "") + sym + body


def fmt_num(value: float, digits: int = 2) -> str:
    """Plain number with a proper minus sign (e.g. correlations, EPS)."""
    if not _ok(value):
        return "n/a"
    text = f"{abs(value):,.{digits}f}"
    return (MINUS + text) if value < 0 and float(text.replace(",", "")) != 0 else text


def fmt_compact(value: float) -> str:
    if not _ok(value):
        return "n/a"
    v = abs(value)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= size:
            return (MINUS if value < 0 else "") + f"{v / size:.2f}{suffix}"
    return (MINUS if value < 0 else "") + f"{v:,.0f}"


def fmt_date(value) -> str:
    return value.strftime("%b %d, %Y").replace(" 0", " ")


def clamp(value: float, limit: float = 1.0) -> float:
    return max(-limit, min(limit, value))


def side(value: float, reference: float, tolerance: float = 0.001) -> int:
    """+1 above, -1 below, 0 when within `tolerance` (0.1%) of the reference: a flat price isn't a trend."""
    if value > reference * (1 + tolerance):
        return 1
    if value < reference * (1 - tolerance):
        return -1
    return 0


def position_word(value: float, reference: float) -> str:
    return {1: "above", -1: "below", 0: "at"}[side(value, reference)]


def change_phrase(value: float, period: str) -> str:
    """'a 33.9% gain over 90 days' / 'a 4.0% decline over 30 days' / 'no change over 30 days'."""
    if round(abs(value) * 100, 1) == 0:
        return f"no change over {period}"
    return f"a {fmt_pct(value, signed=False)} {'gain' if value > 0 else 'decline'} over {period}"


def up_down(value: float) -> str:
    """'up 33.9%' / 'down 4.0%' / 'flat'."""
    if round(abs(value) * 100, 1) == 0:
        return "flat"
    return f"{'up' if value > 0 else 'down'} {fmt_pct(value, signed=False)}"


def join_list(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def period_label(days: int) -> str:
    return "1 year" if 350 <= days <= 380 else f"{days} days"


# --------------------------------------------------------------------------------------------------------- signals
@dataclass
class Signal:
    key: str
    score: float  # -1 .. +1
    weight: float
    reason: str  # short phrase used in the reasons list ("Up 33.9% over 90 days")
    phrase: str  # noun phrase for sentences ("a 33.9% gain over 90 days")
    insight: Optional[Insight] = None
    can_be_risk: bool = True  # good news (deep liquidity, analyst targets) is never presented as the main risk

    @property
    def impact(self) -> float:
        return self.score * self.weight


@dataclass
class Facts:
    """Everything calculated from the data, shared by the text builders."""
    price: float
    ppy: int  # periods per year: 252 trading days (stocks) or 365 (crypto)
    history_days: int
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

    @property
    def short_history(self) -> bool:
        return self.history_days < SHORT_HISTORY_DAYS

    @property
    def window_label(self) -> str:
        """What the high/low/drawdown window really covers."""
        return "52-week" if self.history_days >= 350 else f"{self.history_days}-day"


def points(days: int, ppy: int) -> int:
    """How many daily data points cover `days` calendar days."""
    return days if ppy == 365 else max(1, round(days * 252 / 365))


def calculate_facts(data: AssetData) -> Facts:
    closes = data.closes
    ppy = 365 if data.type == "crypto" else 252
    year = closes[-points(365, ppy):]
    history_days = (data.times[-1] - data.times[0]).days

    r1y_days = None
    r1y = None
    if len(closes) >= points(300, ppy):
        r1y = closes[-1] / closes[0] - 1 if closes[0] > 0 else None
        r1y_days = history_days

    facts = Facts(
        price=closes[-1], ppy=ppy, history_days=history_days,
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

    if data.btc_closes and len(closes) > MIN_RETURNS_FOR_CORRELATION:
        own = ind.log_returns(closes[-91:])
        btc = ind.log_returns(data.btc_closes[-91:])
        if min(len(own), len(btc)) >= MIN_RETURNS_FOR_CORRELATION:
            facts.btc_corr = ind.correlation(own, btc)
        facts.btc_r30 = ind.pct_return(data.btc_closes, 30)
    return facts


def trend_signal(f: Facts, data: AssetData) -> Optional[Signal]:
    if f.sma50 is None:
        return None
    cur = data.currency
    price_50 = side(f.price, f.sma50)
    parts = [price_50]
    if f.sma200 is not None:
        parts += [side(f.price, f.sma200), side(f.sma50, f.sma200)]
    score = sum(parts) / len(parts)

    if score == 0 and all(p == 0 for p in parts):
        return Signal("trend", 0.0, 1.5, "Trading at its moving averages", "a price sitting at its moving averages",
                      Insight(title="No clear trend", kind="trend", tone="neutral",
                              detail=f"The price ({fmt_money(f.price, cur)}) is sitting at its moving averages, so "
                                     "there is no trend in either direction."))

    facts = [f"The price ({fmt_money(f.price, cur)}) is {position_word(f.price, f.sma50)} its 50-day average "
             f"({fmt_money(f.sma50, cur)})"]
    if f.sma200 is not None:
        facts.append(f"{position_word(f.price, f.sma200)} its 200-day average ({fmt_money(f.sma200, cur)})")
        cross = position_word(f.sma50, f.sma200)
        detail = f"{facts[0]} and {facts[1]}; the 50-day average is {cross} the 200-day."
        if score >= 0.99:
            title = "Uptrend intact"
        elif score <= -0.99:
            title = "Downtrend in place"
        else:
            title = "Mixed trend signals"
        long_side = position_word(f.price, f.sma200)
        reason = f"Trading {long_side} its 200-day average"
        phrase = f"the price trading {long_side} its 200-day average"
    else:
        detail = facts[0] + "."
        title = {1: "Short-term uptrend", -1: "Short-term downtrend"}.get(price_50, "No clear short-term trend")
        reason = f"Trading {position_word(f.price, f.sma50)} its 50-day average"
        phrase = f"the price trading {position_word(f.price, f.sma50)} its 50-day average"

    # only a clean trend gets a colour; mixed signals stay neutral
    tone = "positive" if score >= 0.99 else "negative" if score <= -0.99 else "neutral"
    if f.sma200 is None:
        tone = "positive" if price_50 > 0 else "negative" if price_50 < 0 else "neutral"
    return Signal("trend", score, 1.5, reason, phrase, Insight(title=title, detail=detail, kind="trend", tone=tone))


def momentum_signal(f: Facts) -> Optional[Signal]:
    if f.r90 is None and f.r30 is None:
        return None
    score, weights = 0.0, 0.0
    if f.r90 is not None:
        score += clamp(f.r90 / 0.25) * 0.6
        weights += 0.6
    if f.r30 is not None:
        score += clamp(f.r30 / 0.10) * 0.4
        weights += 0.4
    score /= weights

    bits = []
    if f.r7 is not None and abs(f.r7) >= 0.05:
        bits.append(f"{up_down(f.r7)} over 7 days")
    if f.r30 is not None:
        bits.append(f"{up_down(f.r30)} over 30 days")
    if f.r90 is not None:
        bits.append(f"{up_down(f.r90)} over 90 days")
    if f.r1y is not None:
        bits.append(f"{up_down(f.r1y)} over {'the past year' if 350 <= (f.r1y_days or 0) <= 380 else f'{f.r1y_days} days'}")

    cooling = score > 0.15 and f.r7 is not None and f.r7 <= -0.05
    reviving = score < -0.15 and f.r7 is not None and f.r7 >= 0.05
    if cooling:
        title = "Momentum cooling"
    elif reviving:
        title = "Selling easing"
    else:
        title = ("Strong recent momentum" if score > 0.5 else "Positive recent momentum" if score > 0.15
                 else "Weak recent momentum" if score < -0.5 else "Negative recent momentum" if score < -0.15
                 else "Flat recent momentum")

    candidates = [(d, r) for d, r in (("90 days", f.r90), ("30 days", f.r30)) if r is not None]
    matching = [(d, r) for d, r in candidates if (r > 0) == (score > 0) and round(abs(r) * 100, 1) > 0]
    if abs(score) <= 0.15 or not matching:
        reason, phrase = "Flat momentum", "flat momentum"
    else:
        period, main = matching[0]
        reason = f"{up_down(main).capitalize()} over {period}"
        phrase = change_phrase(main, period)

    tone = "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"
    detail = "The price is " + join_list(bits) + "."
    return Signal("momentum", score, 1.5, reason, phrase,
                  Insight(title=title, detail=detail, kind="momentum", tone=tone))


def rsi_signal(f: Facts) -> Optional[Signal]:
    if f.rsi is None or 30 <= f.rsi <= 70:
        return None
    if f.rsi > 70:
        return Signal("rsi", -0.4, 0.5, f"Overbought (RSI {f.rsi:.0f})", f"an overbought RSI of {f.rsi:.0f}", Insight(
            title="Looks stretched", kind="momentum", tone="negative",
            detail=f"The 14-day RSI is {f.rsi:.0f} (above 70), which often comes before a pause or pullback."))
    return Signal("rsi", 0.4, 0.5, f"Oversold (RSI {f.rsi:.0f})", f"an oversold RSI of {f.rsi:.0f}", Insight(
        title="Oversold", kind="momentum", tone="positive",
        detail=f"The 14-day RSI is {f.rsi:.0f} (below 30); sellers may be exhausted, though downtrends can persist."))


def volume_signal(f: Facts) -> Optional[Signal]:
    # needs a real price move to interpret, and a meaningful change in volume
    if f.volume_trend is None or f.r30 is None or abs(f.volume_trend) < 0.2 or abs(f.r30) < 0.01:
        return None
    vol_text = f"Average daily volume over the last 20 days is {fmt_pct(f.volume_trend)} vs the prior 90 days"
    if f.volume_trend > 0:
        score = 0.5 if f.r30 > 0 else -0.5
        title = "Buying interest rising" if f.r30 > 0 else "Selling pressure building"
        phrase = "rising volume on gains" if f.r30 > 0 else "rising volume on losses"
        detail = f"{vol_text}, while the price is {up_down(f.r30)} over 30 days."
    else:
        score = -0.2 if f.r30 > 0 else 0.1
        title = "Participation fading"
        phrase = "fading trading volume"
        detail = f"{vol_text}, so recent moves have less conviction behind them."
    tone = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    return Signal("volume", score, 0.8, title, phrase, Insight(title=title, detail=detail, kind="volume", tone=tone))


def fundamentals_signal(data: AssetData) -> Optional[Signal]:
    fu = data.fundamentals
    rg, eg, pm = fu.get("revenueGrowth"), fu.get("earningsGrowth"), fu.get("profitMargins")
    if data.is_fund or (not _ok(rg) and not _ok(eg) and not _ok(pm)):
        return None
    parts, bits = [], []
    if _ok(rg):
        parts.append(clamp(rg / 0.2))
        bits.append(f"revenue growth of {fmt_pct(rg)} year over year")
    if _ok(eg):
        parts.append(clamp(eg / 0.25))
        bits.append(f"earnings growth of {fmt_pct(eg)}")
    if _ok(pm):
        if pm < 0:
            parts.append(-1.0)
            bits.append(f"a loss, with a {fmt_pct(pm)} profit margin")
        elif pm < 0.05:
            parts.append(-0.3)
            bits.append(f"a thin {fmt_pct(pm, signed=False)} profit margin")
        else:
            parts.append(0.4 if pm > 0.15 else 0.0)
            bits.append(f"a {fmt_pct(pm, signed=False)} profit margin")
    score = sum(parts) / len(parts)
    if _ok(pm) and pm < 0:
        score = min(score, -0.2)  # a loss-making company can't have "solid" fundamentals, whatever its growth

    title = ("Strong fundamentals" if score > 0.5 else "Solid fundamentals" if score > 0.25
             else "Weak fundamentals" if score < -0.3 else "Mixed fundamentals")
    tone = "positive" if score > 0.25 else "negative" if score < -0.1 else "neutral"
    detail = "Latest reported figures show " + join_list(bits) + "."
    # the reason names the figure that pushes in the same direction as the overall score
    lead = next((bit for part, bit in zip(parts, bits) if (part < 0) == (score < 0)), bits[0])
    reason = lead[0].upper() + lead[1:]
    return Signal("fundamentals", score, 1.2, reason, lead,
                  Insight(title=title, detail=detail, kind="fundamentals", tone=tone))


def valuation_signal(data: AssetData) -> Optional[Signal]:
    fu = data.fundamentals
    pe, fpe = fu.get("trailingPE"), fu.get("forwardPE")
    if not _ok(pe) or pe <= 0:
        return None
    score = 0.0
    if pe > 100:
        score -= 0.8
    elif pe > 60:
        score -= 0.5
    elif pe > 35:
        score -= 0.2
    elif pe < 15:
        score += 0.2
    growth_note = ""
    if _ok(fpe) and 0 < fpe < pe * 0.8:
        score += 0.3
        growth_note = f" The forward P/E of {fpe:.1f}x is lower, meaning analysts expect earnings to grow."
    elif _ok(fpe) and fpe > pe * 1.1:
        score -= 0.2
        growth_note = f" The forward P/E of {fpe:.1f}x is higher, meaning earnings are expected to shrink."
    level = "very high" if pe > 100 else "high" if pe > 35 else "moderate" if pe > 15 else "low"
    subject = "The fund's holdings trade" if data.is_fund else "It trades"
    detail = f"{subject} at {pe:.1f}x trailing earnings, a {level} multiple.{growth_note}"
    tone = "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"
    return Signal("valuation", clamp(score), 0.8, f"{level.capitalize()} valuation ({pe:.1f}x earnings)",
                  f"a {level} valuation of {pe:.1f}x earnings",
                  Insight(title=f"{level.capitalize()} valuation", detail=detail, kind="valuation", tone=tone))


def native_to_user(data: AssetData, amount: float) -> Optional[float]:
    """Convert an amount quoted in the stock's own currency (Yahoo fundamentals) into the user's currency, using the
    ratio between the converted price history and Yahoo's current price."""
    current = data.fundamentals.get("currentPrice")
    if not _ok(current) or not current or not data.closes:
        return None
    return amount * data.closes[-1] / current


def consensus_words(mean: Optional[float]) -> Optional[str]:
    """Yahoo's 1 (most positive) – 5 (most negative) analyst score, in plain words without buy/sell advice."""
    if not _ok(mean):
        return None
    words = ("very positive" if mean <= 1.5 else "positive" if mean <= 2.5 else "neutral" if mean <= 3.5
             else "negative" if mean <= 4.5 else "very negative")
    return f"{words} ({mean:.1f} on a 1–5 scale, 1 = most positive)"


def analysts_signal(data: AssetData) -> Optional[Signal]:
    fu = data.fundamentals
    n, target, current = fu.get("numberOfAnalystOpinions"), fu.get("targetMeanPrice"), fu.get("currentPrice")
    rec = fu.get("recommendationMean")
    if not n or n < 3 or not _ok(target) or not _ok(current) or not current:
        return None
    upside = target / current - 1
    score = clamp(upside / 0.2) * 0.6 + (clamp((3 - rec) / 1.5) * 0.4 if _ok(rec) else 0)
    target_user = native_to_user(data, target)
    target_text = fmt_money(target_user, data.currency) if target_user else f"{fmt_num(target)} {fu.get('currency', '')}"
    where = "above" if upside > 0 else "below"
    consensus = consensus_words(rec)
    detail = (f"The average target of {n} analysts is {target_text}, {fmt_pct(upside, signed=False)} {where} the last "
              "price" + (f", and their overall view is {consensus}." if consensus else "."))
    tone = "positive" if upside > 0.05 else "negative" if upside < -0.05 else "neutral"
    return Signal("analysts", score, 0.7, f"Analyst targets {fmt_pct(upside, signed=False)} {where} the price",
                  f"analyst targets {fmt_pct(upside, signed=False)} {where} the price",
                  Insight(title="Analyst targets", detail=detail, kind="analysts", tone=tone), can_be_risk=False)


def crypto_signals(f: Facts, data: AssetData) -> list[Signal]:
    coin, cur = data.coin, data.currency
    signals = []

    mcap, volume = coin.get("market_cap"), coin.get("total_volume")
    if _ok(mcap) and _ok(volume) and mcap:
        turnover = volume / mcap
        digits = 2 if turnover < 0.01 else 1
        if turnover < 0.01:
            signals.append(Signal("liquidity", -0.4, 0.6, "Thin trading volume", "thin trading volume", Insight(
                title="Thin liquidity", kind="volume", tone="negative",
                detail=(f"24h volume of {fmt_money(volume, cur)} is only {fmt_pct(turnover, signed=False, digits=digits)} "
                        f"of its {fmt_money(mcap, cur)} market cap, so large orders can move the price."))))
        elif turnover > 0.05:
            signals.append(Signal("liquidity", 0.2, 0.4, "Actively traded", "active trading", Insight(
                title="Deep liquidity", kind="volume", tone="positive",
                detail=(f"24h volume of {fmt_money(volume, cur)} is {fmt_pct(turnover, signed=False, digits=digits)} "
                        f"of its {fmt_money(mcap, cur)} market cap.")), can_be_risk=False))

    ath_change = coin.get("ath_change_percentage")
    if _ok(ath_change) and coin.get("ath"):
        from_ath = ath_change / 100
        score = 0.2 if from_ath > -0.1 else -0.3 if from_ath < -0.7 else 0.0
        title = ("At its all-time high" if from_ath > -0.005 else "Near all-time high" if from_ath > -0.1
                 else "Far below all-time high" if from_ath < -0.7 else "Below all-time high")
        where = ("at its all-time high" if from_ath > -0.005
                 else f"{fmt_pct(from_ath, signed=False)} below its all-time high")
        signals.append(Signal("ath", score, 0.5, title, f"trading {where}", Insight(
            title=title, kind="market", tone="positive" if score > 0 else "negative" if score < 0 else "neutral",
            detail=f"It is {where} of {fmt_money(coin['ath'], cur)}."), can_be_risk=score < 0))

    if _ok(f.btc_corr) and _ok(f.btc_r30) and f.btc_corr > 0.5:
        score = clamp(f.btc_r30 / 0.1) * 0.5
        signals.append(Signal("btc", score, 0.7, f"Moves with Bitcoin (correlation {fmt_num(f.btc_corr)})",
                              f"its close link to Bitcoin (correlation {fmt_num(f.btc_corr)})", Insight(
            title="Tied to Bitcoin", kind="correlation",
            tone="positive" if score > 0.1 else "negative" if score < -0.1 else "neutral",
            detail=(f"Daily moves have a {fmt_num(f.btc_corr)} correlation with Bitcoin over 90 days, and Bitcoin is "
                    f"{up_down(f.btc_r30)} over 30 days."))))
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
    coin = data.coin
    if data.is_stablecoin and _ok(coin.get("price_usd")) and cur != "USD":
        m.append(Metric(label="Price in USD", value=fmt_money(coin["price_usd"], "USD"), group="performance"))
    for label, value in (("7-day return", f.r7), ("30-day return", f.r30), ("90-day return", f.r90)):
        if value is not None:
            m.append(Metric(label=label, value=fmt_pct(value), group="performance"))
    if f.r1y is not None:
        m.append(Metric(label=f"{period_label(f.r1y_days or 0)} return".capitalize(), value=fmt_pct(f.r1y),
                        group="performance"))
    m.append(Metric(label=f"{f.window_label} range".capitalize(),
                    value=f"{fmt_money(f.low, cur)} – {fmt_money(f.high, cur)}", group="performance"))
    if f.sma50 is not None:
        m.append(Metric(label="50-day average", value=fmt_money(f.sma50, cur), group="trend"))
    if f.sma200 is not None:
        m.append(Metric(label="200-day average", value=fmt_money(f.sma200, cur), group="trend"))
    if f.rsi is not None:
        m.append(Metric(label="RSI (14-day)", value=f"{f.rsi:.0f}", group="trend"))
    if f.vol is not None:
        m.append(Metric(label="Volatility (annualized, 90-day)", value=fmt_pct(f.vol, signed=False), group="risk"))
    if f.drawdown is not None:
        window = "1 year" if f.history_days >= 350 else f"{f.history_days} days"
        m.append(Metric(label=f"Max drawdown ({window})", value=fmt_pct(f.drawdown), group="risk"))
    if f.volume_trend is not None:
        m.append(Metric(label="Volume, 20-day vs prior 90-day", value=fmt_pct(f.volume_trend), group="volume"))

    fu = data.fundamentals
    native = fu.get("financialCurrency") or fu.get("currency") or ""
    if _ok(fu.get("marketCap")):
        m.append(Metric(label=f"Market cap ({fu.get('currency', native)})", value=fmt_compact(fu["marketCap"]),
                        group="fundamentals"))
    if not data.is_fund:
        for key, label in (("revenueGrowth", "Revenue growth (YoY)"), ("earningsGrowth", "Earnings growth (YoY)"),
                           ("profitMargins", "Profit margin"), ("operatingMargins", "Operating margin")):
            if _ok(fu.get(key)):
                # growth is always signed; margins only show a sign when negative (a loss)
                value = fmt_pct(fu[key]) if key.endswith("Growth") or fu[key] < 0 else fmt_pct(fu[key], signed=False)
                m.append(Metric(label=label, value=value, group="fundamentals"))
        if _ok(fu.get("freeCashflow")) and fu["freeCashflow"]:
            m.append(Metric(label=f"Free cash flow ({native})", value=fmt_compact(fu["freeCashflow"]),
                            group="fundamentals"))
    for key, label in (("trailingPE", "P/E (trailing)"), ("forwardPE", "P/E (forward)"),
                       ("priceToSalesTrailing12Months", "Price / sales")):
        if _ok(fu.get(key)) and fu[key] > 0:  # a negative P/E (losses) isn't meaningful
            m.append(Metric(label=label, value=f"{fu[key]:.1f}x", group="valuation"))
    if _ok(fu.get("targetMeanPrice")) and fu.get("numberOfAnalystOpinions"):
        target_user = native_to_user(data, fu["targetMeanPrice"])
        m.append(Metric(label="Analyst mean target",
                        value=fmt_money(target_user, cur) if target_user else fmt_num(fu["targetMeanPrice"]),
                        group="analysts"))
        m.append(Metric(label="Analysts covering", value=str(fu["numberOfAnalystOpinions"]), group="analysts"))
        if _ok(fu.get("currentPrice")) and fu["currentPrice"]:
            m.append(Metric(label="Analyst target vs price",
                            value=fmt_pct(fu["targetMeanPrice"] / fu["currentPrice"] - 1), group="analysts"))
    consensus = consensus_words(fu.get("recommendationMean"))
    if consensus and fu.get("numberOfAnalystOpinions"):
        m.append(Metric(label="Analyst consensus", value=consensus.split(" (")[0].capitalize()
                        + f" ({fu['recommendationMean']:.1f}/5)", group="analysts"))

    if _ok(coin.get("market_cap")):
        rank = f" (#{coin['market_cap_rank']})" if coin.get("market_cap_rank") else ""
        m.append(Metric(label="Market cap", value=fmt_money(coin["market_cap"], cur) + rank, group="market"))
    if _ok(coin.get("total_volume")):
        m.append(Metric(label="24h volume", value=fmt_money(coin["total_volume"], cur), group="volume"))
    if _ok(coin.get("ath")):
        m.append(Metric(label="All-time high", value=fmt_money(coin["ath"], cur), group="market"))
    if _ok(coin.get("ath_change_percentage")) and coin.get("ath"):
        m.append(Metric(label="Distance from all-time high", value=fmt_pct(coin["ath_change_percentage"] / 100),
                        group="market"))
    if _ok(coin.get("market_cap")) and _ok(coin.get("total_volume")) and coin["market_cap"]:
        turnover = coin["total_volume"] / coin["market_cap"]
        m.append(Metric(label="24h volume / market cap",
                        value=fmt_pct(turnover, signed=False, digits=2 if turnover < 0.01 else 1), group="volume"))
    if _ok(coin.get("circulating_supply")):
        m.append(Metric(label="Circulating supply", value=fmt_compact(coin["circulating_supply"]), group="supply"))
    if _ok(coin.get("max_supply")):
        m.append(Metric(label="Max supply", value=fmt_compact(coin["max_supply"]), group="supply"))
    elif _ok(coin.get("circulating_supply")):
        m.append(Metric(label="Max supply", value="Not reported", group="supply"))
    if f.btc_corr is not None:
        m.append(Metric(label="Correlation with BTC (90-day)", value=fmt_num(f.btc_corr), group="market"))
    if f.btc_r30 is not None:
        m.append(Metric(label="Bitcoin 30-day return", value=fmt_pct(f.btc_r30), group="market"))
    return m


def _key_levels(f: Facts) -> list[tuple[str, float]]:
    levels = []
    if f.sma200 is not None:
        levels.append(("200-day average", f.sma200))
    if f.sma50 is not None:
        levels.append(("50-day average", f.sma50))
    levels.append((f"{f.window_label} high", f.high))
    return levels


def build_watch(f: Facts, data: AssetData, sentiment: str) -> list[WatchItem]:
    cur, items = data.currency, []
    earnings = _future_date(data.calendar.get("Earnings Date"))
    if earnings and earnings - datetime.now(timezone.utc) < timedelta(days=90):
        est = data.calendar.get("Earnings Average")
        lo, hi = data.calendar.get("Earnings Low"), data.calendar.get("Earnings High")
        native = data.fundamentals.get("financialCurrency") or data.fundamentals.get("currency") or ""
        detail = "Results and guidance often cause the biggest single-day moves for a stock."
        if _ok(est):
            detail = (f"Analysts expect earnings per share of about {fmt_num(est)} {native}".rstrip()
                      + (f" (range {fmt_num(lo)} to {fmt_num(hi)})" if _ok(lo) and _ok(hi) else "") + ". " + detail)
        items.append(WatchItem(title="Earnings report", detail=detail, kind="earnings", date=earnings))

    ex_div = _future_date(data.calendar.get("Ex-Dividend Date"))
    if ex_div and ex_div - datetime.now(timezone.utc) < timedelta(days=60):
        items.append(WatchItem(title="Ex-dividend date", kind="dividend", date=ex_div,
                               detail="Shares bought on or after this date don't receive the next dividend."))

    if data.is_stablecoin:
        if _ok(data.coin.get("price_usd")):
            items.append(WatchItem(title="The $1.00 peg", kind="price_level",
                                   detail=f"It is trading at {fmt_money(data.coin['price_usd'], 'USD')}. A sustained "
                                          "move away from $1.00 would signal stress for the stablecoin."))
        if cur != "USD":
            items.append(WatchItem(title=f"USD/{cur} exchange rate", kind="market",
                                   detail=f"Its price in {cur} moves almost entirely with the US dollar's exchange "
                                          "rate."))
        return items[:3]

    # the nearest important price level, described from where the price actually is
    name, level = min(_key_levels(f), key=lambda lv: abs(lv[1] / f.price - 1))
    distance = level / f.price - 1
    if abs(distance) < 0.005:
        title = f"Trading at its {name}"
        detail = (f"The price is right at its {name} ({fmt_money(level, cur)}). Whether it holds above or slips "
                  "below this level is the next signal to watch.")
    elif distance < 0:
        title = f"{name.capitalize()} at {fmt_money(level, cur)}"
        detail = (f"The nearest support, {fmt_pct(distance, signed=False)} below the current price. Staying above it "
                  "keeps the current picture intact; a drop below would weaken it.")
    else:
        title = f"{name.capitalize()} at {fmt_money(level, cur)}"
        detail = (f"The nearest resistance, {fmt_pct(distance, signed=False)} above the current price. A move through "
                  "it would add strength; failing there could cap further gains.")
    items.append(WatchItem(title=title, kind="price_level", detail=detail))

    coin = data.coin
    circ, max_supply = coin.get("circulating_supply"), coin.get("max_supply")
    if data.type == "crypto" and _ok(circ) and _ok(max_supply) and max_supply and circ / max_supply < 0.7:
        items.append(WatchItem(
            title="Future token supply", kind="supply",
            detail=(f"{fmt_pct(circ / max_supply, signed=False)} of the maximum supply is circulating, so new "
                    "tokens entering the market could add selling pressure.")))
    elif data.type == "crypto" and _ok(f.btc_corr) and f.btc_corr > 0.6:
        items.append(WatchItem(title="Bitcoin's direction", kind="market",
                               detail=f"With a {fmt_num(f.btc_corr)} correlation, a big move in Bitcoin is likely to "
                                      "carry this asset with it."))

    if f.rsi is not None and len(items) < 3:
        if f.rsi > 70:
            items.append(WatchItem(title=f"RSI at {f.rsi:.0f}", kind="momentum",
                                   detail="Watch whether buying cools and the RSI falls back below 70."))
        elif f.rsi < 30:
            items.append(WatchItem(title=f"RSI at {f.rsi:.0f}", kind="momentum",
                                   detail="Watch whether selling eases and the RSI recovers above 30."))
    return items[:3]


def _swing_risk(f: Facts) -> Optional[Risk]:
    if f.vol is None:
        return None
    monthly = f.vol * math.sqrt(points(30, f.ppy) / f.ppy)
    return Risk(title="Normal price swings",
                detail=f"Even without news, a typical month moves about ±{fmt_pct(monthly, signed=False)} for this "
                       "asset, which is enough to change the short-term picture.")


def build_risk(f: Facts, data: AssetData, sentiment: str, signals: list[Signal]) -> tuple[Risk, Optional[str]]:
    """
    The main risk, plus a short phrase naming it for the bottom line ("its rich valuation"). The phrase is None when
    the risk is only the asset's ordinary volatility: the scenario ranges already show that.
    """
    earnings = _future_date(data.calendar.get("Earnings Date"))
    if earnings and earnings - datetime.now(timezone.utc) < timedelta(days=21):
        return Risk(title="Upcoming earnings",
                    detail=f"The earnings report on {fmt_date(earnings)} could move the price sharply in either "
                           "direction and reset the outlook."), "the upcoming earnings report"

    pe = data.fundamentals.get("trailingPE")
    if _ok(pe) and pe > 50 and sentiment != "bearish":
        return Risk(title="Rich valuation",
                    detail=f"At {pe:.1f}x earnings, the price assumes strong growth continues; any slowdown could "
                           "lead to a sharp re-rating."), "its rich valuation"

    high_vol = 0.8 if data.type == "crypto" else 0.45
    if f.vol is not None and f.vol > high_vol:
        monthly = f.vol * math.sqrt(points(30, f.ppy) / f.ppy)
        return Risk(title="High volatility",
                    detail=f"With {fmt_pct(f.vol, signed=False)} annualized volatility, a typical month can swing "
                           f"about ±{fmt_pct(monthly, signed=False)}, enough to erase the current trend quickly."), \
            "its high volatility, which can erase a trend quickly"

    if data.type == "crypto" and _ok(f.btc_corr) and f.btc_corr > 0.6 and sentiment != "bearish":
        return Risk(title="Bitcoin dependence",
                    detail=f"Its {fmt_num(f.btc_corr)} correlation with Bitcoin means a broad crypto sell-off would "
                           "likely override its own story."), "a broad crypto sell-off led by Bitcoin"

    # the strongest real counter-signal: for a bullish/neutral view a negative one, for a bearish view an upside one
    if sentiment == "bearish":
        opposing = [s for s in signals if s.score >= 0.3 and s.can_be_risk]
    else:
        opposing = [s for s in signals if s.score <= -0.3 and s.can_be_risk]
    if opposing:
        top = max(opposing, key=lambda s: abs(s.impact))
        if top.insight:
            if sentiment == "bearish":
                return Risk(title=f"Upside risk: {top.insight.title[0].lower() + top.insight.title[1:]}",
                            detail=top.insight.detail + " That could support a rebound against the bearish view."), \
                    f"a rebound, given {top.phrase}"
            return Risk(title=top.insight.title,
                        detail=top.insight.detail + " This is the main factor working against the outlook."), \
                top.phrase

    if data.type == "crypto" and _ok(f.btc_corr) and f.btc_corr > 0.6:
        return Risk(title="Bitcoin dependence",
                    detail=f"Its {fmt_num(f.btc_corr)} correlation with Bitcoin means a broad crypto rally or "
                           "sell-off would likely override its own story."), "a big move in Bitcoin"
    swings = _swing_risk(f)
    if swings:
        return swings, None
    return Risk(title="Trend reversal",
                detail="The signals point the same way for now; a sudden change in market sentiment would challenge "
                       "them."), "a sudden change in market sentiment"


def build_scenarios(f: Facts, data: AssetData, sentiment: str) -> tuple[list[Scenario], Optional[str]]:
    cur = data.currency
    level = f.sma200 or f.sma50
    level_name = "200-day average" if f.sma200 else "50-day average"
    earnings = _future_date(data.calendar.get("Earnings Date"))
    earnings_soon = earnings and earnings - datetime.now(timezone.utc) < timedelta(days=30)

    bull_conditions, bear_conditions = [], []
    if data.is_stablecoin:
        bull_conditions = ["The peg holds near $1.00"] + (
            [f"The US dollar strengthens against the {cur}"] if cur != "USD" else [])
        bear_conditions = ["Confidence in its reserves weakens and the peg slips"] + (
            [f"The US dollar weakens against the {cur}"] if cur != "USD" else [])
    else:
        if level:
            where = side(f.price, level)
            text = f"the {level_name} ({fmt_money(level, cur)})"
            if where >= 0:
                bull_conditions.append(f"The price stays above {text}")
                bear_conditions.append(f"A sustained break below {text}")
            else:
                bull_conditions.append(f"A recovery above {text}")
                bear_conditions.append(f"The price stays below {text}")

        # an upside target the price could plausibly reach: the window high if it's close, else the 50-day average
        thirty_day_top = f.price * math.exp(ind.Z_05 * f.vol * math.sqrt(points(30, f.ppy) / f.ppy)) if f.vol else None
        if f.high <= f.price * 1.005:
            bull_conditions.append(f"Momentum carries it to new {f.window_label} highs")
        elif thirty_day_top and f.high <= thirty_day_top:
            bull_conditions.append(f"A move through the {f.window_label} high of {fmt_money(f.high, cur)}")
        elif f.sma50 and f.sma50 > f.price * 1.005 and level != f.sma50:
            bull_conditions.append(f"A recovery above the 50-day average ({fmt_money(f.sma50, cur)})")

        if earnings_soon:
            bull_conditions.append("The upcoming earnings report beats expectations")
            bear_conditions.append("The upcoming earnings report disappoints")
        if data.type == "crypto" and _ok(f.btc_corr) and f.btc_corr > 0.5:
            bull_conditions.append("Bitcoin strengthens")
            bear_conditions.append("Bitcoin weakens")
        if f.volume_trend is not None:
            bull_conditions.append("Volume rises on up days")
            bear_conditions.append("Volume rises on down days")

    if data.is_stablecoin:
        base_summary = (f"The peg holds and the price in {cur} follows the exchange rate within the small range below."
                        if cur != "USD" else "The peg holds and the price stays within the small range below.")
        bull_summary = "The peg holds and exchange-rate moves lift the price to the top of its small range."
        bear_summary = "Pressure on the peg or the exchange rate pushes the price to the bottom of its range."
    else:
        # the base range is symmetric around the current price (no built-in trend), so it isn't described as leaning
        # either way, whatever the overall outlook
        base_summary = ("No major surprise: the price keeps swinging the way it has recently and ends up in the middle "
                        "of its typical range, a little above or below where it is now.")
        bull_summary = ("Buyers stay in control and the price pushes toward the top of its range."
                        if sentiment == "bullish" else
                        "Buyers regain control and the price rallies toward the top of its typical range.")
        bear_summary = ("Sellers stay in control and the price falls toward the bottom of its range."
                        if sentiment == "bearish" else
                        "Sellers take over and the price falls toward the bottom of its typical range.")
    scenarios = [
        Scenario(case="bull", summary=bull_summary, conditions=bull_conditions[:3]),
        Scenario(case="base", summary=base_summary,
                 conditions=["No major surprise or change in trend", "Volatility stays near recent levels"]),
        Scenario(case="bear", summary=bear_summary, conditions=bear_conditions[:3]),
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


def _confidence(signals: list[Signal], score: float, f: Facts) -> str:
    total_weight = sum(s.weight for s in signals)
    direction = 1 if score > 0 else -1
    agreeing = sum(s.weight for s in signals if s.score * direction > 0.05)
    agreement = agreeing / total_weight if total_weight else 0
    # disagreement caps confidence at medium: a split trend (the price and its averages pointing different ways)
    # or a real counter-signal carrying a meaningful share of the weight. Otherwise "high confidence" could sit
    # next to "Mixed trend signals" in the same report.
    opposing = sum(s.weight for s in signals if s.score * direction < -0.15)
    split_trend = any(s.key == "trend" and abs(s.score) < 0.99 for s in signals)
    disagreement = split_trend or (total_weight and opposing / total_weight >= 0.15)
    if f.short_history:
        return "low"
    if (agreement >= 0.7 and not disagreement
            and ((len(signals) >= 4 and abs(score) > 0.35) or (len(signals) >= 3 and abs(score) > 0.6))):
        return "high"
    if abs(score) < 0.1 or agreement < 0.5 or len(signals) < 3:
        return "low"
    return "medium"


def build_report(data: AssetData) -> AnalystReport:
    now = datetime.now(timezone.utc)
    asset = AssetInfo(symbol=data.symbol.upper(), name=data.name, type=data.type, currency=data.currency,
                      price=data.closes[-1] if data.closes else None)
    sources = [Source(**s) for s in data.sources]
    limitations = list(data.limitations)

    if len(data.closes) < MIN_POINTS:
        if not data.closes:
            summary = (f"No market data was found for {asset.name or asset.symbol}. Check the symbol, or try again "
                       "later if the data provider is having trouble.")
        else:
            summary = (f"There isn't enough price history for {asset.name or asset.symbol} to produce a reliable "
                       f"outlook ({len(data.closes)} daily data points; at least {MIN_POINTS} are needed).")
        return AnalystReport(status="insufficient_data", asset=asset, generated_at=now, engine="rules",
                             summary=summary, sources=sources, limitations=limitations, disclaimer=DISCLAIMER)

    f = calculate_facts(data)
    name = asset.name or asset.symbol
    if f.short_history:
        limitations.append(f"Only {f.history_days} days of price history are available, so trend and risk measures "
                           "are less reliable and confidence is capped at low.")

    if data.is_stablecoin:
        signals = [s for s in crypto_signals(f, data) if s.key == "liquidity"]
        score, sentiment = 0.0, "neutral"
        confidence = "high" if not f.short_history else "low"
        reasons = ["Designed to hold a fixed $1.00 value"]
        fx = (f" Its price in {data.currency} is {up_down(f.r30)} over 30 days, which reflects the US dollar's "
              f"exchange rate rather than demand for the coin." if data.currency != "USD" and f.r30 is not None else "")
        summary = (f"{name} is a stablecoin designed to stay at one US dollar, so a bullish or bearish price outlook "
                   f"doesn't apply.{fx}")
        if data.currency != "USD":
            reasons.append(f"Price in {data.currency} follows the USD exchange rate")
        insights = [Insight(title="Built to hold its value", kind="market", tone="neutral",
                            detail=f"{name} aims to stay at $1.00, so price moves are small; the key question is "
                                   "whether its reserves keep the peg secure.")]
        insights += [s.insight for s in signals if s.insight][:1]
        risk = Risk(title="Losing the peg",
                    detail="If confidence in its reserves weakened, the price could fall below $1.00, as has happened "
                           "to other stablecoins in the past.")
        bottom_line = (f"{name} is built for stability rather than growth, so the outlook is neutral by design. The "
                       "main thing to monitor is whether it keeps trading at $1.00.")
    else:
        signals = [s for s in (
            trend_signal(f, data), momentum_signal(f), rsi_signal(f), volume_signal(f),
            *([fundamentals_signal(data), valuation_signal(data), analysts_signal(data)] if data.type == "stock"
              else crypto_signals(f, data)),
        ) if s is not None]

        total_weight = sum(s.weight for s in signals)
        score = clamp(sum(s.impact for s in signals) / total_weight) if total_weight else 0.0
        sentiment = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
        confidence = _confidence(signals, score, f)
        direction = 1 if score > 0 else -1

        ranked = sorted(signals, key=lambda s: abs(s.impact), reverse=True)
        if sentiment == "neutral":
            supporting = [s for s in ranked if abs(s.score) > 0.15]
        else:
            supporting = [s for s in ranked if s.score * direction > 0.15]
        reasons = [s.reason for s in supporting[:3]]

        insights, kinds = [], set()
        for s in ranked:
            if s.insight and s.insight.kind not in kinds:
                insights.append(s.insight)
                kinds.add(s.insight.kind)
            if len(insights) == 3:
                break

        word = {"bullish": "a bullish", "bearish": "a bearish", "neutral": "a neutral"}[sentiment]
        sentences = [f"The data points to {word} outlook for {name} ({confidence} confidence)."]
        if f.r90 is not None:
            trend = f" and trades {position_word(f.price, f.sma200)} its 200-day average." if f.sma200 else "."
            sentences.append(f"It is {up_down(f.r90)} over 90 days{trend}")
        if supporting and supporting[0].key not in ("trend", "momentum") and supporting[0].insight:
            sentences.append(supporting[0].insight.detail)
        opposing = [s for s in ranked if s.score * direction < -0.15] if sentiment != "neutral" else []
        if opposing:
            sentences.append(f"The main counterpoint is {opposing[0].phrase}.")
        summary = " ".join(sentences[:4])

        risk, risk_phrase = build_risk(f, data, sentiment, signals)

        level = f.sma200 or f.sma50
        level_name = "200-day average" if f.sma200 else "50-day average"
        cur = data.currency
        if sentiment == "neutral" or not level:
            change = (f"A decisive move out of the {fmt_money(f.low, cur)}–{fmt_money(f.high, cur)} range would set "
                      "the next direction.")
        elif sentiment == "bullish":
            change = (f"A sustained drop below the {level_name} ({fmt_money(level, cur)}) would weaken this view."
                      if side(f.price, level) >= 0 else
                      f"A recovery above the {level_name} ({fmt_money(level, cur)}) would strengthen it.")
        else:
            change = (f"A recovery above the {level_name} ({fmt_money(level, cur)}) would challenge this view."
                      if side(f.price, level) <= 0 else
                      f"A drop below the {level_name} ({fmt_money(level, cur)}) would confirm it.")
        lean_word = {"bullish": "favourable", "bearish": "unfavourable", "neutral": "mixed"}[sentiment]
        driver = supporting[0].phrase if supporting else "the recent price action"
        bottom_line = f"On balance the evidence is {lean_word}, driven mainly by {driver}. {change}"
        if risk_phrase:  # ordinary volatility is already covered by the scenario ranges, so it isn't repeated here
            bottom_line += f" The main risk to watch is {risk_phrase}."

    scenarios, range_method = build_scenarios(f, data, sentiment)

    last = data.times[-1]
    max_age = timedelta(days=2 if data.type == "crypto" else 4)
    stale = now - last > max_age
    return AnalystReport(
        status="ok", asset=asset, generated_at=now,
        period=Period(start=data.times[0], end=last, days=f.history_days),
        stale=stale,
        stale_reason=(f"The latest price data is from {fmt_date(last)}, so this analysis may not reflect recent moves."
                      if stale else None),
        engine="rules", sentiment=sentiment, confidence=confidence, score=round(score, 3),
        summary=summary, reasons=reasons, insights=insights, scenarios=scenarios, range_method=range_method,
        watch=build_watch(f, data, sentiment), main_risk=risk, bottom_line=bottom_line,
        metrics=build_metrics(f, data), sources=sources, limitations=limitations, disclaimer=DISCLAIMER,
    )
