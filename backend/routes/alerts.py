"""
Watchlist, price alerts, the notification inbox and its settings, and push device registration.

GET/POST /watchlist, DELETE /watchlist/{type}/{api_id}; GET/POST /alerts, DELETE /alerts/{id};
GET /notifications, POST /notifications/read, GET/PUT /notifications/settings; POST/DELETE /push/devices.
The checks themselves run in the background (services/alerts.py).
"""
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.alerts import Alert, Notification, NotificationSettings, PushDevice, WatchItem
from backend.db_models.assets import User
from backend.services.alerts import settings_for
from backend.services.asset_services import end_read, get_prices_at

router = APIRouter(tags=["alerts"])

MAX_WATCHLIST = 50
MAX_ACTIVE_ALERTS = 50
INBOX_SIZE = 100

ApiId = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-^=]+$")
CoinId = Field(default=None, max_length=100, pattern=r"^[a-z0-9-]+$")


class WatchIn(BaseModel):
    api_id: str = ApiId
    type: Literal["stock", "crypto"]
    coin_id: Optional[str] = CoinId
    name: Optional[str] = Field(default=None, max_length=120)


class AlertIn(BaseModel):
    api_id: str = ApiId
    type: Literal["stock", "crypto"]
    coin_id: Optional[str] = CoinId
    kind: Literal["above", "below", "move"]
    # a price in the user's currency (above / below), or a % move (move: 1 to 50)
    threshold: float = Field(gt=0, le=1e9)


class SettingsIn(BaseModel):
    daily_briefing: bool
    holding_events: bool
    push: bool


class DeviceIn(BaseModel):
    token: str = Field(min_length=32, max_length=200, pattern=r"^[0-9a-fA-F]+$")


def _api_id(api_id: str, asset_type: str) -> str:
    """Stocks keep Yahoo's upper case (SHOP.TO), coins CoinGecko's lower case (btc), like trades."""
    return api_id.upper() if asset_type == "stock" else api_id.lower()


# ---------------------------------------------------------------------------------------------------- watchlist
@router.get("/watchlist")
async def get_watchlist(session: AsyncSession = Depends(get_async_session),
                        user: User = Depends(current_active_user)):
    """The watchlist, newest first, each with its price now and its change over 24 hours in the user's currency."""
    items = (await session.scalars(select(WatchItem).where(WatchItem.user_id == user.id)
                                   .order_by(WatchItem.created_at.desc()))).all()
    await end_read(session)
    assets = {i.api_id: i.asset_type for i in items}
    coins = {i.api_id: i.coin_id for i in items if i.coin_id}
    now = datetime.now(timezone.utc)
    prices = await get_prices_at(assets, now, user.currency, coin_ids=coins) if assets else {}
    before = await get_prices_at(assets, now - timedelta(days=1), user.currency, coin_ids=coins) if assets else {}
    out = []
    for i in items:
        p, b = prices.get(i.api_id), before.get(i.api_id)
        out.append({"api_id": i.api_id, "type": i.asset_type, "coin_id": i.coin_id, "name": i.name, "price": p,
                    "day_change_pct": (p / b - 1) * 100 if p is not None and b else None})
    return out


@router.post("/watchlist", status_code=201)
async def add_to_watchlist(body: WatchIn, session: AsyncSession = Depends(get_async_session),
                           user: User = Depends(current_active_user)):
    """Stars an asset (adding one that's already there changes nothing)."""
    api_id = _api_id(body.api_id, body.type)
    existing = await session.scalar(select(WatchItem).where(
        WatchItem.user_id == user.id, WatchItem.asset_type == body.type, WatchItem.api_id == api_id))
    if existing:
        return {"api_id": api_id, "type": body.type}
    count = await session.scalar(select(func.count()).select_from(WatchItem).where(WatchItem.user_id == user.id))
    if count >= MAX_WATCHLIST:
        raise HTTPException(422, f"Your watchlist is full ({MAX_WATCHLIST} assets). Remove one to add another.")
    session.add(WatchItem(user_id=user.id, api_id=api_id, asset_type=body.type, coin_id=body.coin_id,
                          name=body.name))
    await session.commit()
    return {"api_id": api_id, "type": body.type}


@router.delete("/watchlist/{asset_type}/{api_id}", status_code=204)
async def remove_from_watchlist(asset_type: Literal["stock", "crypto"], api_id: str,
                                session: AsyncSession = Depends(get_async_session),
                                user: User = Depends(current_active_user)):
    await session.execute(delete(WatchItem).where(
        WatchItem.user_id == user.id, WatchItem.asset_type == asset_type,
        WatchItem.api_id == _api_id(api_id, asset_type)))
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------------- alerts
def _alert_json(a: Alert) -> dict:
    return {"id": a.id, "api_id": a.api_id, "type": a.asset_type, "coin_id": a.coin_id, "kind": a.kind,
            "threshold": a.threshold, "currency": a.currency, "active": a.active,
            "last_triggered_at": a.last_triggered_at.isoformat() if a.last_triggered_at else None}


@router.get("/alerts")
async def list_alerts(session: AsyncSession = Depends(get_async_session), user: User = Depends(current_active_user)):
    """The user's alerts, active first, newest first."""
    rows = (await session.scalars(select(Alert).where(Alert.user_id == user.id)
                                  .order_by(Alert.active.desc(), Alert.created_at.desc()))).all()
    return [_alert_json(a) for a in rows]


@router.post("/alerts", status_code=201)
async def create_alert(body: AlertIn, session: AsyncSession = Depends(get_async_session),
                       user: User = Depends(current_active_user)):
    """A new alert; a price threshold is in the user's display currency."""
    if body.kind == "move" and not 1 <= body.threshold <= 50:
        raise HTTPException(422, "A daily move alert needs a size between 1% and 50%.")
    active = await session.scalar(select(func.count()).select_from(Alert).where(
        Alert.user_id == user.id, Alert.active.is_(True)))
    if active >= MAX_ACTIVE_ALERTS:
        raise HTTPException(422, f"You have {MAX_ACTIVE_ALERTS} active alerts, the most allowed. Delete one first.")
    alert = Alert(user_id=user.id, api_id=_api_id(body.api_id, body.type), asset_type=body.type,
                  coin_id=body.coin_id, kind=body.kind, threshold=body.threshold, currency=user.currency)
    session.add(alert)
    await session.commit()
    return _alert_json(alert)


@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: str, session: AsyncSession = Depends(get_async_session),
                       user: User = Depends(current_active_user)):
    await session.execute(delete(Alert).where(Alert.user_id == user.id, Alert.id == alert_id))
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------------- inbox
@router.get("/notifications")
async def list_notifications(session: AsyncSession = Depends(get_async_session),
                             user: User = Depends(current_active_user)):
    """The newest INBOX_SIZE notifications and how many are unread."""
    rows = (await session.scalars(select(Notification).where(Notification.user_id == user.id)
                                  .order_by(Notification.created_at.desc()).limit(INBOX_SIZE))).all()
    unread = await session.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {
        "unread": unread,
        "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
                   "created_at": n.created_at.isoformat(), "read": n.read_at is not None} for n in rows],
    }


@router.post("/notifications/read", status_code=204)
async def mark_read(session: AsyncSession = Depends(get_async_session), user: User = Depends(current_active_user)):
    """Marks every notification read (opening the inbox)."""
    await session.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                          .values(read_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    await session.commit()
    return Response(status_code=204)


@router.get("/notifications/settings")
async def get_settings(session: AsyncSession = Depends(get_async_session),
                       user: User = Depends(current_active_user)):
    s = await settings_for(session, user.id)
    return {"daily_briefing": s.daily_briefing, "holding_events": s.holding_events, "push": s.push}


@router.put("/notifications/settings")
async def put_settings(body: SettingsIn, session: AsyncSession = Depends(get_async_session),
                       user: User = Depends(current_active_user)):
    row = await session.get(NotificationSettings, user.id)
    if row is None:
        row = NotificationSettings(user_id=user.id)
        session.add(row)
    row.daily_briefing, row.holding_events, row.push = body.daily_briefing, body.holding_events, body.push
    await session.commit()
    return body.model_dump()


# ---------------------------------------------------------------------------------------------------- push
@router.post("/push/devices", status_code=204)
async def register_device(body: DeviceIn, session: AsyncSession = Depends(get_async_session),
                          user: User = Depends(current_active_user)):
    """The app's APNs token for this phone; it moves to whoever is signed in on the phone now."""
    token = body.token.lower()
    row = await session.get(PushDevice, token)
    if row is None:
        session.add(PushDevice(token=token, user_id=user.id))
    else:
        row.user_id = user.id
    await session.commit()
    return Response(status_code=204)


@router.delete("/push/devices/{token}", status_code=204)
async def unregister_device(token: str, session: AsyncSession = Depends(get_async_session),
                            user: User = Depends(current_active_user)):
    """Signing out on the phone: stop sending this account's notifications to it."""
    await session.execute(delete(PushDevice).where(PushDevice.user_id == user.id, PushDevice.token == token.lower()))
    await session.commit()
    return Response(status_code=204)
