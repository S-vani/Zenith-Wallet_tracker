"""
Tables for the watchlist, price alerts, the in-app notification inbox (alerts, events and the daily briefing), the
iPhones registered for push notifications and each user's notification settings. Created by create_all at startup
(backend/db/database.py imports this module); every row belongs to one user and goes with the account
(authentication/cleanup.py delete_users).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, Uuid

from backend.db_models.assets import Base


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, like every other timestamp


class WatchItem(Base):
    """An asset the user follows without owning it (Search's star). api_id/type as in transactions."""
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "asset_type", "api_id", name="uq_watch_user_asset"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Uuid(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    api_id = Column(String, nullable=False)  # "AAPL", "SHOP.TO", "btc"
    asset_type = Column(String, nullable=False)  # "stock" | "crypto"
    coin_id = Column(String, nullable=True)  # the exact CoinGecko coin, like trades keep it
    name = Column(String, nullable=True)  # "NASDAQ · Apple Inc." as Search showed it, for the list
    created_at = Column(DateTime, nullable=False, default=_now)


class Alert(Base):
    """
    A price alert. kind: "above" / "below" (threshold = a price in `currency`, fires once, then switches itself off)
    or "move" (threshold = a % move since the previous close either way, fires at most once a day).
    """
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Uuid(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    api_id = Column(String, nullable=False)
    asset_type = Column(String, nullable=False)
    coin_id = Column(String, nullable=True)
    kind = Column(String, nullable=False)
    threshold = Column(Float, nullable=False)
    currency = Column(String, nullable=False)  # the price threshold's currency (the user's at the time)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    last_triggered_at = Column(DateTime, nullable=True)


class Notification(Base):
    """One entry in the in-app inbox (and the push sent for it): kind "alert", "event" or "briefing"."""
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Uuid(as_uuid=True), ForeignKey("user.id"), nullable=False)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    link = Column(String, nullable=True)  # an app screen to open, e.g. "/search?asset=AAPL&type=stock"
    dedupe_key = Column(String, nullable=True)  # e.g. "event:earnings:AAPL:2027-01-28", so an event is sent once
    created_at = Column(DateTime, nullable=False, default=_now)
    read_at = Column(DateTime, nullable=True)


class PushDevice(Base):
    """An iPhone's APNs device token, registered by the app when the user allows notifications."""
    __tablename__ = "push_devices"

    token = Column(String, primary_key=True)  # hex, from APNs; moves to whoever signs in on that phone last
    user_id = Column(Uuid(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=_now)


class NotificationSettings(Base):
    """What a user wants to hear about. A missing row means the defaults below."""
    __tablename__ = "notification_settings"

    user_id = Column(Uuid(as_uuid=True), ForeignKey("user.id"), primary_key=True)
    daily_briefing = Column(Boolean, nullable=False, default=True)  # 8:00 Toronto: overnight change, movers, events
    holding_events = Column(Boolean, nullable=False, default=True)  # earnings / ex-dividend / 200-day crossings
    push = Column(Boolean, nullable=False, default=True)  # also send them to the phone (in-app inbox always)
    briefing_sent_on = Column(String, nullable=True)  # Toronto date of the last briefing, "2026-11-24"
