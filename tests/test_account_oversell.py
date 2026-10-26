"""
Sells are checked against their own account (backend/services/asset_services.py, account_split): a tagged sell may
use its account's shares plus the "not set" ones, a sell with no account is only checked overall, and a change is
refused only when it makes some sell's shortfall worse, so older data stays editable. Holdings stay per symbol.
"""
import itertools
import random
from decimal import Decimal
from types import SimpleNamespace

import pytest

import backend.services.asset_services as services
from backend.services.allocation import replay_accounts

ACCOUNT_OVERSOLD = "Insufficient holdings in that account"


def post(client, owner, expect=200, **overrides):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
            "api_id": "AAPL"}
    body.update(overrides)
    res = client.post("/transactions", headers=owner.headers, json=body)
    assert res.status_code == expect, res.text
    return res.json()


def put(client, owner, tx_id, expect=200, **changes):
    res = client.put(f"/transactions/{tx_id}", headers=owner.headers, json=changes)
    assert res.status_code == expect, res.text
    return res.json()


def holding(client, owner, symbol="AAPL"):
    return next(h for h in client.get("/holdings", headers=owner.headers).json() if h["symbol"] == symbol)


def test_a_sell_cant_take_more_than_its_account_holds(client, user):
    post(client, user, quantity=10, account_type="TFSA")
    post(client, user, quantity=6, account_type="NON_REGISTERED")

    res = client.post("/transactions", headers=user.headers, json={
        "symbol": "AAPL", "action": "SELL", "asset_type": "stock", "price_of_one": 120, "quantity": 15,
        "api_id": "AAPL", "account_type": "TFSA"})
    assert res.status_code == 409 and res.json()["detail"] == ACCOUNT_OVERSOLD

    post(client, user, action="SELL", quantity=10, account_type="TFSA")  # exactly what the TFSA holds
    post(client, user, expect=409, action="SELL", quantity=1, account_type="TFSA")
    # holdings stay one position per symbol, with the split per account alongside
    h = holding(client, user)
    assert h["quantity"] == 6 and h["accounts"] == {"NON_REGISTERED": 6}


def test_not_set_shares_can_be_sold_from_any_account(client, user):
    # older users: untagged buys, then a sell tagged TFSA (the untagged shares could have been in the TFSA)
    post(client, user, quantity=10)
    post(client, user, quantity=2, account_type="TFSA")
    post(client, user, action="SELL", quantity=11, account_type="TFSA")  # 2 TFSA + 9 not set
    assert holding(client, user)["accounts"] == {"UNSET": 1}
    post(client, user, expect=409, action="SELL", quantity=2, account_type="RRSP")  # only 1 left anywhere


def test_a_sell_with_no_account_is_only_checked_overall(client, user):
    post(client, user, quantity=3, account_type="TFSA")
    post(client, user, quantity=3, account_type="RRSP")
    post(client, user, action="SELL", quantity=5)
    post(client, user, expect=409, action="SELL", quantity=2)
    assert holding(client, user)["quantity"] == 1


def test_a_backdated_sell_is_checked_against_the_account_at_that_date(client, user):
    post(client, user, quantity=5, account_type="TFSA", created_at="2024-01-10T15:00:00Z")
    post(client, user, quantity=5, account_type="TFSA", created_at="2024-03-10T15:00:00Z")
    post(client, user, quantity=5, account_type="RRSP", created_at="2024-01-05T15:00:00Z")
    post(client, user, expect=409, action="SELL", quantity=7, account_type="TFSA",
         created_at="2024-02-01T15:00:00Z")
    post(client, user, action="SELL", quantity=5, account_type="TFSA", created_at="2024-02-01T15:00:00Z")


def test_edits_and_deletes_are_checked_per_account(client, user):
    tfsa_buy = post(client, user, quantity=10, account_type="TFSA")
    post(client, user, quantity=10, account_type="NON_REGISTERED")
    tfsa_sell = post(client, user, action="SELL", quantity=8, account_type="TFSA")

    put(client, user, tfsa_sell["id"], expect=409, quantity=12)  # more than the TFSA held
    put(client, user, tfsa_buy["id"], expect=409, quantity=5)  # the sell would be 3 short
    put(client, user, tfsa_buy["id"], expect=409, account_type="RRSP")  # moving the buy away
    res = client.delete(f"/transactions/{tfsa_buy['id']}", headers=user.headers)
    assert res.status_code == 409 and res.json()["detail"] == ACCOUNT_OVERSOLD
    # moving the sell to the account that holds the shares is fine, and so is a price change
    put(client, user, tfsa_sell["id"], account_type="NON_REGISTERED")
    put(client, user, tfsa_sell["id"], price_of_one=130)
    assert client.delete(f"/transactions/{tfsa_buy['id']}", headers=user.headers).status_code == 200


def test_older_data_with_sells_in_the_wrong_account_stays_editable(client, user, db):
    post(client, user, quantity=10, account_type="TFSA")
    sell = post(client, user, action="SELL", quantity=4, account_type="TFSA")
    db.set_transaction(sell["id"], account_type="RRSP")  # saved before sells were checked per account

    put(client, user, sell["id"], price_of_one=150)  # not made worse: fine
    put(client, user, sell["id"], quantity=3)  # smaller shortfall: fine
    put(client, user, sell["id"], expect=409, quantity=5)  # bigger shortfall: refused
    other = post(client, user, quantity=1, account_type="NON_REGISTERED")
    assert client.delete(f"/transactions/{other['id']}", headers=user.headers).status_code == 200
    # a new trade elsewhere in the history is still allowed
    post(client, user, action="SELL", quantity=2, account_type="TFSA")


def test_account_split_matches_the_allocation_view():
    """account_split's per-account quantities are allocation.replay_accounts' (same draw order), on random data."""
    rng = random.Random(7)
    accounts = [None, "TFSA", "RRSP", "NON_REGISTERED"]
    ids = itertools.count()
    for _ in range(200):
        trades, held = [], Decimal(0)
        for _ in range(rng.randint(1, 12)):
            qty = Decimal(rng.randint(1, 6))
            action = "SELL" if held and rng.random() < 0.45 else "BUY"
            qty = min(qty, held) if action == "SELL" else qty
            held += qty if action == "BUY" else -qty
            trades.append(SimpleNamespace(id=str(next(ids)), api_id="AAPL", action=action, quantity=float(qty),
                                          account_type=rng.choice(accounts)))
        split, _ = services.account_split(trades)
        assert split == replay_accounts(trades)


@pytest.mark.parametrize("before, after, refused", [
    ({}, {}, False),
    ({}, {"s1": Decimal(1)}, True),
    ({"s1": Decimal(2)}, {"s1": Decimal(2)}, False),
    ({"s1": Decimal(2)}, {"s1": Decimal(1)}, False),
    ({"s1": Decimal(2)}, {"s1": Decimal(3)}, True),
    ({"s1": Decimal(2)}, {}, False),
])
def test_account_oversell_added(before, after, refused):
    assert services.account_oversell_added(before, after) is refused
