"""
Coins that share a ticker: trades keep the CoinGecko id picked in search (`coin_id`), and every CoinGecko lookup for
that holding (price fallback, charts) asks for that exact coin. Trades without one keep the ticker lookup.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.database import ADDED_COLUMNS, add_missing_columns
from test_valuation import coingecko  # noqa: F401 - the CoinGecko stub fixture


def post(client, owner, **overrides):
    body = {"symbol": "pepe", "action": "BUY", "asset_type": "crypto", "price_of_one": 0.00002,
            "quantity": 1_000_000, "api_id": "pepe"}
    body.update(overrides)
    return client.post("/transactions", headers=owner.headers, json=body)


def test_coin_id_is_saved_with_a_crypto_trade(client, user, db):
    res = post(client, user, coin_id="Pepe-Impostor ")
    assert res.status_code == 200, res.text
    assert db.get_transaction(res.json()["id"]).coin_id == "pepe-impostor"  # stripped and lowercased
    [row] = client.get("/transactions", headers=user.headers).json()
    assert row["coin_id"] == "pepe-impostor"


def test_coin_id_is_optional_and_ignored_for_stocks(client, user, db):
    old_client = post(client, user)  # an older app version doesn't send it
    blank = post(client, user, coin_id="")
    stock = post(client, user, symbol="AAPL", api_id="AAPL", asset_type="stock", price_of_one=100, quantity=1,
                 coin_id="apple")
    for res in (old_client, blank, stock):
        assert res.status_code == 200, res.text
        assert db.get_transaction(res.json()["id"]).coin_id is None


@pytest.mark.parametrize("bad", ["../coins", "a/b", "bit coin", "x" * 81, "btc?x=1"])
def test_coin_id_must_look_like_a_coingecko_id(client, user, bad):
    # it goes into CoinGecko url paths, so nothing but letters, digits and dashes
    assert post(client, user, coin_id=bad).status_code == 422


def test_holding_with_a_coin_id_is_priced_from_that_coin(client, user, coingecko):
    coingecko.prices["pepe"] = 0.00004  # the most popular coin with the ticker
    coingecko.prices_by_id["pepe-impostor"] = 0.001  # the coin that was actually bought
    assert post(client, user, coin_id="pepe-impostor").status_code == 200

    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["coin_id"] == "pepe-impostor"
    assert h["current_price"] == pytest.approx(1000)

    d = client.get("/dashboard?current_timeperiod=all", headers=user.headers).json()
    assert d["value"] == pytest.approx(1000)
    history = client.get("/portfolio/history?range=7", headers=user.headers).json()
    assert history[-1]["value"] == pytest.approx(1000)

    assert set(coingecko.coin_ids) == {"pepe-impostor"}  # never the ticker lookup


def test_older_trades_without_a_coin_id_keep_the_ticker_lookup(client, user, coingecko):
    coingecko.prices["pepe"] = 0.00004
    assert post(client, user).status_code == 200

    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["coin_id"] is None
    assert h["current_price"] == pytest.approx(40)
    assert set(coingecko.coin_ids) == {None}


def test_the_newest_trade_with_a_coin_id_names_the_holding(client, user, coingecko):
    coingecko.prices_by_id["pepe-impostor"] = 0.001
    assert post(client, user).status_code == 200  # an older trade without one
    assert post(client, user, coin_id="pepe-impostor").status_code == 200
    [h] = client.get("/holdings", headers=user.headers).json()
    assert h["coin_id"] == "pepe-impostor"
    assert h["current_price"] == pytest.approx(2000)


def test_price_history_uses_the_coin_id(client, user, coingecko):
    coingecko.prices["pepe"] = 0.00004
    coingecko.prices_by_id["pepe-impostor"] = 0.001
    body = client.get("/prices/history?symbol=PEPE&type=crypto&range=1M&coin_id=pepe-impostor",
                      headers=user.headers).json()
    assert body["source"] == "CoinGecko"
    assert body["data"][-1]["price"] == pytest.approx(0.001)
    assert coingecko.coin_ids == ["pepe-impostor"]

    # without one it's the most popular coin with the ticker, cached separately
    body = client.get("/prices/history?symbol=PEPE&type=crypto&range=1M", headers=user.headers).json()
    assert body["data"][-1]["price"] == pytest.approx(0.00004)


def test_price_history_rejects_a_bad_coin_id(client, user):
    res = client.get("/prices/history?symbol=PEPE&type=crypto&range=1M&coin_id=../x", headers=user.headers)
    assert res.status_code == 422


def test_editing_the_coin_id_and_changing_the_asset(client, user, db):
    tx = post(client, user, coin_id="pepe-impostor").json()

    res = client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"coin_id": "pepe"})
    assert res.status_code == 200 and db.get_transaction(tx["id"]).coin_id == "pepe"

    # an edit that doesn't mention it keeps it
    client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"quantity": 5})
    assert db.get_transaction(tx["id"]).coin_id == "pepe"

    # a different asset without a new id: the old coin no longer applies
    client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"api_id": "doge", "symbol": "doge"})
    assert db.get_transaction(tx["id"]).coin_id is None

    # stocks never keep one
    client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"coin_id": "dogecoin"})
    client.put(f"/transactions/{tx['id']}", headers=user.headers, json={"asset_type": "stock"})
    assert db.get_transaction(tx["id"]).coin_id is None


async def _migrate_old_transactions(path):
    old_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with old_engine.begin() as conn:
            await conn.execute(text("CREATE TABLE transactions (id VARCHAR PRIMARY KEY, user_id CHAR(32))"))
            await conn.execute(text("INSERT INTO transactions VALUES ('t1', 'a')"))
            await add_missing_columns(conn)
            rows = await conn.execute(text("SELECT id, coin_id FROM transactions"))
            return [tuple(row) for row in rows]
    finally:
        await old_engine.dispose()


def test_coin_id_column_reaches_an_existing_database(run, tmp_path):
    assert "coin_id" in {name for name, _, _ in ADDED_COLUMNS["transactions"]}
    assert run(_migrate_old_transactions, (tmp_path / "old.db").as_posix()) == [("t1", None)]
