"""The /transactions routes: creating, validating, filtering, editing and deleting."""
from datetime import datetime

import pytest

from conftest import RATES


def tx_body(**overrides):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
            "api_id": "AAPL"}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------------------------------------------------
# creating
# ---------------------------------------------------------------------------------------------------------------------
def test_create_buy(client, user, db):
    res = client.post("/transactions", headers=user.headers, json=tx_body(quantity=2.5, price_of_one=123.45))
    assert res.status_code == 200, res.text
    tx = res.json()
    assert tx["action"] == "BUY"
    assert tx["symbol"] == "AAPL"
    assert tx["user_id"].replace("-", "") == user.id.replace("-", "")
    assert float(tx["profit"]) == 0

    stored = db.get_transaction(tx["id"])
    assert float(stored.price_of_one) == pytest.approx(123.45)
    assert float(stored.quantity) == pytest.approx(2.5)


@pytest.mark.parametrize("overrides", [
    {"quantity": 1e30},
    {"quantity": 1e9 + 1},
    {"quantity": 0},
    {"quantity": -1},
    {"price_of_one": 0},
    {"price_of_one": -5},
    {"price_of_one": 1e10},
    {"asset_type": "bond"},
    {"action": "HOLD"},
    {"action": "buy"},
    {"symbol": None},
    {"quantity": "lots"},
])
def test_create_rejects_invalid_input(client, user, overrides):
    res = client.post("/transactions", headers=user.headers, json=tx_body(**overrides))
    assert res.status_code == 422


def test_create_accepts_the_limits(client, user):
    res = client.post("/transactions", headers=user.headers, json=tx_body(quantity=1e9, price_of_one=1e9))
    assert res.status_code == 200, res.text


def test_price_entered_in_usd_is_stored_in_cad(client, make_user, db):
    usd_user = make_user(currency="USD")
    res = client.post("/transactions", headers=usd_user.headers, json=tx_body(price_of_one=70))
    assert res.status_code == 200

    stored = db.get_transaction(res.json()["id"])
    assert float(stored.price_of_one) == pytest.approx(70 / RATES["usd"])  # 100 CAD

    # and it is shown back in USD
    [listed] = client.get("/transactions", headers=usd_user.headers).json()
    assert listed["price_of_one"] == pytest.approx(70)


def test_price_entered_in_eur_round_trips(client, make_user):
    eur_user = make_user(currency="EUR")
    client.post("/transactions", headers=eur_user.headers, json=tx_body(price_of_one=60))
    [listed] = client.get("/transactions", headers=eur_user.headers).json()
    assert listed["price_of_one"] == pytest.approx(60)


def test_cad_stored_prices_are_converted_for_the_users_currency(client, user):
    client.post("/transactions", headers=user.headers, json=tx_body(price_of_one=100))

    client.put("/user/information", headers=user.headers, json={"currency": "USD"})
    [listed] = client.get("/transactions", headers=user.headers).json()
    assert listed["price_of_one"] == pytest.approx(100 * RATES["usd"])

    client.put("/user/information", headers=user.headers, json={"currency": "EUR"})
    [listed] = client.get("/transactions", headers=user.headers).json()
    assert listed["price_of_one"] == pytest.approx(100 * RATES["eur"])


# ---------------------------------------------------------------------------------------------------------------------
# selling
# ---------------------------------------------------------------------------------------------------------------------
def test_selling_exactly_the_remaining_fractional_quantity(user, buy, sell):
    # 0.3 - 0.1 is 0.19999999999999998 in floats, selling 0.2 must still be allowed
    buy(user, "ETH", 0.3, 2000, asset_type="crypto", api_id="eth")
    sell(user, "ETH", 0.1, 2000, asset_type="crypto", api_id="eth")
    sell(user, "ETH", 0.2, 2000, asset_type="crypto", api_id="eth")


def test_selling_more_than_owned_is_rejected(client, user, buy, sell):
    buy(user, "AAPL", 1, 100)
    res = client.post("/transactions", headers=user.headers, json=tx_body(action="SELL", quantity=1.0000001))
    assert res.status_code == 409
    assert res.json()["detail"] == "Insufficient holdings"


def test_selling_something_never_bought_is_rejected(client, user):
    res = client.post("/transactions", headers=user.headers, json=tx_body(action="SELL", symbol="TSLA"))
    assert res.status_code == 409


def test_cannot_sell_again_after_selling_everything(client, user, buy, sell):
    buy(user, "AAPL", 2, 100)
    sell(user, "AAPL", 2, 100)
    res = client.post("/transactions", headers=user.headers, json=tx_body(action="SELL", quantity=0.0001))
    assert res.status_code == 409


def test_users_cannot_sell_each_others_holdings(client, make_user, buy):
    alice, bob = make_user(), make_user()
    buy(alice, "AAPL", 5, 100)
    res = client.post("/transactions", headers=bob.headers, json=tx_body(action="SELL", quantity=1))
    assert res.status_code == 409


def test_sell_records_profit_against_average_cost(user, buy, sell):
    buy(user, "AAPL", 2, 100)
    buy(user, "AAPL", 2, 200)  # average cost 150
    tx = sell(user, "AAPL", 1, 180)
    assert float(tx["profit"]) == pytest.approx(30)

    loss = sell(user, "AAPL", 1, 120)
    assert float(loss["profit"]) == pytest.approx(-30)


def test_sell_profit_for_usd_user_is_stored_in_cad_and_shown_in_usd(client, make_user, buy, sell):
    usd_user = make_user(currency="USD")
    buy(usd_user, "AAPL", 1, 70)  # 100 CAD
    tx = sell(usd_user, "AAPL", 1, 84)  # 120 CAD
    assert float(tx["profit"]) == pytest.approx(20)  # stored in CAD

    sells = client.get("/transactions?action=SELL", headers=usd_user.headers).json()
    assert sells[0]["profit"] == pytest.approx(20 * RATES["usd"])


# ---------------------------------------------------------------------------------------------------------------------
# listing and filtering
# ---------------------------------------------------------------------------------------------------------------------
def test_list_only_returns_your_own_transactions(client, make_user, buy):
    alice, bob = make_user(), make_user()
    buy(alice, "AAPL", 1, 100)
    assert client.get("/transactions", headers=bob.headers).json() == []
    assert len(client.get("/transactions", headers=alice.headers).json()) == 1


def test_list_shape(client, user, buy):
    buy(user, "btc", 0.5, 40000, asset_type="crypto")
    [row] = client.get("/transactions", headers=user.headers).json()
    assert set(row) == {"id", "user_id", "action", "profit", "asset_type", "symbol", "api_ids", "coin_id",
                        "price_of_one", "quantity", "account_type", "created_at"}
    assert datetime.fromisoformat(row["created_at"]).tzinfo is not None


@pytest.fixture
def mixed_symbols(user, buy):
    for symbol in ["AAPL", "AMD", "A_X", "BTC", "MSFT"]:
        buy(user, symbol, 1, 10)
    return user


def symbols_for(client, owner, query):
    return sorted(t["symbol"] for t in client.get(f"/transactions?{query}", headers=owner.headers).json())


def test_symbol_filter_is_a_case_insensitive_prefix_match(client, mixed_symbols):
    assert symbols_for(client, mixed_symbols, "symbol=a") == ["AAPL", "AMD", "A_X"]
    assert symbols_for(client, mixed_symbols, "symbol=AAP") == ["AAPL"]
    assert symbols_for(client, mixed_symbols, "symbol=PL") == []


@pytest.mark.parametrize("wildcard", ["_", "%", "%25", "__", "\\"])
def test_symbol_filter_does_not_treat_wildcards_specially(client, mixed_symbols, wildcard):
    assert symbols_for(client, mixed_symbols, f"symbol={wildcard}") == []


def test_symbol_filter_matches_a_literal_underscore(client, mixed_symbols):
    assert symbols_for(client, mixed_symbols, "symbol=A_") == ["A_X"]


def test_filter_by_action(client, user, buy, sell):
    buy(user, "AAPL", 2, 100)
    buy(user, "MSFT", 1, 100)
    sell(user, "AAPL", 1, 100)

    sells = client.get("/transactions?action=SELL", headers=user.headers).json()
    buys = client.get("/transactions?action=BUY", headers=user.headers).json()
    assert [t["symbol"] for t in sells] == ["AAPL"]
    assert sorted(t["symbol"] for t in buys) == ["AAPL", "MSFT"]
    assert client.get("/transactions?action=HOLD", headers=user.headers).status_code == 422


def test_filter_by_date_range_and_newest_first(client, user, buy, db):
    dates = {"JAN": datetime(2024, 1, 10, 12), "FEB": datetime(2024, 2, 10, 12), "MAR": datetime(2024, 3, 10, 12)}
    for symbol, created_at in dates.items():
        tx = buy(user, symbol, 1, 10)
        db.set_created_at(tx["id"], created_at)

    def query(params):
        return [t["symbol"] for t in client.get(f"/transactions?{params}", headers=user.headers).json()]

    assert query("") == ["MAR", "FEB", "JAN"]
    assert query("start_date=2024-02-01T00:00:00Z&end_date=2024-02-28T23:59:59Z") == ["FEB"]
    assert query("start_date=2024-02-01T00:00:00Z") == ["MAR", "FEB"]
    assert query("end_date=2024-02-10T12:00:00Z") == ["FEB", "JAN"]  # end is inclusive
    assert query("start_date=2024-04-01T00:00:00Z") == []
    assert client.get("/transactions?start_date=yesterday", headers=user.headers).status_code == 422


def test_filters_combine(client, user, buy, sell, db):
    buy(user, "AAPL", 2, 100)
    old = buy(user, "AMD", 1, 100)
    db.set_created_at(old["id"], datetime(2020, 1, 1))
    sell(user, "AAPL", 1, 100)

    rows = client.get("/transactions?symbol=a&action=BUY&start_date=2023-01-01T00:00:00Z",
                      headers=user.headers).json()
    assert [(t["symbol"], t["action"]) for t in rows] == [("AAPL", "BUY")]


# ---------------------------------------------------------------------------------------------------------------------
# single transaction routes
# ---------------------------------------------------------------------------------------------------------------------
def test_get_update_and_delete_by_id(client, user, buy, db):
    tx = buy(user, "AAPL", 1, 100)

    got = client.get(f"/transactions/{tx['id']}", headers=user.headers)
    assert got.status_code == 200
    assert got.json()["id"] == tx["id"]

    updated = client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"quantity": 3, "symbol": "MSFT"})
    assert updated.status_code == 200
    assert float(updated.json()["quantity"]) == 3
    assert updated.json()["symbol"] == "MSFT"
    assert float(updated.json()["price_of_one"]) == 100  # untouched fields stay

    deleted = client.delete(f"/transactions/{tx['id']}", headers=user.headers)
    assert deleted.status_code == 200
    assert db.get_transaction(tx["id"]) is None
    assert client.get(f"/transactions/{tx['id']}", headers=user.headers).status_code == 404


def test_missing_transaction_is_404(client, user):
    for method in ("GET", "DELETE"):
        assert client.request(method, "/transactions/does-not-exist", headers=user.headers).status_code == 404
    assert client.put("/transactions/does-not-exist", headers=user.headers, json={"quantity": 1}).status_code == 404


def test_other_users_transactions_are_invisible(client, make_user, buy, db):
    alice, bob = make_user(), make_user()
    tx = buy(alice, "AAPL", 1, 100)

    assert client.get(f"/transactions/{tx['id']}", headers=bob.headers).status_code == 404
    assert client.put(f"/transactions/{tx['id']}", headers=bob.headers, json={"quantity": 9}).status_code == 404
    assert client.delete(f"/transactions/{tx['id']}", headers=bob.headers).status_code == 404
    assert float(db.get_transaction(tx["id"]).quantity) == 1


@pytest.mark.parametrize("update", [{"quantity": 1e30}, {"quantity": 0}, {"price_of_one": -1}, {"action": "HOLD"}])
def test_update_validates_numbers_and_action(client, user, buy, update):
    tx = buy(user, "AAPL", 1, 100)
    assert client.put(f"/transactions/{tx['id']}", headers=user.headers, json=update).status_code == 422


def test_update_rejects_unknown_asset_type(client, user, buy):
    tx = buy(user, "AAPL", 1, 100)
    assert client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"asset_type": "bond"}).status_code == 422


def test_update_converts_price_from_users_currency(client, make_user, buy, db):
    usd_user = make_user(currency="USD")
    tx = buy(usd_user, "AAPL", 1, 70)
    client.put(f"/transactions/{tx['id']}", headers=usd_user.headers, json={"price_of_one": 70})
    assert float(db.get_transaction(tx["id"]).price_of_one) == pytest.approx(100)
