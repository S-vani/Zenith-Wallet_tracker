"""
Ledger rules for transactions: exact quantities (sell all), backdated trades, oversell 409s, and prices kept in the
currency they were typed in.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text, update

import backend.routes.assets as routes_module
import backend.services.asset_services as services
from backend.db.database import ADDED_COLUMNS, _add_missing_columns, async_session_maker
from backend.db_models.assets import Transaction
from conftest import RATES


def tx_body(**overrides):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
            "api_id": "AAPL"}
    body.update(overrides)
    return body


def post(client, owner, **overrides):
    return client.post("/transactions", headers=owner.headers, json=tx_body(**overrides))


def listed(client, owner, tx_id):
    return next(t for t in client.get("/transactions", headers=owner.headers).json() if t["id"] == tx_id)


def set_rates(monkeypatch, **rates):
    async def fake_rates():
        return dict(RATES, **rates)

    monkeypatch.setattr(services, "get_all_conversion_rates", fake_rates)
    monkeypatch.setattr(routes_module, "get_all_conversion_rates", fake_rates)


async def _forget_entered_price(tx_id):
    async with async_session_maker() as session:
        await session.execute(update(Transaction).where(Transaction.id == tx_id)
                              .values(price_entered=None, currency_entered=None))
        await session.commit()


# ---------------------------------------------------------------------------------------------------------------------
# sell all precision
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("quantity", [35155977.36, 1234567.89, 0.1, 50000.07, 2500000.3, 999999999.9999, 1e9])
def test_selling_exactly_what_was_bought(client, user, quantity):
    # SQLite gives 1234567.89 back as 1234567.8899999999, which used to make this a 409
    symbol = f"x{uuid.uuid4().hex[:6]}"
    assert post(client, user, symbol=symbol, api_id=symbol, asset_type="crypto", price_of_one=1,
                quantity=quantity).status_code == 200
    res = post(client, user, symbol=symbol, api_id=symbol, asset_type="crypto", price_of_one=1, quantity=quantity,
               action="SELL")
    assert res.status_code == 200, res.text
    assert client.get("/holdings", headers=user.headers).json() == []


def test_sell_all_button_value_passes(client, user):
    post(client, user, symbol="pepe", api_id="pepe", asset_type="crypto", price_of_one=0.00001, quantity=35155977.36)
    post(client, user, symbol="pepe", api_id="pepe", asset_type="crypto", price_of_one=0.00001, quantity=37817151.952)

    [holding] = client.get("/holdings", headers=user.headers).json()
    assert repr(holding["quantity"]) == "72973129.312"  # exact sum, no float noise for the box to copy

    res = post(client, user, symbol="pepe", api_id="pepe", asset_type="crypto", price_of_one=0.00001,
               quantity=holding["quantity"], action="SELL")
    assert res.status_code == 200, res.text
    assert client.get("/holdings", headers=user.headers).json() == []


def test_sell_within_float_noise_counts_as_selling_everything(client, user):
    post(client, user, quantity=72973129.312)
    # what a float sum could hand the frontend: one float step (2e-8) above what is owned
    res = post(client, user, quantity=72973129.31200002, action="SELL")
    assert res.status_code == 200, res.text
    assert client.get("/holdings", headers=user.headers).json() == []


def test_tolerance_does_not_allow_real_overselling(client, user):
    post(client, user, quantity=1234567.89)
    assert post(client, user, quantity=1234567.8901, action="SELL").status_code == 409
    post(client, user, symbol="ETH", api_id="eth", asset_type="crypto", quantity=0.5)
    assert post(client, user, symbol="ETH", api_id="eth", asset_type="crypto", quantity=0.5000000002,
                action="SELL").status_code == 409


def test_as_quantity_removes_sqlite_float_noise():
    assert services.as_quantity(Decimal("1234567.8899999999")) == Decimal("1234567.89")
    assert services.as_quantity(0.1) == Decimal("0.1")
    assert services.as_quantity(None) == 0


# ---------------------------------------------------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------------------------------------------------
def test_trade_date_is_stored_as_naive_utc(client, user, db):
    res = post(client, user, created_at="2024-01-10T12:00:00-05:00")
    assert res.status_code == 200, res.text
    assert db.get_transaction(res.json()["id"]).created_at == datetime(2024, 1, 10, 17, 0)
    assert listed(client, user, res.json()["id"])["created_at"] == "2024-01-10T17:00:00+00:00"


def test_trade_without_a_date_is_now(client, user, db):
    res = post(client, user)
    stored = db.get_transaction(res.json()["id"]).created_at
    assert abs(stored.replace(tzinfo=None) - datetime.now(timezone.utc).replace(tzinfo=None)) < timedelta(minutes=1)


def test_future_dates_are_rejected(client, user):
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    res = post(client, user, created_at=tomorrow)
    assert res.status_code == 422
    assert client.get("/transactions", headers=user.headers).json() == []
    assert post(client, user, created_at="1900-01-01T00:00:00Z").status_code == 422


def test_a_slightly_fast_clock_is_treated_as_now(client, user, db):
    soon = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    res = post(client, user, created_at=soon)
    assert res.status_code == 200
    assert db.get_transaction(res.json()["id"]).created_at <= datetime.now(timezone.utc).replace(tzinfo=None)


def test_backdated_sell_before_its_buy_is_rejected(client, user):
    post(client, user, quantity=2, created_at="2024-03-01T12:00:00Z")
    res = post(client, user, action="SELL", quantity=1, created_at="2024-02-01T12:00:00Z")
    assert res.status_code == 409
    assert res.json()["detail"] == "Insufficient holdings"
    assert len(client.get("/transactions", headers=user.headers).json()) == 1  # nothing was saved


def test_backdated_sell_uses_the_average_cost_at_that_date(client, user):
    post(client, user, quantity=1, price_of_one=100, created_at="2024-01-01T12:00:00Z")
    post(client, user, quantity=1, price_of_one=200, created_at="2024-03-01T12:00:00Z")
    res = post(client, user, action="SELL", quantity=1, price_of_one=150, created_at="2024-02-01T12:00:00Z")
    assert res.status_code == 200, res.text
    assert float(res.json()["profit"]) == pytest.approx(50)  # only the 100 buy existed in February


def test_backdated_sell_that_breaks_a_later_sell_is_rejected(client, user):
    post(client, user, quantity=2, created_at="2024-01-01T12:00:00Z")
    post(client, user, action="SELL", quantity=2)
    assert post(client, user, action="SELL", quantity=1, created_at="2024-02-01T12:00:00Z").status_code == 409


def test_backdated_buy_recomputes_later_sell_profit(client, user):
    post(client, user, quantity=1, price_of_one=100, created_at="2024-01-01T12:00:00Z")
    sale = post(client, user, action="SELL", quantity=1, price_of_one=150).json()
    assert listed(client, user, sale["id"])["profit"] == pytest.approx(50)

    post(client, user, quantity=1, price_of_one=200, created_at="2024-02-01T12:00:00Z")  # average cost now 150
    assert listed(client, user, sale["id"])["profit"] == pytest.approx(0)


def test_editing_a_buy_to_after_its_sell_is_rejected(client, user, db):
    buy = post(client, user, quantity=1, created_at="2024-01-01T12:00:00Z").json()
    post(client, user, action="SELL", quantity=1, created_at="2024-02-01T12:00:00Z")

    res = client.put(f"/transactions/{buy['id']}", headers=user.headers, json={"created_at": "2024-03-01T12:00:00Z"})
    assert res.status_code == 409
    assert db.get_transaction(buy["id"]).created_at == datetime(2024, 1, 1, 12)

    ok = client.put(f"/transactions/{buy['id']}", headers=user.headers,
                    json={"created_at": "2023-06-01T09:30:00+02:00"})
    assert ok.status_code == 200
    assert db.get_transaction(buy["id"]).created_at == datetime(2023, 6, 1, 7, 30)


def test_editing_to_a_future_date_is_rejected(client, user):
    tx = post(client, user).json()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.put(f"/transactions/{tx['id']}", headers=user.headers,
                      json={"created_at": tomorrow}).status_code == 422


def test_deleting_the_buy_behind_a_sell_gives_a_clear_409(client, user):
    buy = post(client, user, quantity=1, created_at="2024-01-01T12:00:00Z").json()
    post(client, user, action="SELL", quantity=1)
    res = client.delete(f"/transactions/{buy['id']}", headers=user.headers)
    assert res.status_code == 409
    assert "selling more than you owned" in res.json()["detail"]


# ---------------------------------------------------------------------------------------------------------------------
# prices kept in the currency they were typed in
# ---------------------------------------------------------------------------------------------------------------------
def test_usd_cost_basis_does_not_drift_with_fx(client, make_user, monkeypatch, db):
    usd_user = make_user(currency="USD")
    tx = post(client, usd_user, quantity=10, price_of_one=100).json()  # AAPL is exactly 100 USD

    stored = db.get_transaction(tx["id"])
    assert float(stored.price_entered) == 100 and stored.currency_entered == "USD"
    assert float(stored.price_of_one) == pytest.approx(100 / RATES["usd"])  # CAD copy still kept

    # CAD strengthens: 1 USD = 1.25 CAD, 1 CAD = 0.8 USD
    set_rates(monkeypatch, usd_to_cad=1.25, usd=0.8, eur=0.6)
    assert listed(client, usd_user, tx["id"])["price_of_one"] == pytest.approx(100)
    [holding] = client.get("/holdings", headers=usd_user.headers).json()
    assert holding["price_paid"] == pytest.approx(1000)
    assert holding["current_price"] - holding["price_paid"] == pytest.approx(0)


def test_usd_realized_profit_matches_the_typed_prices(client, make_user, monkeypatch, db):
    usd_user = make_user(currency="USD")
    post(client, usd_user, quantity=2, price_of_one=100)

    set_rates(monkeypatch, usd_to_cad=1.25, usd=0.8, eur=0.6)
    sale = post(client, usd_user, action="SELL", quantity=1, price_of_one=110).json()

    assert listed(client, usd_user, sale["id"])["profit"] == pytest.approx(10)  # (110 - 100) x 1, in USD
    assert float(db.get_transaction(sale["id"]).profit) == pytest.approx(10 / 0.8)  # stored in CAD at the sale's rate

    set_rates(monkeypatch, usd_to_cad=1.6, usd=0.625, eur=0.5)  # and it stays +$10 when FX moves again
    assert listed(client, usd_user, sale["id"])["profit"] == pytest.approx(10)


def test_cad_profit_is_unchanged_by_the_new_columns(client, user):
    post(client, user, quantity=2, price_of_one=100)
    post(client, user, quantity=2, price_of_one=200)
    sale = post(client, user, action="SELL", quantity=1, price_of_one=180).json()
    assert float(sale["profit"]) == pytest.approx(30)


def test_other_currency_trades_are_converted_from_cad(client, make_user, db):
    usd_user = make_user(currency="USD")
    tx = post(client, usd_user, price_of_one=70).json()  # 100 CAD
    db.set_user(usd_user.email, currency="EUR")
    assert listed(client, usd_user, tx["id"])["price_of_one"] == pytest.approx(100 * RATES["eur"])


def test_old_rows_without_typed_price_keep_converting_from_cad(client, make_user, monkeypatch, run):
    usd_user = make_user(currency="USD")
    buy = post(client, usd_user, quantity=2, price_of_one=70).json()  # 100 CAD
    run(_forget_entered_price, buy["id"])

    set_rates(monkeypatch, usd_to_cad=1.25, usd=0.8, eur=0.6)
    assert listed(client, usd_user, buy["id"])["price_of_one"] == pytest.approx(80)  # 100 CAD at today's rate
    [holding] = client.get("/holdings", headers=usd_user.headers).json()
    assert holding["price_paid"] == pytest.approx(160)

    # a USD sale of an old CAD-only buy: same profit as the plain CAD maths
    sale = post(client, usd_user, action="SELL", quantity=1, price_of_one=96).json()  # 120 CAD
    assert float(sale["profit"]) == pytest.approx(20)


def test_editing_the_price_keeps_it_as_typed(client, make_user, monkeypatch, db):
    usd_user = make_user(currency="USD")
    tx = post(client, usd_user, price_of_one=70).json()
    client.put(f"/transactions/{tx['id']}", headers=usd_user.headers, json={"price_of_one": 90})
    stored = db.get_transaction(tx["id"])
    assert float(stored.price_entered) == 90 and stored.currency_entered == "USD"

    client.put(f"/transactions/{tx['id']}", headers=usd_user.headers, json={"quantity": 3})  # price untouched
    set_rates(monkeypatch, usd_to_cad=1.25, usd=0.8, eur=0.6)
    assert listed(client, usd_user, tx["id"])["price_of_one"] == pytest.approx(90)


def test_turn_list_to_dict_uses_the_typed_price_for_the_same_currency():
    tx = SimpleNamespace(id="t", user_id=uuid.UUID(int=1), action="SELL", profit=Decimal("12.5"), asset_type="stock",
                         symbol="AAPL", api_id="AAPL", price_of_one=Decimal("137.5"), price_entered=Decimal("110"),
                         currency_entered="USD", quantity=Decimal("1"), created_at=datetime(2024, 1, 1))
    [usd] = services.turn_list_to_dict([tx], conversion=0.7, currency="USD")
    assert usd["price_of_one"] == pytest.approx(110)
    assert usd["profit"] == pytest.approx(10)  # 12.5 CAD at the sale's own rate (0.8)

    [eur] = services.turn_list_to_dict([tx], conversion=0.6, currency="EUR")
    assert eur["price_of_one"] == pytest.approx(137.5 * 0.6)
    assert eur["profit"] == pytest.approx(12.5 * 0.6)


# ---------------------------------------------------------------------------------------------------------------------
# the production database gets the new columns
# ---------------------------------------------------------------------------------------------------------------------
def test_new_columns_are_added_to_an_existing_table(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE transactions (id VARCHAR PRIMARY KEY, price_of_one NUMERIC(20, 10))'))
        conn.execute(text("INSERT INTO transactions VALUES ('old', 100)"))
        _add_missing_columns(conn)
        _add_missing_columns(conn)  # running again on every start is harmless

        columns = {c["name"] for c in inspect(conn).get_columns("transactions")}
        assert {name for name, *_ in ADDED_COLUMNS["transactions"]} <= columns
        row = conn.execute(text("SELECT price_entered, currency_entered FROM transactions")).one()
        assert tuple(row) == (None, None)  # old rows keep the CAD-only behaviour
    engine.dispose()


def test_usd_dashboard_realized_profit_does_not_drift_with_fx(client, make_user, monkeypatch, market):
    # the dashboard's realized total (and cash flow) add up trade by trade, so typed USD amounts stay put
    usd_user = make_user(currency="USD")
    post(client, usd_user, quantity=2, price_of_one=100)
    post(client, usd_user, action="SELL", quantity=2, price_of_one=110)  # +$20 realized, all sold

    def all_time_return():
        return client.get("/dashboard", params={"current_timeperiod": "all"}, headers=usd_user.headers).json()

    before = all_time_return()
    set_rates(monkeypatch, usd_to_cad=1.6, usd=0.625, eur=0.5)  # CAD weakens a lot
    after = all_time_return()
    assert before["curr_timeperiod"] == pytest.approx(20)
    assert after["curr_timeperiod"] == pytest.approx(20)
