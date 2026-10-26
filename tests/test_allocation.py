"""
GET /portfolio/allocation: today's portfolio value split by asset type, account, holding and listing currency.
Fake prices (conftest): AAPL 100 USD = 140 CAD, MSFT 200 USD = 280 CAD, SHOP.TO 50 CAD, BTC 50,000 CAD.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

import backend.services.asset_services as services
from backend.services.allocation import build_allocation, listing_currency, replay_accounts


def trade(client, owner, symbol, quantity, price=100, action="BUY", account=None, asset_type="stock"):
    res = client.post("/transactions", headers=owner.headers, json={
        "symbol": symbol, "action": action, "asset_type": asset_type, "price_of_one": price,
        "quantity": quantity, "api_id": symbol, "account_type": account,
    })
    assert res.status_code == 200, res.text
    return res.json()


def allocation(client, owner):
    res = client.get("/portfolio/allocation", headers=owner.headers)
    assert res.status_code == 200, res.text
    return res.json()


def as_map(rows):
    return {row["key"]: row["value"] for row in rows}


def assert_weights(body):
    for group in ("by_asset_type", "by_account", "by_holding", "by_currency"):
        rows = body[group]
        if body["total"] > 0:
            assert sum(r["weight"] for r in rows) == pytest.approx(1.0)
            assert sum(r["value"] for r in rows) == pytest.approx(body["total"])
        else:
            assert rows == []
        assert [r["value"] for r in rows] == sorted((r["value"] for r in rows), reverse=True)
        for r in rows:
            assert r["weight"] == pytest.approx(r["value"] / body["total"])


def test_needs_a_login(client):
    assert client.get("/portfolio/allocation").status_code == 401


def test_empty_portfolio(client, user):
    body = allocation(client, user)
    assert body == {"currency": "CAD", "total": 0, "unpriced": [], "by_asset_type": [], "by_account": [],
                    "by_holding": [], "by_currency": []}


def test_values_and_weights_per_group(client, user):
    trade(client, user, "AAPL", 2, account="TFSA")  # 280 CAD
    trade(client, user, "SHOP.TO", 1, account="RRSP")  # 50 CAD
    trade(client, user, "btc", 0.01, price=40000, asset_type="crypto")  # 500 CAD, no account

    body = allocation(client, user)
    assert body["currency"] == "CAD"
    assert body["total"] == pytest.approx(830)
    assert body["unpriced"] == []
    assert as_map(body["by_asset_type"]) == pytest.approx({"crypto": 500, "stock": 330})
    assert [r["key"] for r in body["by_asset_type"]] == ["crypto", "stock"]
    assert as_map(body["by_account"]) == pytest.approx({"UNSET": 500, "TFSA": 280, "RRSP": 50})
    assert as_map(body["by_currency"]) == pytest.approx({"CRYPTO": 500, "USD": 280, "CAD": 50})
    assert [(h["symbol"], h["asset_type"]) for h in body["by_holding"]] == [
        ("btc", "crypto"), ("AAPL", "stock"), ("SHOP.TO", "stock")]
    assert body["by_holding"][0]["weight"] == pytest.approx(500 / 830)
    assert_weights(body)


def test_amounts_follow_the_users_currency(client, make_user):
    owner = make_user(currency="USD")
    trade(client, owner, "AAPL", 1, account="TFSA")
    body = allocation(client, owner)
    assert body["currency"] == "USD"
    assert body["total"] == pytest.approx(98)  # 100 USD -> 140 CAD -> 98 USD at the test rates
    assert as_map(body["by_account"]) == pytest.approx({"TFSA": 98})


def test_sells_reduce_their_own_account(client, user):
    trade(client, user, "AAPL", 10, account="TFSA")
    trade(client, user, "AAPL", 5, account="RRSP")
    trade(client, user, "AAPL", 4, action="SELL", account="TFSA")

    body = allocation(client, user)
    assert as_map(body["by_account"]) == pytest.approx({"TFSA": 6 * 140, "RRSP": 5 * 140})
    assert body["total"] == pytest.approx(11 * 140)
    assert_weights(body)


def test_a_sell_from_an_account_without_enough_takes_from_not_set_first(client, user):
    trade(client, user, "AAPL", 10)  # untagged
    trade(client, user, "AAPL", 5, account="TFSA")
    trade(client, user, "AAPL", 8, action="SELL", account="RRSP")  # RRSP never held any

    body = allocation(client, user)
    # nothing goes negative, the untagged shares cover the sell, and the total stays the holding's 7 shares
    assert as_map(body["by_account"]) == pytest.approx({"TFSA": 5 * 140, "UNSET": 2 * 140})
    assert body["total"] == pytest.approx(7 * 140)
    assert_weights(body)


def test_a_partly_covered_sell_takes_the_rest_from_the_largest_other_account(client, user, db):
    trade(client, user, "AAPL", 3, account="TFSA")
    trade(client, user, "AAPL", 2, account="FHSA")
    trade(client, user, "AAPL", 6, account="RRSP")
    # such a sell is refused now; older data can still have one (saved before sells were checked per account)
    sold = trade(client, user, "AAPL", 5, action="SELL")
    db.set_transaction(sold["id"], account_type="TFSA")  # 3 from the TFSA, 2 more from the RRSP

    body = allocation(client, user)
    assert as_map(body["by_account"]) == pytest.approx({"RRSP": 4 * 140, "FHSA": 2 * 140})
    assert_weights(body)


def test_selling_everything_empties_every_account(client, user, db):
    trade(client, user, "AAPL", 3, account="TFSA")
    trade(client, user, "AAPL", 2)
    sold = trade(client, user, "AAPL", 5, action="SELL")
    db.set_transaction(sold["id"], account_type="RRSP")  # older data, see the test above
    trade(client, user, "AAPL", 1, account="FHSA")

    body = allocation(client, user)
    assert as_map(body["by_account"]) == pytest.approx({"FHSA": 140})
    assert body["total"] == pytest.approx(140)


def test_unpriced_holdings_are_listed_and_left_out(client, user):
    trade(client, user, "AAPL", 1, account="TFSA")
    trade(client, user, "GONE", 3, account="RRSP")  # no source has a price for it

    body = allocation(client, user)
    assert body["unpriced"] == ["GONE"]
    assert body["total"] == pytest.approx(140)
    assert [h["symbol"] for h in body["by_holding"]] == ["AAPL"]
    assert as_map(body["by_account"]) == pytest.approx({"TFSA": 140})  # the RRSP only holds the unpriced one
    assert_weights(body)


def test_nothing_priced_gives_no_weights(client, user):
    trade(client, user, "GONE", 3)
    body = allocation(client, user)
    assert body["unpriced"] == ["GONE"]
    assert body["total"] == 0
    assert_weights(body)


def test_other_users_trades_are_not_included(client, make_user):
    me, someone = make_user(), make_user()
    trade(client, me, "AAPL", 1, account="TFSA")
    trade(client, someone, "MSFT", 10, account="RRSP")
    trade(client, someone, "AAPL", 50)

    body = allocation(client, me)
    assert body["total"] == pytest.approx(140)
    assert as_map(body["by_account"]) == pytest.approx({"TFSA": 140})
    assert [h["symbol"] for h in body["by_holding"]] == ["AAPL"]


def test_total_matches_the_holdings_and_the_dashboard(client, user):
    trade(client, user, "AAPL", 2.5, account="TFSA")
    trade(client, user, "MSFT", 1.25)
    trade(client, user, "SHOP.TO", 7, account="NON_REGISTERED")
    trade(client, user, "btc", 0.0123, price=40000, asset_type="crypto", account="TFSA")
    trade(client, user, "MSFT", 0.5, action="SELL", account="RRSP")
    trade(client, user, "GONE", 1)

    body = allocation(client, user)
    holdings = client.get("/holdings", headers=user.headers).json()
    dashboard = client.get("/dashboard", headers=user.headers).json()
    priced = {h["symbol"]: h["current_price"] for h in holdings if h["current_price"] is not None}

    assert body["total"] == pytest.approx(sum(priced.values()))
    assert body["total"] == pytest.approx(dashboard["value"])
    assert body["unpriced"] == dashboard["unpriced"]
    assert {h["symbol"]: h["value"] for h in body["by_holding"]} == pytest.approx(priced)
    assert_weights(body)


def test_no_extra_price_lookups(client, user, market):
    trade(client, user, "AAPL", 1)
    trade(client, user, "SHOP.TO", 1)
    trade(client, user, "btc", 0.01, price=40000, asset_type="crypto")
    client.get("/holdings", headers=user.headers)  # fills the price and listing currency caches
    market.requested.clear()

    body = allocation(client, user)
    assert market.requested == []  # everything, the listing currencies too, came from what /holdings fetched
    assert as_map(body["by_currency"]) == pytest.approx({"CRYPTO": 500, "USD": 140, "CAD": 50})


# ---------------------------------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------------------------------
def t(action, quantity, account=None, api_id="AAPL"):
    return SimpleNamespace(action=action, quantity=quantity, account_type=account, api_id=api_id)


def test_replay_accounts_rules():
    positions = replay_accounts([
        t("BUY", 0.3, "TFSA"), t("BUY", 0.1, "TFSA"), t("SELL", 0.2, "TFSA"),  # exact decimals: 0.2 left
        t("BUY", 1, api_id="ETH"), t("SELL", 0.4, "RRSP", api_id="ETH"),
        t("SELL", 1, "TFSA", api_id="NEVER"),  # nothing held: ignored
    ])
    assert positions == {"AAPL": {"TFSA": Decimal("0.2")}, "ETH": {"UNSET": Decimal("0.6")}}


def test_replay_accounts_ties_go_by_name():
    positions = replay_accounts([t("BUY", 2, "TFSA"), t("BUY", 2, "RRSP"), t("SELL", 1, "FHSA")])
    assert positions == {"AAPL": {"TFSA": Decimal(2), "RRSP": Decimal(1)}}


def test_replay_accounts_sell_all_within_the_tolerance():
    positions = replay_accounts([t("BUY", 1, "TFSA"), t("BUY", 2), t("SELL", 2.99999999999999, "RRSP")])
    assert positions == {}


def test_listing_currency_uses_the_cache_or_the_ticker(monkeypatch):
    monkeypatch.setattr(services, "_symbol_currency_cache", {"VOD.L": "GBp", "SAP.DE": "EUR"})
    assert listing_currency("VOD.L", "stock") == "GBP"  # pence are pound exposure
    assert listing_currency("SAP.DE", "stock") == "EUR"
    assert listing_currency("RY.TO", "stock") == "CAD"  # not looked up yet: from the suffix
    assert listing_currency("AAPL", "stock") == "USD"
    assert listing_currency("ODD.XX", "stock") == "OTHER"
    assert listing_currency("btc", "crypto") == "CRYPTO"


def test_build_allocation_falls_back_to_not_set_for_a_holding_without_accounts():
    holdings = {"AAPL": {"quantity": 2.0, "type": "stock"}}
    body = build_allocation(holdings, {}, {"AAPL": 10.0}, "cad")
    assert body["currency"] == "CAD"
    assert body["by_account"] == [{"key": "UNSET", "value": 20.0, "weight": 1.0}]
