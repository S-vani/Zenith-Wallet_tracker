"""
Regressions for the issues found in the final QA pass (mostly API-only edge cases).
"""
import pytest

from tests.conftest import register, unique_email


def post_raw(client, user, body: str):
    # raw JSON so NaN / Infinity literals can be sent exactly as a client would
    return client.post("/transactions", headers={**user.headers, "Content-Type": "application/json"}, content=body)


# --------------------------------------------------------------------------- input validation
@pytest.mark.parametrize("field,value", [("symbol", ""), ("symbol", "   "), ("api_id", ""), ("api_id", "  "),
                                         ("symbol", "X" * 33), ("api_id", "X" * 65)])
def test_blank_or_huge_symbols_are_rejected(client, user, field, value):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 5, "quantity": 1,
            "api_id": "AAPL", field: value}
    assert client.post("/transactions", headers=user.headers, json=body).status_code == 422


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_a_422_not_a_500(client, user, literal):
    body = ('{"symbol":"AAPL","action":"BUY","asset_type":"stock","price_of_one":%s,"quantity":1,"api_id":"AAPL"}'
            % literal)
    res = post_raw(client, user, body)
    assert res.status_code == 422
    assert res.json()["detail"][0]["loc"][-1] == "price_of_one"


def test_nan_on_update_is_a_422(client, user, buy):
    tx = buy(user, "AAPL", 1, 100)
    res = client.put(f"/transactions/{tx['id']}", headers={**user.headers, "Content-Type": "application/json"},
                     content='{"quantity": NaN}')
    assert res.status_code == 422


def test_amounts_too_small_to_store_are_rejected(client, user):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 1e-12, "quantity": 1e-12,
            "api_id": "AAPL"}
    assert client.post("/transactions", headers=user.headers, json=body).status_code == 422


@pytest.mark.parametrize("days", [0, -1, -365, 1_000_000_000, 99999999999999999999])
def test_portfolio_history_range_is_validated(client, user, days):
    assert client.get("/portfolio/history", params={"range": days}, headers=user.headers).status_code == 422


def test_price_history_rejects_unknown_type_and_blank_symbol(client, user):
    assert client.get("/prices/history", params={"symbol": "AAPL", "type": "bond", "range": "1D"},
                      headers=user.headers).status_code == 422
    assert client.get("/prices/history", params={"symbol": "", "type": "stock", "range": "1D"},
                      headers=user.headers).status_code == 422


# --------------------------------------------------------------------------- bad tickers don't break pages
def test_a_ticker_with_no_price_data_does_not_break_the_portfolio(client, user, buy, monkeypatch):
    import backend.services.asset_services as services

    buy(user, "ZZZZ", 1, 5)

    real_ticker = services.yf.Ticker

    def exploding_ticker(symbol):
        if symbol.upper().startswith("ZZZZ"):
            raise ValueError("no data for this ticker")
        return real_ticker(symbol)

    monkeypatch.setattr(services.yf, "Ticker", exploding_ticker)

    assert client.get("/holdings", headers=user.headers).status_code == 200
    assert client.get("/dashboard", params={"current_timeperiod": "week"}, headers=user.headers).status_code == 200
    assert client.get("/portfolio/history", params={"range": 7}, headers=user.headers).status_code == 200
    res = client.get("/prices/history", params={"symbol": "ZZZZ", "type": "stock", "range": "1D"}, headers=user.headers)
    assert res.status_code == 200
    assert res.json()["data"] == []


# --------------------------------------------------------------------------- edits and deletes keep history valid
def test_editing_a_sell_above_holdings_is_rejected(client, user, buy, sell):
    buy(user, "AAPL", 2, 100)
    s = sell(user, "AAPL", 1, 120)
    res = client.put(f"/transactions/{s['id']}", headers=user.headers, json={"quantity": 999})
    assert res.status_code == 409
    assert client.get(f"/transactions/{s['id']}", headers=user.headers).json()["quantity"] == pytest.approx(1)


def test_editing_a_sell_price_recomputes_its_profit(client, user, buy, sell):
    buy(user, "AAPL", 2, 100)
    s = sell(user, "AAPL", 1, 120)
    client.put(f"/transactions/{s['id']}", headers=user.headers, json={"price_of_one": 150})
    row = next(t for t in client.get("/transactions", headers=user.headers).json() if t["id"] == s["id"])
    assert row["profit"] == pytest.approx(50)


def test_turning_a_sell_into_a_buy_recomputes_later_sells(client, user, buy, sell, db):
    buy(user, "AAPL", 1, 100)
    first_sell = sell(user, "AAPL", 1, 100)
    res = client.put(f"/transactions/{first_sell['id']}", headers=user.headers, json={"action": "BUY"})
    assert res.status_code == 200
    assert client.get("/holdings", headers=user.headers).json()[0]["quantity"] == pytest.approx(2)


def test_deleting_the_buy_behind_a_sell_is_rejected(client, user, buy, sell):
    b = buy(user, "AAPL", 1, 100)
    sell(user, "AAPL", 1, 120)
    res = client.delete(f"/transactions/{b['id']}", headers=user.headers)
    assert res.status_code == 409
    assert client.get(f"/transactions/{b['id']}", headers=user.headers).status_code == 200


def test_delete_returns_a_plain_confirmation(client, user, buy):
    b = buy(user, "AAPL", 1, 100)
    res = client.delete(f"/transactions/{b['id']}", headers=user.headers)
    assert res.status_code == 200
    assert res.json() == {"id": b["id"], "deleted": True}


# --------------------------------------------------------------------------- dates with offsets
def test_date_filters_respect_timezone_offsets(client, user, buy, db):
    from tests.conftest import naive_utc

    tx = buy(user, "AAPL", 1, 100)
    db.set_created_at(tx["id"], naive_utc(2026, 10, 12, 15, 6))

    # 20:00 at +05:00 is 15:00 UTC, so the 15:06 UTC transaction is after it
    after = client.get("/transactions", params={"start_date": "2026-10-12T20:00:00+05:00"}, headers=user.headers)
    assert [t["id"] for t in after.json()] == [tx["id"]]

    # 10:00 at -05:00 is 15:00 UTC, so nothing at 15:06 is before it
    before = client.get("/transactions", params={"end_date": "2026-10-12T10:00:00-05:00"}, headers=user.headers)
    assert before.json() == []


# --------------------------------------------------------------------------- removed routes / passwords
def test_users_me_route_is_not_exposed(client, user):
    # email/password changes must go through /user/email (re-verification) instead
    assert client.patch("/users/me", headers=user.headers, json={"email": unique_email()}).status_code in (404, 405)


def test_forgot_password_never_reveals_whether_an_account_exists(client, user):
    # the reset flow is exposed on purpose (see test_password_reset.py), but answers the same for any email
    assert client.post("/auth/forgot-password", json={"email": unique_email()}).status_code == 202
    assert client.post("/auth/forgot-password", json={"email": user.email}).status_code == 202


@pytest.mark.parametrize("password", [" " * 8, "x" * 129])
def test_weak_or_huge_passwords_are_rejected(client, password):
    res = register(client, password=password)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "REGISTER_INVALID_PASSWORD"


def test_password_equal_to_email_is_rejected(client):
    email = unique_email()
    res = register(client, email=email, password=email)
    assert res.status_code == 400
