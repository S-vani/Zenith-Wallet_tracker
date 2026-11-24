"""
Portfolio X-Ray: the rules-based analyst for the whole portfolio. From today's holdings and a year of daily prices it
works out how concentrated the portfolio is, what it really owns once ETFs are looked through, how it moves against
the market, what a few stress scenarios would cost, and a 0-100 diversification score, then writes plain-English
findings built only from those numbers (no buy / sell advice, like the Market Analyst).

The maths (everything below build_xray's data loading) is pure, so tests feed it made-up holdings and prices.
"""
import asyncio
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import pstdev

from backend.services.asset_services import _asset_series, end_read, get_holdings_at_time, get_position_values_at
from backend.services.profiles import FUND_TYPES, stock_profile

BENCHMARK = ("^GSPC", "S&P 500")
TRADING_DAYS = 252
MIN_OVERLAP_DAYS = 60  # fewer common days than this: no beta / volatility / correlation
CORRELATED = 0.8
CACHE_SECONDS = 30 * 60
_cache: dict[tuple, tuple[float, dict]] = {}

# Yahoo's fund sector keys -> the names its stock profiles use
FUND_SECTOR_NAMES = {
    "realestate": "Real Estate", "consumer_cyclical": "Consumer Cyclical", "basic_materials": "Basic Materials",
    "consumer_defensive": "Consumer Defensive", "technology": "Technology", "communication_services":
    "Communication Services", "financial_services": "Financial Services", "utilities": "Utilities",
    "industrials": "Industrials", "energy": "Energy", "healthcare": "Healthcare",
}


# ---------------------------------------------------------------------------------------------------- pure maths
def concentration(weights: dict[str, float]) -> dict:
    """Top holding, top 3, and the effective number of holdings (1 / sum of squared weights)."""
    ordered = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    hhi = sum(w * w for w in weights.values())
    return {
        "top": {"symbol": ordered[0][0], "weight": ordered[0][1]} if ordered else None,
        "top3_weight": sum(w for _, w in ordered[:3]),
        "effective_holdings": 1 / hhi if hhi > 0 else 0.0,
        "count": len(weights),
    }


def region_of(profile: dict, api_id: str, asset_type: str) -> str:
    """Where an asset's business is: the stock's country, a fund's region guessed from its name, or Crypto."""
    if asset_type == "crypto":
        return "Crypto"
    if profile.get("quote_type") in FUND_TYPES:
        text = f"{profile.get('name') or ''} {profile.get('category') or ''}".lower()
        if any(k in text for k in ("all-world", "all world", "global", "all-equity", "all equity", "growth etf",
                                   "balanced etf", "world")):
            return "Global (fund)"
        if any(k in text for k in ("emerging",)):
            return "Emerging markets"
        if any(k in text for k in ("international", "ex-us", "ex us", "developed", "eafe", "europe")):
            return "International"
        if any(k in text for k in ("canad", "tsx")):
            return "Canada"
        if any(k in text for k in ("s&p 500", "us ", "u.s.", "total stock", "nasdaq", "total market")):
            return "United States"
        return "Canada" if api_id.upper().endswith((".TO", ".V", ".NE", ".CN")) else "United States"
    return profile.get("country") or ("Canada" if api_id.upper().endswith((".TO", ".V", ".NE", ".CN"))
                                      else "Unknown")


def look_through(weights: dict[str, float], types: dict[str, str], profiles: dict[str, dict]) -> dict:
    """
    Sector, region and company exposure with funds opened up: a fund's weight is split by its sector weights and
    top holdings (what's not in its top holdings stays as the fund). Crypto is its own sector and region.
    """
    sectors, regions, companies = defaultdict(float), defaultdict(float), defaultdict(float)
    via: dict[str, list[str]] = defaultdict(list)
    for api_id, w in weights.items():
        profile = profiles.get(api_id) or {}
        regions[region_of(profile, api_id, types[api_id])] += w
        if types[api_id] == "crypto":
            sectors["Crypto"] += w
            companies[api_id.upper()] += w
            continue
        if profile.get("quote_type") in FUND_TYPES:
            fund_sectors = profile.get("fund_sectors") or {}
            total = sum(fund_sectors.values())
            if total > 0:
                for key, sw in fund_sectors.items():
                    sectors[FUND_SECTOR_NAMES.get(key, key.replace("_", " ").title())] += w * sw / total
            else:
                sectors["Funds (no breakdown)"] += w
            inside = 0.0
            for h in profile.get("fund_holdings") or []:
                share = w * h["weight"]
                if share <= 0:
                    continue
                companies[h["symbol"].upper()] += share
                via[h["symbol"].upper()].append(api_id.upper())
                inside += share
            companies[f"{api_id.upper()} (rest of fund)"] += max(0.0, w - inside)
        else:
            sectors[profile.get("sector") or "Other"] += w
            companies[api_id.upper()] += w
    def ordered(d):
        return [{"name": k, "weight": v} for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)]

    top_companies = [c for c in ordered(companies) if "(rest of fund)" not in c["name"]][:8]
    for c in top_companies:
        c["via"] = sorted(set(via.get(c["name"], [])))
    return {"sectors": ordered(sectors), "regions": ordered(regions), "companies": top_companies}


def daily_returns(days: list, closes: list) -> dict:
    """{day: return since the previous close} from aligned day / close lists."""
    out = {}
    for i in range(1, len(closes)):
        if closes[i - 1] and closes[i] is not None:
            out[days[i]] = closes[i] / closes[i - 1] - 1
    return out


def _cov(a: list[float], b: list[float]) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)


def correlation(a: list[float], b: list[float]) -> float | None:
    sa, sb = pstdev(a), pstdev(b)
    return _cov(a, b) / (sa * sb) if sa > 0 and sb > 0 else None


def risk_stats(weights: dict[str, float], returns: dict[str, dict], benchmark: dict | None) -> dict:
    """
    The current portfolio replayed over the past year (today's weights, each holding's own daily returns): yearly
    volatility, worst peak-to-trough drop, beta and correlation against the benchmark, each holding's beta, and the
    pairs of holdings that move together. Days are the benchmark's trading days (crypto keeps those days' closes).
    """
    usable = {k: r for k, r in returns.items() if r and weights.get(k, 0) > 0}
    if not usable:
        return {"days": 0}
    days = sorted(set(benchmark) if benchmark else set().union(*[set(r) for r in usable.values()]))
    days = [d for d in days if any(d in r for r in usable.values())]
    if len(days) < MIN_OVERLAP_DAYS:
        return {"days": len(days)}
    weight_sum = sum(weights[k] for k in usable)
    port = []
    for d in days:
        port.append(sum(weights[k] * usable[k].get(d, 0.0) for k in usable) / weight_sum)
    vol = pstdev(port) * math.sqrt(TRADING_DAYS)
    level, peak, max_dd = 1.0, 1.0, 0.0
    for r in port:
        level *= 1 + r
        peak = max(peak, level)
        max_dd = min(max_dd, level / peak - 1)
    out = {"days": len(days), "volatility": vol, "max_drawdown": max_dd, "one_year_return": level - 1}
    if benchmark:
        bench = [benchmark.get(d, 0.0) for d in days]
        var_b = pstdev(bench) ** 2
        if var_b > 0:
            out["beta"] = _cov(port, bench) / var_b
            out["benchmark_correlation"] = correlation(port, bench)
            out["holding_betas"] = {k: _cov([usable[k].get(d, 0.0) for d in days], bench) / var_b for k in usable}
    names = sorted(usable, key=lambda k: weights[k], reverse=True)[:10]
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = [d for d in days if d in usable[a] and d in usable[b]]
            if len(common) < MIN_OVERLAP_DAYS:
                continue
            c = correlation([usable[a][d] for d in common], [usable[b][d] for d in common])
            if c is not None and c >= CORRELATED:
                pairs.append({"a": a.upper(), "b": b.upper(), "correlation": c})
    out["correlated_pairs"] = sorted(pairs, key=lambda p: p["correlation"], reverse=True)[:5]
    return out


def stress_tests(total: float, weights: dict[str, float], types: dict[str, str], exposure: dict, risk: dict,
                 currency: str, listing: dict[str, str]) -> list[dict]:
    """What a few plain scenarios would do to today's value (estimates from betas and exposures, not forecasts)."""
    tests = []
    betas = risk.get("holding_betas") or {}
    if betas:
        move = sum(weights[k] * -0.20 * betas.get(k, 1.0) for k in weights)
        tests.append({"name": "Stock market falls 20%", "change_pct": move, "change": total * move,
                      "how": "each holding moves by its own beta to the S&P 500 over the past year"})
    crypto = sum(w for k, w in weights.items() if types[k] == "crypto")
    if crypto > 0:
        tests.append({"name": "Crypto halves", "change_pct": -0.5 * crypto, "change": total * -0.5 * crypto,
                      "how": "every coin falls 50%, everything else stays put"})
    tech = next((s["weight"] for s in exposure["sectors"] if s["name"] == "Technology"), 0.0)
    if tech > 0:
        tests.append({"name": "Tech sells off 30%", "change_pct": -0.3 * tech, "change": total * -0.3 * tech,
                      "how": "your technology exposure, ETFs included, falls 30%"})
    foreign = sum(w for k, w in weights.items() if types[k] == "stock" and listing.get(k) and listing[k] != currency)
    if foreign > 0 and currency in ("CAD", "USD", "EUR"):
        tests.append({"name": f"The {'Canadian dollar' if currency == 'CAD' else currency} falls 10%",
                      "change_pct": 0.1 * foreign, "change": total * 0.1 * foreign,
                      "how": "holdings listed in other currencies are worth more in yours; the rest stay put"})
    return tests


def diversification_score(conc: dict, exposure: dict, risk: dict, weights: dict, types: dict) -> dict:
    """0-100 (higher = more spread out), with the reasons that took points off."""
    score, reasons = 100.0, []
    top = conc["top"]["weight"] if conc["top"] else 0
    if top > 0.10:
        cut = min(30.0, (top - 0.10) * 75)
        score -= cut
        reasons.append(("top", cut))
    eff = conc["effective_holdings"]
    if eff < 15:
        cut = min(25.0, (15 - eff) * 2)
        score -= cut
        reasons.append(("few", cut))
    sector = exposure["sectors"][0]["weight"] if exposure["sectors"] else 0
    if sector > 0.30:
        cut = min(20.0, (sector - 0.30) * 50)
        score -= cut
        reasons.append(("sector", cut))
    crypto = sum(w for k, w in weights.items() if types[k] == "crypto")
    if crypto > 0.10:
        cut = min(15.0, (crypto - 0.10) * 40)
        score -= cut
        reasons.append(("crypto", cut))
    vol = risk.get("volatility")
    if vol and vol > 0.20:
        cut = min(10.0, (vol - 0.20) * 40)
        score -= cut
        reasons.append(("volatile", cut))
    score = max(0.0, round(score))
    label = "Well diversified" if score >= 75 else "Fairly diversified" if score >= 50 else "Concentrated"
    return {"score": score, "label": label, "reasons": [r for r, _ in sorted(reasons, key=lambda x: -x[1])]}


def pct(x: float, digits: int = 0) -> str:
    return f"{x * 100:.{digits}f}%"


def findings(total: float, conc: dict, exposure: dict, risk: dict, tests: list[dict], money) -> list[dict]:
    """Plain-English observations, most important first; `money(value)` formats an amount."""
    out = []
    top = conc["top"]
    if top and top["weight"] >= 0.20:
        symbol = top["symbol"].upper()
        out.append({"level": "warn", "title": f"{symbol} is {pct(top['weight'])} of your portfolio",
                    "text": f"A 10% drop in {symbol} alone would take {money(total * top['weight'] * 0.1)} off your "
                            f"portfolio. One company's news moves everything."})
    if exposure["sectors"]:
        s = exposure["sectors"][0]
        if s["weight"] >= 0.35 and s["name"] not in ("Crypto", "Funds (no breakdown)"):
            out.append({"level": "warn", "title": f"{pct(s['weight'])} in {s['name']}",
                        "text": f"Counting what's inside your ETFs, {s['name'].lower()} is your biggest bet, so news "
                                f"for that industry moves most of your portfolio."})
    hidden = [c for c in exposure["companies"] if c.get("via") and c["weight"] >= 0.03]
    if hidden:
        c = hidden[0]
        out.append({"level": "info", "title": f"You own more {c['name']} than it looks",
                    "text": f"{c['name']} is {pct(c['weight'], 1)} of your portfolio once its share of "
                            f"{', '.join(c['via'])} is added in."})
    beta = risk.get("beta")
    if beta is not None:
        if beta >= 1.2:
            out.append({"level": "warn", "title": f"Moves {beta:.1f}× the market",
                        "text": f"Over the past year your holdings moved about {beta:.1f} times as much as the S&P 500 "
                                f"on a typical day, up and down."})
        elif beta <= 0.7:
            out.append({"level": "good", "title": f"Steadier than the market ({beta:.1f}×)",
                        "text": "Your holdings moved less than the S&P 500 on a typical day over the past year."})
    if risk.get("max_drawdown") is not None and risk["max_drawdown"] <= -0.20:
        drop = -risk["max_drawdown"]
        out.append({"level": "info", "title": f"Worst drop in a year: {pct(drop)}",
                    "text": f"Held as it is today, your portfolio would have fallen {pct(drop)} from its high at the "
                            f"worst point of the past year, about {money(total * drop)}."})
    for p in (risk.get("correlated_pairs") or [])[:2]:
        out.append({"level": "info", "title": f"{p['a']} and {p['b']} move together",
                    "text": f"Their daily moves had a correlation of {p['correlation']:.2f} over the past year, so "
                            f"they add less spread than two separate holdings usually would."})
    worst = min(tests, key=lambda t: t["change_pct"], default=None)
    if worst and worst["change_pct"] < -0.05:
        out.append({"level": "info", "title": f"Biggest scenario hit: {worst['name'].lower()}",
                    "text": f"That would take about {money(-worst['change'])} ({pct(-worst['change_pct'])}) off "
                            f"today's value."})
    if conc["effective_holdings"] >= 15 and (not conc["top"] or conc["top"]["weight"] < 0.10):
        out.append({"level": "good", "title": "Well spread out",
                    "text": f"No holding is over 10%, and your money is spread about as much as "
                            f"{conc['effective_holdings']:.0f} equal holdings."})
    order = {"warn": 0, "info": 1, "good": 2}
    return sorted(out, key=lambda f: order[f["level"]])


# ---------------------------------------------------------------------------------------------------- loading
def _listing_currency(api_id: str, asset_type: str) -> str | None:
    if asset_type == "crypto":
        return None
    return "CAD" if api_id.upper().endswith((".TO", ".V", ".NE", ".CN")) else "USD"


async def _returns_for(api_id: str, asset_type: str, coin_id: str | None) -> dict:
    try:
        series, _, _ = await _asset_series(api_id, asset_type, "1y", "1d", coin_id=coin_id)
    except Exception:
        return {}
    if not series:
        return {}
    return daily_returns(series.bar_days(), series.closes)


async def build_xray(session, user, money) -> dict:
    """The X-Ray of the user's portfolio now, in their currency (cached CACHE_SECONDS per user and currency)."""
    key = (str(user.id), user.currency)
    cached = cached_xray(user)
    if cached:
        return cached
    now = datetime.now(timezone.utc)
    holdings = await get_holdings_at_time(session, user.id, now, user.currency)
    values = await get_position_values_at(session, user.id, now, user.currency)
    await end_read(session)
    priced = {k: v for k, v in values.items() if v}
    total = sum(priced.values())
    if total <= 0:
        return {"empty": True, "currency": user.currency}
    weights = {k: v / total for k, v in priced.items()}
    types = {k: str(holdings[k]["type"]) for k in priced}
    coins = {k: holdings[k].get("coin_id") for k in priced}

    stocks = [k for k in priced if types[k] == "stock"]
    profiles = dict(zip(stocks, await asyncio.gather(*[stock_profile(k) for k in stocks])))
    returns = dict(zip(priced, await asyncio.gather(*[_returns_for(k, types[k], coins[k]) for k in priced])))
    benchmark = await _returns_for(BENCHMARK[0], "stock", None)

    conc = concentration(weights)
    exposure = look_through(weights, types, profiles)
    risk = risk_stats(weights, returns, benchmark or None)
    listing = {k: _listing_currency(k, types[k]) for k in priced}
    tests = stress_tests(total, weights, types, exposure, risk, user.currency, listing)
    score = diversification_score(conc, exposure, risk, weights, types)
    risk_out = {k: v for k, v in risk.items() if k != "holding_betas"}
    result = {
        "empty": False,
        "currency": user.currency,
        "total": total,
        "generated_at": now.isoformat(),
        "benchmark": BENCHMARK[1],
        "score": score,
        "concentration": conc,
        "holdings": [{"symbol": k.upper(), "type": types[k], "weight": weights[k],
                      "beta": (risk.get("holding_betas") or {}).get(k)}
                     for k in sorted(weights, key=lambda k: weights[k], reverse=True)],
        "exposure": exposure,
        "risk": risk_out,
        "stress_tests": tests,
        "findings": findings(total, conc, exposure, risk, tests, money),
        "unpriced": sorted(k.upper() for k, v in values.items() if not v),
        "limitations": [
            "Built from today's holdings and the past year of daily prices: how they behaved, not a forecast.",
            "ETFs are opened up using their sector weights and top holdings from Yahoo Finance; regions of funds are "
            "estimated from their names.",
            "Scenarios are simple estimates. Real markets rarely move one thing at a time.",
        ],
    }
    _cache[key] = (time.monotonic(), result)
    return result


def cached_xray(user) -> dict | None:
    """The user's X-Ray from the last CACHE_SECONDS, or None."""
    hit = _cache.get((str(user.id), user.currency))
    return hit[1] if hit and time.monotonic() - hit[0] < CACHE_SECONDS else None
