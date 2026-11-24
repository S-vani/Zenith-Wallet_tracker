"""
Smart alerts: price alerts, holding events and the daily briefing, delivered to the in-app inbox (table
notifications) and, when the user allows it and APNs is configured, as push notifications (services/push.py).

One background loop (run_alerts_forever, started in main.py's lifespan; the API runs as one process) does:
- every ALERT_CHECK_SECONDS: price alerts ("above" / "below" fire once and switch off; "move" fires when today's move
  passes the threshold, at most once per Toronto day);
- once a day after BRIEFING_HOUR in Toronto, per user: holding events (earnings or ex-dividend tomorrow, a holding
  crossing its 200-day average) and the morning briefing (value and change since yesterday, the biggest movers,
  events in the next 7 days, alerts that fired).
Prices come from the same cached sources as the rest of the app; nothing here gives buy / sell advice.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.db.database import async_session_maker
from backend.db_models.alerts import Alert, Notification, NotificationSettings, PushDevice
from backend.db_models.assets import Transaction, User
from backend.services.asset_services import (
    _asset_series, end_read, get_holdings_at_time, get_prices_at, holding_coin_ids,
)
from backend.services.profiles import stock_profile
from backend.services.push import send_push

log = logging.getLogger("uvicorn.error")

TORONTO = ZoneInfo("America/Toronto")
ALERT_CHECK_SECONDS = 5 * 60
BRIEFING_HOUR = 8  # local Toronto time
KEEP_NOTIFICATIONS = timedelta(days=60)
EVENT_LOOKAHEAD_DAYS = 7

SYMBOLS = {"CAD": "CA$", "USD": "US$", "EUR": "€"}


def money(value: float, currency: str) -> str:
    """CA$1,234.56 / US$… / €… (the app's formatMoney style: USD is never a bare $)."""
    sign = "−" if value < 0 else ""
    return f"{sign}{SYMBOLS.get(currency, currency + ' ')}{abs(value):,.2f}"


def signed_money(value: float, currency: str) -> str:
    """+CA$12.00 / −CA$12.00"""
    return money(value, currency) if value < 0 else "+" + money(value, currency)


def signed_pct(pct: float) -> str:
    return f"{'+' if pct >= 0 else '−'}{abs(pct):.2f}%"


def asset_link(api_id: str, asset_type: str) -> str:
    """The Search screen opened on this asset (the app and website both understand it)."""
    return f"/search?q={api_id}&type={asset_type}"


def toronto_today(now: datetime) -> str:
    return now.astimezone(TORONTO).date().isoformat()


# ---------------------------------------------------------------------------------------------------- delivery
async def settings_for(session, user_id) -> NotificationSettings:
    """The user's settings row (defaults when there's none yet; not added to the session)."""
    row = await session.get(NotificationSettings, user_id)
    return row or NotificationSettings(user_id=user_id, daily_briefing=True, holding_events=True, push=True)


async def notify(session, user_id, kind: str, title: str, body: str, link: str | None = None,
                 dedupe_key: str | None = None) -> bool:
    """
    Adds an inbox entry and pushes it to the user's phones (if they allow push). With a dedupe_key nothing happens
    when an entry with that key already exists. Commits. Returns whether a notification was created.
    """
    if dedupe_key:
        exists = await session.scalar(select(Notification.id).where(
            Notification.user_id == user_id, Notification.dedupe_key == dedupe_key).limit(1))
        if exists:
            return False
    session.add(Notification(user_id=user_id, kind=kind, title=title, body=body, link=link, dedupe_key=dedupe_key))
    await session.commit()
    settings = await settings_for(session, user_id)
    if settings.push:
        tokens = (await session.scalars(select(PushDevice.token).where(PushDevice.user_id == user_id))).all()
        await end_read(session)
        for token in tokens:
            if await send_push(token, title, body, link) == "gone":
                await session.execute(delete(PushDevice).where(PushDevice.token == token))
                await session.commit()
    return True


# ---------------------------------------------------------------------------------------------------- price alerts
async def check_price_alerts(now: datetime | None = None) -> int:
    """Fires the price alerts whose condition is met. Returns how many fired."""
    now = now or datetime.now(timezone.utc)
    fired = 0
    async with async_session_maker() as session:
        alerts = (await session.scalars(select(Alert).where(Alert.active.is_(True)))).all()
        if not alerts:
            return 0
        # one price lookup per currency, for every asset alerted in it
        by_currency: dict[str, dict[str, str]] = {}
        coin_ids: dict[str, str] = {}
        for a in alerts:
            by_currency.setdefault(a.currency, {})[a.api_id] = a.asset_type
            if a.coin_id:
                coin_ids[a.api_id] = a.coin_id
        await end_read(session)
        prices, previous = {}, {}
        for currency, assets in by_currency.items():
            prices[currency] = await get_prices_at(assets, now, currency, coin_ids=coin_ids)
            if any(a.kind == "move" and a.currency == currency for a in alerts):
                previous[currency] = await get_prices_at(assets, now - timedelta(days=1), currency, coin_ids=coin_ids)

        today = toronto_today(now)
        for a in alerts:
            price = prices.get(a.currency, {}).get(a.api_id)
            if price is None:
                continue
            symbol = a.api_id.upper()
            if a.kind == "above" and price >= a.threshold or a.kind == "below" and price <= a.threshold:
                word = "above" if a.kind == "above" else "below"
                title = f"{symbol} is {word} {money(a.threshold, a.currency)}"
                body = f"{symbol} is at {money(price, a.currency)}. This alert is now off; set a new one any time."
                a.active = False
            elif a.kind == "move":
                before = previous.get(a.currency, {}).get(a.api_id)
                if not before:
                    continue
                pct = (price / before - 1) * 100
                last = a.last_triggered_at
                already = last is not None and toronto_today(last.replace(tzinfo=timezone.utc)) == today
                if abs(pct) < a.threshold or already:
                    continue
                title = f"{symbol} {'up' if pct > 0 else 'down'} {abs(pct):.1f}% in a day"
                body = f"{symbol} is at {money(price, a.currency)}, {signed_pct(pct)} over the last 24 hours."
            else:
                continue
            a.last_triggered_at = now.replace(tzinfo=None)
            await session.commit()
            await notify(session, a.user_id, "alert", title, body, link=asset_link(a.api_id, a.asset_type))
            fired += 1
    return fired


# ---------------------------------------------------------------------------------------------------- daily
async def crossed_200_day(api_id: str, asset_type: str, coin_id: str | None) -> str | None:
    """"above" / "below" when the latest daily close crossed the 200-day average since the close before."""
    try:
        series, _, _ = await _asset_series(api_id, asset_type, "1y", "1d", coin_id=coin_id)
    except Exception:
        return None
    closes = [c for c in (series.closes if series else []) if c is not None]
    if len(closes) < 202:
        return None
    avg_now = sum(closes[-200:]) / 200
    avg_before = sum(closes[-201:-1]) / 200
    if closes[-2] <= avg_before and closes[-1] > avg_now:
        return "above"
    if closes[-2] >= avg_before and closes[-1] < avg_now:
        return "below"
    return None


async def holding_events(holdings: dict, now: datetime) -> list[dict]:
    """Upcoming earnings / ex-dividend dates (next 7 days) and fresh 200-day crossings of these holdings."""
    today = now.astimezone(TORONTO).date()
    events = []
    for api_id, data in holdings.items():
        if str(data["type"]) == "stock":
            profile = await stock_profile(api_id)
            for key, label in (("earnings_date", "earnings"), ("ex_dividend_date", "ex-dividend date")):
                when = profile.get(key)
                if when and 0 <= (when - today).days <= EVENT_LOOKAHEAD_DAYS:
                    events.append({"api_id": api_id, "type": "stock", "kind": key, "label": label, "date": when})
        crossing = await crossed_200_day(api_id, str(data["type"]), data.get("coin_id"))
        if crossing:
            events.append({"api_id": api_id, "type": str(data["type"]), "kind": "ma200", "label": crossing,
                           "date": today})
    return events


def when_text(day, today) -> str:
    """"today", "tomorrow" or "Thu Jan 28"."""
    days = (day - today).days
    return "today" if days == 0 else "tomorrow" if days == 1 else f"{day.strftime('%a %b')} {day.day}"


async def run_daily_for_user(session, user: User, now: datetime, fired_today: int) -> None:
    """Holding events and the morning briefing for one user (whatever their settings allow)."""
    settings = await settings_for(session, user.id)
    holdings = await get_holdings_at_time(session, user.id, now, user.currency)
    await end_read(session)
    if not holdings:
        return
    today = now.astimezone(TORONTO).date()
    events = await holding_events(holdings, now) if (settings.holding_events or settings.daily_briefing) else []

    if settings.holding_events:
        for e in events:
            symbol = e["api_id"].upper()
            if e["kind"] == "ma200":
                title = f"{symbol} moved {e['label']} its 200-day average"
                body = (f"{symbol} closed {e['label']} its 200-day average, a level many investors watch for a change "
                        f"in trend. Open it for the full Market Analyst report.")
            elif (e["date"] - today).days <= 1:  # only the day before / the day of, the briefing lists the rest
                title = f"{symbol} {e['label']} {when_text(e['date'], today)}"
                body = (f"{symbol} reports earnings {when_text(e['date'], today)}; results often move the price."
                        if e["kind"] == "earnings_date" else
                        f"Shares bought on or after {symbol}'s ex-dividend date ({when_text(e['date'], today)}) don't "
                        f"get the next dividend.")
            else:
                continue
            await notify(session, user.id, "event", title, body, link=asset_link(e["api_id"], e["type"]),
                         dedupe_key=f"event:{e['kind']}:{e['api_id']}:{e['date'].isoformat()}")

    if settings.daily_briefing:
        await send_briefing(session, user, holdings, events, now, fired_today)
    row = await session.get(NotificationSettings, user.id)
    if row is None:
        row = NotificationSettings(user_id=user.id, daily_briefing=True, holding_events=True, push=True)
        session.add(row)
    row.briefing_sent_on = toronto_today(now)
    await session.commit()


async def send_briefing(session, user: User, holdings: dict, events: list[dict], now: datetime,
                        fired_today: int) -> None:
    """The morning summary: value and its change since yesterday, the biggest movers and what's coming up."""
    types = {api_id: str(d["type"]) for api_id, d in holdings.items()}
    coins = holding_coin_ids(holdings)
    current = await get_prices_at(types, now, user.currency, coin_ids=coins)
    before = await get_prices_at(types, now - timedelta(days=1), user.currency, coin_ids=coins)
    value_now = value_before = 0.0
    moves = []
    for api_id, data in holdings.items():
        p, b = current.get(api_id), before.get(api_id)
        if p is None or b is None:
            continue
        qty = float(data["quantity"])
        value_now += p * qty
        value_before += b * qty
        if b:
            moves.append((api_id.upper(), (p / b - 1) * 100))
    if value_now <= 0:
        return
    change = value_now - value_before
    pct = change / value_before * 100 if value_before else 0.0
    parts = [f"Your portfolio is {money(value_now, user.currency)}, {signed_money(change, user.currency)} "
             f"({signed_pct(pct)}) since yesterday."]
    moves.sort(key=lambda m: m[1])
    if moves:
        best, worst = moves[-1], moves[0]
        if best[1] > 0:
            parts.append(f"Best: {best[0]} {signed_pct(best[1])}.")
        if worst[1] < 0 and worst[0] != best[0]:
            parts.append(f"Worst: {worst[0]} {signed_pct(worst[1])}.")
    today = now.astimezone(TORONTO).date()
    upcoming = [e for e in events if e["kind"] != "ma200"]
    if upcoming:
        upcoming.sort(key=lambda e: e["date"])
        listed = ", ".join(f"{e['api_id'].upper()} {e['label']} {when_text(e['date'], today)}" for e in upcoming[:3])
        parts.append(f"Coming up: {listed}.")
    if fired_today:
        parts.append(f"{fired_today} of your alerts fired since yesterday.")
    title = f"Good morning: {signed_pct(pct)} overnight"
    await notify(session, user.id, "briefing", title, " ".join(parts), link="/dashboard",
                 dedupe_key=f"briefing:{toronto_today(now)}")


async def run_daily(now: datetime | None = None) -> int:
    """The daily pass for every user who hasn't had it today (after BRIEFING_HOUR Toronto). Returns how many."""
    now = now or datetime.now(timezone.utc)
    if now.astimezone(TORONTO).hour < BRIEFING_HOUR:
        return 0
    today = toronto_today(now)
    done = 0
    async with async_session_maker() as session:
        # the ids as Python UUIDs: users and transactions store them in different column types, so an IN subquery
        # comparing the two columns never matches
        traders = (await session.scalars(select(Transaction.user_id).distinct())).all()
        users = (await session.scalars(
            select(User).where(User.is_active.is_(True), User.is_verified.is_(True), User.id.in_(traders))
        )).unique().all() if traders else []  # unique(): User eager-loads its Google links
        rows = (await session.scalars(select(NotificationSettings))).all()
        sent = {row.user_id: row.briefing_sent_on for row in rows}
        since = (now - timedelta(days=1)).replace(tzinfo=None)
        for user in users:
            if sent.get(user.id) == today:
                continue
            fired = await session.scalar(select(Notification.id).where(
                Notification.user_id == user.id, Notification.kind == "alert",
                Notification.created_at >= since).limit(1))
            try:
                await run_daily_for_user(session, user, now, 1 if fired else 0)
                done += 1
            except Exception as exc:  # one user's data problem mustn't stop everyone's briefing
                log.warning("Daily alerts failed for a user: %s", type(exc).__name__)
                await session.rollback()
        # the inbox keeps 60 days
        cutoff = (now - KEEP_NOTIFICATIONS).replace(tzinfo=None)
        await session.execute(delete(Notification).where(Notification.created_at < cutoff))
        await session.commit()
    return done


def background_jobs_enabled() -> bool:
    """Off with DISABLE_BACKGROUND_JOBS=1 (the tests set it; they run the jobs directly)."""
    return os.getenv("DISABLE_BACKGROUND_JOBS", "").strip().lower() not in ("1", "true", "yes")


async def run_alerts_forever() -> None:
    """The alerts loop: price alerts every ALERT_CHECK_SECONDS, the daily pass when it's due."""
    while True:
        try:
            await check_price_alerts()
            await run_daily()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Alerts check failed: %s", type(exc).__name__)
        await asyncio.sleep(ALERT_CHECK_SECONDS)
