"""At most MAX_SYMBOLS_PER_USER different assets per account, so one holdings request can't fan out to hundreds of
Yahoo calls."""
import pytest

import backend.routes.assets as routes_module


@pytest.fixture
def small_limit(monkeypatch):
    monkeypatch.setattr(routes_module, "MAX_SYMBOLS_PER_USER", 3)


def test_the_limit_is_200_and_the_message_says_so():
    assert routes_module.MAX_SYMBOLS_PER_USER == 200
    assert "200 different assets" in routes_module.TOO_MANY_SYMBOLS


def test_a_new_asset_past_the_limit_is_refused(client, user, buy, small_limit):
    for symbol in ("AAPL", "MSFT", "SHOP.TO"):
        buy(user, symbol, 1, 10)
    res = client.post("/transactions", headers=user.headers, json={
        "symbol": "btc", "action": "BUY", "asset_type": "crypto", "price_of_one": 1, "quantity": 1, "api_id": "btc"})
    assert res.status_code == 422
    assert res.json()["detail"] == routes_module.TOO_MANY_SYMBOLS


def test_assets_already_traded_stay_allowed(client, user, buy, sell, small_limit):
    for symbol in ("AAPL", "MSFT", "SHOP.TO"):
        buy(user, symbol, 2, 10)
    buy(user, "AAPL", 1, 12)
    sell(user, "MSFT", 2, 15)  # sold out, but still in the history
    buy(user, "MSFT", 1, 11)


def test_the_limit_is_per_user(client, make_user, buy, small_limit):
    alice, bob = make_user(), make_user()
    for symbol in ("AAPL", "MSFT", "SHOP.TO"):
        buy(alice, symbol, 1, 10)
    buy(bob, "btc", 1, 10, asset_type="crypto")


def test_deleting_an_assets_trades_frees_a_slot(client, user, buy, small_limit):
    trades = [buy(user, symbol, 1, 10) for symbol in ("AAPL", "MSFT", "SHOP.TO")]
    buy(user, "btc", 1, 10, asset_type="crypto", expect=422)
    client.delete(f"/transactions/{trades[0]['id']}", headers=user.headers)
    buy(user, "btc", 1, 10, asset_type="crypto")


def test_editing_a_trade_onto_a_new_asset_counts_too(client, user, buy, small_limit):
    for symbol in ("AAPL", "MSFT"):
        buy(user, symbol, 1, 10)
    msft_again = buy(user, "MSFT", 1, 10)
    shop = buy(user, "SHOP.TO", 1, 10)

    # MSFT keeps another trade, so moving this one to a 4th asset would be one too many
    res = client.put(f"/transactions/{msft_again['id']}", headers=user.headers, json={"api_id": "NVDA",
                                                                                       "symbol": "NVDA"})
    assert res.status_code == 422

    # SHOP.TO's only trade becoming NVDA leaves 3 assets: allowed
    res = client.put(f"/transactions/{shop['id']}", headers=user.headers, json={"api_id": "NVDA", "symbol": "NVDA"})
    assert res.status_code == 200, res.text
