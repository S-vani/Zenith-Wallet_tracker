"""
Trades can say which account they were made in (TFSA, RRSP, FHSA, RESP, NON_REGISTERED), or nothing (null). The
account labels and filters trades; holdings and the dashboard stay per symbol. Sells are also checked against their
own account (tests/test_account_oversell.py).
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.database import ADDED_COLUMNS, add_missing_columns
from backend.schemas.assets import ACCOUNT_TYPES


def post(client, owner, expect=200, **overrides):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
            "api_id": "AAPL"}
    body.update(overrides)
    res = client.post("/transactions", headers=owner.headers, json=body)
    assert res.status_code == expect, res.text
    return res.json()


def listed(client, owner, **params):
    res = client.get("/transactions", headers=owner.headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_the_allowed_values_live_in_one_place():
    assert ACCOUNT_TYPES == ("TFSA", "RRSP", "FHSA", "RESP", "NON_REGISTERED")


@pytest.mark.parametrize("account", ACCOUNT_TYPES)
def test_account_type_is_saved_and_returned(client, user, db, account):
    tx = post(client, user, account_type=account)
    assert tx["account_type"] == account  # the create response
    assert db.get_transaction(tx["id"]).account_type == account
    assert client.get(f"/transactions/{tx['id']}", headers=user.headers).json()["account_type"] == account
    [row] = listed(client, user)
    assert row["account_type"] == account


def test_account_type_defaults_to_null(client, user, db):
    left_out = post(client, user)  # older app versions don't send it
    explicit = post(client, user, account_type=None)
    for tx in (left_out, explicit):
        assert tx["account_type"] is None
        assert db.get_transaction(tx["id"]).account_type is None
    assert [row["account_type"] for row in listed(client, user)] == [None, None]


@pytest.mark.parametrize("bad", ["tfsa", "TFSA ", "", "LIRA", "UNSET", 1, ["TFSA"]])
def test_unknown_account_types_are_rejected(client, user, bad):
    post(client, user, expect=422, account_type=bad)
    tx = post(client, user)
    res = client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"account_type": bad})
    assert res.status_code == 422


def test_editing_the_account_type(client, user, db):
    tx = post(client, user, account_type="TFSA")
    put = lambda body: client.put(f"/transactions/{tx['id']}", headers=user.headers, json=body)  # noqa: E731

    res = put({"account_type": "RRSP"})
    assert res.status_code == 200 and res.json()["account_type"] == "RRSP"

    # an edit that doesn't mention it keeps it
    assert put({"quantity": 3}).status_code == 200
    assert db.get_transaction(tx["id"]).account_type == "RRSP"

    # an explicit null clears it
    res = put({"account_type": None})
    assert res.status_code == 200 and res.json()["account_type"] is None
    assert db.get_transaction(tx["id"]).account_type is None


def test_filtering_the_list_by_account(client, user):
    tfsa = post(client, user, account_type="TFSA")
    rrsp = post(client, user, account_type="RRSP", symbol="MSFT", api_id="MSFT")
    unset = post(client, user)

    assert [r["id"] for r in listed(client, user, account_type="TFSA")] == [tfsa["id"]]
    assert [r["id"] for r in listed(client, user, account_type="RRSP")] == [rrsp["id"]]
    assert [r["id"] for r in listed(client, user, account_type="UNSET")] == [unset["id"]]
    assert listed(client, user, account_type="FHSA") == []
    assert len(listed(client, user)) == 3  # no filter = every account

    # combines with the other filters
    assert listed(client, user, account_type="TFSA", symbol="MSFT") == []
    assert [r["id"] for r in listed(client, user, account_type="RRSP", symbol="MS")] == [rrsp["id"]]


@pytest.mark.parametrize("bad", ["tfsa", "NONE", "null", ""])
def test_unknown_account_filters_are_rejected(client, user, bad):
    res = client.get("/transactions", headers=user.headers, params={"account_type": bad})
    assert res.status_code == 422


def test_holdings_and_the_oversell_check_stay_per_symbol(client, user):
    post(client, user, account_type="TFSA", quantity=2)
    # the RRSP holds none: refused (per account), while a sell with no account is only checked overall
    post(client, user, expect=409, account_type="RRSP", action="SELL", quantity=1, price_of_one=120)
    post(client, user, action="SELL", quantity=1, price_of_one=120)
    post(client, user, account_type="TFSA", action="SELL", quantity=1, price_of_one=120)
    post(client, user, expect=409, account_type="TFSA", action="SELL", quantity=1)

    assert client.get("/holdings", headers=user.headers).json() == []


def test_users_only_filter_their_own_trades(client, make_user):
    alice, bob = make_user(), make_user()
    post(client, alice, account_type="TFSA")
    assert listed(client, bob, account_type="TFSA") == []


async def _migrate_old_transactions(path):
    old_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with old_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE transactions (id VARCHAR PRIMARY KEY, user_id CHAR(32))"))
            await conn.execute(text("INSERT INTO transactions VALUES ('t1', 'a')"))
            await add_missing_columns(conn)
            rows = await conn.execute(text("SELECT id, account_type FROM transactions"))
            return [tuple(row) for row in rows]
    finally:
        await old_engine.dispose()


def test_account_type_column_reaches_an_existing_database(run, tmp_path):
    assert "account_type" in {name for name, _, _ in ADDED_COLUMNS["transactions"]}
    # rows saved before the column existed come back as "not set"
    assert run(_migrate_old_transactions, (tmp_path / "old.db").as_posix()) == [("t1", None)]
