"""
/portfolio/history's `invested`: the cost basis of the holdings at each point (what was paid for what was still
held), drawn on the dashboard next to the value line so deposits aren't mistaken for gains.
"""
from datetime import datetime, timedelta, timezone

import pytest

import backend.routes.assets as routes_module
import backend.services.asset_services as services
from conftest import RATES

AAPL_CAD = 100 * RATES["usd_to_cad"]


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).replace(tzinfo=None)


def history(client, owner, days=7):
    res = client.get(f"/portfolio/history?range={days}", headers=owner.headers)
    assert res.status_code == 200, res.text
    return res.json()


def points_between(data, start, end):
    points = [p for p in data if start < datetime.fromisoformat(p["time"]).replace(tzinfo=None) < end]
    assert points, "no chart points in that window"
    return points


@pytest.mark.parametrize("days", [1, 7, 30, 365, 1000])
def test_every_range_has_an_invested_value(client, user, buy, days):
    buy(user, "AAPL", 2, 100)
    data = history(client, user, days)
    assert all("invested" in p for p in data)
    assert data[-1]["invested"] == pytest.approx(200)


@pytest.mark.parametrize("days", [1, 7, 30, 365, 1000])
def test_empty_portfolio_invested_is_zero(client, user, days):
    assert all(p["invested"] == 0 and p["value"] == 0 for p in history(client, user, days))


def test_invested_follows_buys_and_sells_at_average_cost(client, user, buy, sell, db):
    first = buy(user, "AAPL", 2, 100)
    db.set_created_at(first["id"], ago(days=5))
    second = buy(user, "AAPL", 2, 200)  # average cost is now 150
    db.set_created_at(second["id"], ago(days=3))
    partial = sell(user, "AAPL", 1, 400)  # a sell keeps the average: 3 left at 150
    db.set_created_at(partial["id"], ago(days=1))

    data = history(client, user)
    assert data[0]["invested"] == 0  # before the first buy
    assert all(p["invested"] == pytest.approx(200) for p in points_between(data, ago(days=5, hours=-1),
                                                                          ago(days=3, hours=1)))
    assert all(p["invested"] == pytest.approx(600) for p in points_between(data, ago(days=3, hours=-1),
                                                                          ago(days=1, hours=1)))
    assert all(p["invested"] == pytest.approx(450) for p in points_between(data, ago(days=1, hours=-1), ago()))

    # the last point is the holdings' "price paid", and the value is unchanged by the new field
    [holding] = client.get("/holdings", headers=user.headers).json()
    assert data[-1]["invested"] == pytest.approx(holding["price_paid"]) == pytest.approx(450)
    assert data[-1]["value"] == pytest.approx(3 * AAPL_CAD)


def test_selling_everything_brings_invested_to_zero(client, user, buy, sell, db):
    b = buy(user, "AAPL", 2, 100)
    db.set_created_at(b["id"], ago(days=3))
    s = sell(user, "AAPL", 2, 120)
    db.set_created_at(s["id"], ago(days=2))
    data = history(client, user)
    assert all(p["invested"] == 0 for p in points_between(data, ago(days=2, hours=-1), ago()))
    assert data[-1]["invested"] == 0


def test_invested_uses_prices_as_typed_so_it_doesnt_drift(client, make_user, buy, monkeypatch):
    usd_user = make_user(currency="USD")
    buy(usd_user, "AAPL", 2, 100)  # typed as 100 USD each

    async def moved_rates():  # USD/CAD moved a lot since
        return {"usd_to_cad": 1.25, "usd": 0.8, "eur": 0.6}

    monkeypatch.setattr(services, "get_all_conversion_rates", moved_rates)
    monkeypatch.setattr(routes_module, "get_all_conversion_rates", moved_rates)
    assert history(client, usd_user)[-1]["invested"] == pytest.approx(200)


def test_holdings_without_a_price_are_left_out_of_both_lines(client, user, buy):
    buy(user, "GONE", 2, 50)  # no source has a price for it
    buy(user, "AAPL", 1, 100)
    last = history(client, user)[-1]
    assert last["value"] == pytest.approx(AAPL_CAD)
    assert last["invested"] == pytest.approx(100)  # not 200: GONE isn't in the value either
