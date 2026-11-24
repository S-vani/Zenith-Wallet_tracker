"""Watchlist, price alerts, the notification inbox, settings, push devices and the daily briefing."""
from datetime import datetime, timedelta, timezone

import pytest

import backend.services.alerts as alerts_service
from backend.services import profiles


@pytest.fixture
def pushes(monkeypatch):
    """Records pushes instead of calling Apple."""
    sent = []

    async def fake_push(token, title, body, link=None):
        sent.append({"token": token, "title": title, "body": body, "link": link})
        return "sent"

    monkeypatch.setattr(alerts_service, "send_push", fake_push)
    monkeypatch.setattr(profiles, "_cache", {})
    return sent


def inbox(client, owner):
    res = client.get("/notifications", headers=owner.headers)
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------------------------------- watchlist
def test_watchlist_add_list_remove(client, user):
    assert client.post("/watchlist", headers=user.headers,
                       json={"api_id": "aapl", "type": "stock", "name": "NASDAQ · Apple Inc."}).status_code == 201
    # adding it again changes nothing
    assert client.post("/watchlist", headers=user.headers, json={"api_id": "AAPL", "type": "stock"}).status_code == 201
    items = client.get("/watchlist", headers=user.headers).json()
    assert [(i["api_id"], i["type"], i["name"]) for i in items] == [("AAPL", "stock", "NASDAQ · Apple Inc.")]
    assert items[0]["price"] == pytest.approx(140.0)  # 100 USD at the test rate 1.4
    assert client.delete("/watchlist/stock/AAPL", headers=user.headers).status_code == 204
    assert client.get("/watchlist", headers=user.headers).json() == []


def test_watchlist_is_per_user_and_validated(client, make_user):
    a, b = make_user(), make_user()
    client.post("/watchlist", headers=a.headers, json={"api_id": "BTC", "type": "crypto"})
    assert client.get("/watchlist", headers=b.headers).json() == []
    assert client.get("/watchlist", headers=a.headers).json()[0]["api_id"] == "btc"
    assert client.post("/watchlist", headers=a.headers, json={"api_id": "A; DROP", "type": "stock"}).status_code == 422
    assert client.get("/watchlist").status_code == 401


# ---------------------------------------------------------------------------------------------------- alerts
def test_alert_crud_and_limits(client, user):
    res = client.post("/alerts", headers=user.headers,
                      json={"api_id": "AAPL", "type": "stock", "kind": "above", "threshold": 150})
    assert res.status_code == 201, res.text
    alert = res.json()
    assert (alert["kind"], alert["threshold"], alert["currency"], alert["active"]) == ("above", 150, "CAD", True)
    assert client.post("/alerts", headers=user.headers,
                       json={"api_id": "AAPL", "type": "stock", "kind": "move", "threshold": 80}).status_code == 422
    assert len(client.get("/alerts", headers=user.headers).json()) == 1
    assert client.delete(f"/alerts/{alert['id']}", headers=user.headers).status_code == 204
    assert client.get("/alerts", headers=user.headers).json() == []


def test_price_alert_fires_once_and_switches_off(client, user, run, market, pushes):
    client.post("/push/devices", headers=user.headers, json={"token": "ab" * 32})
    client.post("/alerts", headers=user.headers, json={"api_id": "AAPL", "type": "stock", "kind": "above",
                                                       "threshold": 125})  # AAPL is 130 CAD
    client.post("/alerts", headers=user.headers, json={"api_id": "AAPL", "type": "stock", "kind": "below",
                                                       "threshold": 100})  # not met
    assert run(alerts_service.check_price_alerts) == 1
    assert run(alerts_service.check_price_alerts) == 0  # off now
    box = inbox(client, user)
    assert box["unread"] == 1 and box["items"][0]["title"] == "AAPL is above CA$125.00"
    assert box["items"][0]["link"] == "/search?q=AAPL&type=stock"
    assert pushes == [{"token": "ab" * 32, "title": "AAPL is above CA$125.00", "body": pushes[0]["body"],
                       "link": "/search?q=AAPL&type=stock"}]
    states = {a["kind"]: a["active"] for a in client.get("/alerts", headers=user.headers).json()}
    assert states == {"above": False, "below": True}


def test_move_alert_fires_once_a_day(client, user, run, market, pushes):
    market.previous_closes["AAPL"] = 90.0  # +11% since a day ago
    client.post("/alerts", headers=user.headers, json={"api_id": "AAPL", "type": "stock", "kind": "move",
                                                       "threshold": 5})
    assert run(alerts_service.check_price_alerts) == 1
    assert run(alerts_service.check_price_alerts) == 0
    assert inbox(client, user)["items"][0]["title"] == "AAPL up 11.1% in a day"


def test_no_push_when_turned_off(client, user, run, pushes):
    client.post("/push/devices", headers=user.headers, json={"token": "cd" * 32})
    res = client.put("/notifications/settings", headers=user.headers,
                     json={"daily_briefing": True, "holding_events": True, "push": False})
    assert res.status_code == 200
    client.post("/alerts", headers=user.headers, json={"api_id": "AAPL", "type": "stock", "kind": "above",
                                                       "threshold": 1})
    run(alerts_service.check_price_alerts)
    assert pushes == [] and inbox(client, user)["unread"] == 1


def test_mark_read_and_settings_defaults(client, user, run, pushes):
    assert client.get("/notifications/settings", headers=user.headers).json() == \
        {"daily_briefing": True, "holding_events": True, "push": True}
    client.post("/alerts", headers=user.headers, json={"api_id": "AAPL", "type": "stock", "kind": "above",
                                                       "threshold": 1})
    run(alerts_service.check_price_alerts)
    assert client.post("/notifications/read", headers=user.headers).status_code == 204
    box = inbox(client, user)
    assert box["unread"] == 0 and box["items"][0]["read"] is True


# ---------------------------------------------------------------------------------------------------- devices
def test_device_moves_to_the_last_account_signed_in(client, make_user, run, pushes):
    a, b = make_user(), make_user()
    token = "ef" * 32
    client.post("/push/devices", headers=a.headers, json={"token": token})
    client.post("/push/devices", headers=b.headers, json={"token": token.upper()})
    for owner in (a, b):
        client.post("/alerts", headers=owner.headers, json={"api_id": "AAPL", "type": "stock", "kind": "above",
                                                            "threshold": 1})
    run(alerts_service.check_price_alerts)
    assert len(pushes) == 1  # only b's alert reaches the phone; a's is in a's inbox
    assert client.post("/push/devices", headers=a.headers, json={"token": "not-hex"}).status_code == 422


# ---------------------------------------------------------------------------------------------------- daily
def test_daily_briefing_once_per_day(client, make_user, buy, run, market, pushes):
    owner = make_user()
    buy(owner, "AAPL", 2, 100)
    market.previous_closes["AAPL"] = 80.0
    morning = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)  # 9:00 in Toronto
    run(alerts_service.run_daily, morning)
    run(alerts_service.run_daily, morning + timedelta(hours=2))  # same Toronto day: nothing new
    briefings = [i for i in inbox(client, owner)["items"] if i["kind"] == "briefing"]
    assert len(briefings) == 1
    assert briefings[0]["title"].startswith("Good morning: +")
    assert "Your portfolio is CA$" in briefings[0]["body"] and "Best: AAPL" in briefings[0]["body"]


def test_no_briefing_before_8_or_when_turned_off(client, make_user, buy, run, pushes):
    owner = make_user()
    buy(owner, "AAPL", 1, 100)
    assert run(alerts_service.run_daily, datetime(2026, 11, 24, 11, 0, tzinfo=timezone.utc)) == 0  # 6:00 Toronto
    client.put("/notifications/settings", headers=owner.headers,
               json={"daily_briefing": False, "holding_events": False, "push": True})
    run(alerts_service.run_daily, datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc))
    assert [i for i in inbox(client, owner)["items"] if i["kind"] == "briefing"] == []


def test_earnings_tomorrow_event_is_sent_once(client, make_user, buy, run, monkeypatch, pushes):
    owner = make_user()
    buy(owner, "AAPL", 1, 100)
    morning = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)

    async def fake_profile(symbol):
        return {"earnings_date": morning.date() + timedelta(days=1), "ex_dividend_date": None}

    monkeypatch.setattr(alerts_service, "stock_profile", fake_profile)
    client.put("/notifications/settings", headers=owner.headers,
               json={"daily_briefing": False, "holding_events": True, "push": True})
    run(alerts_service.run_daily, morning)
    run(alerts_service.run_daily, morning + timedelta(days=1))  # the next day: the same event isn't sent again
    events = [i for i in inbox(client, owner)["items"] if i["kind"] == "event"]
    assert [e["title"] for e in events] == ["AAPL earnings tomorrow"]


def test_200_day_crossing():
    class Series:
        closes = [100.0] * 201 + [130.0]

    async def fake_series(*args, **kwargs):
        return Series(), 1.0, "yahoo"

    import asyncio
    original = alerts_service._asset_series
    alerts_service._asset_series = fake_series
    try:
        assert asyncio.run(alerts_service.crossed_200_day("AAPL", "stock", None)) == "above"
        Series.closes = [99.0] * 200 + [101.0, 102.0]  # already above the day before: not a fresh crossing
        assert asyncio.run(alerts_service.crossed_200_day("AAPL", "stock", None)) is None
    finally:
        alerts_service._asset_series = original


# ---------------------------------------------------------------------------------------------------- the rest
def test_account_deletion_removes_alert_data(client, make_user, db, run, pushes):
    from backend.authentication.cleanup import delete_users
    from backend.db.database import async_session_maker
    from backend.db_models.alerts import Alert, PushDevice, WatchItem
    from sqlalchemy import func, select

    owner = make_user()
    client.post("/watchlist", headers=owner.headers, json={"api_id": "AAPL", "type": "stock"})
    client.post("/alerts", headers=owner.headers, json={"api_id": "AAPL", "type": "stock", "kind": "above",
                                                        "threshold": 1})
    client.post("/push/devices", headers=owner.headers, json={"token": "12" * 32})
    run(alerts_service.check_price_alerts)

    async def remove_and_count():
        import uuid
        async with async_session_maker() as session:
            await delete_users(session, [uuid.UUID(owner.id)])
            counts = []
            for table in (WatchItem, Alert, PushDevice):
                counts.append(await session.scalar(select(func.count()).select_from(table)
                                                   .where(table.user_id == uuid.UUID(owner.id))))
            return counts

    assert run(remove_and_count) == [0, 0, 0]


def test_holdings_carry_the_day_change(client, user, buy, market):
    buy(user, "AAPL", 1, 100)
    market.previous_closes["AAPL"] = 80.0
    row = client.get("/holdings", headers=user.headers).json()[0]
    assert row["day_change_pct"] == pytest.approx(25.0)
