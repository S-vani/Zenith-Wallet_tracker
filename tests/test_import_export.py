"""
CSV export (GET /transactions/export) and the two-step import (POST /transactions/import/preview, then
POST /transactions/import) for Zenith's template, Wealthsimple's activities export and Questrade's activity export.
"""
import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import backend.routes.imports as import_routes
import backend.services.imports as importer
from backend.services.imports import (FileError, csv_safe, map_account_type, parse_csv, parse_number,
                                      parse_trade_date, questrade_symbol)

from conftest import RATES


@pytest.fixture(autouse=True)
def fresh_rate_limits(monkeypatch):
    # the per-user import limits live in memory; each test starts with none used
    monkeypatch.setattr(import_routes, "_preview_times", {})
    monkeypatch.setattr(import_routes, "_import_times", {})


def preview(client, owner, text, fmt="auto", default_account_type=None, expect=200):
    res = client.post("/transactions/import/preview", headers=owner.headers,
                      json={"csv": text, "format": fmt, "default_account_type": default_account_type})
    assert res.status_code == expect, res.text
    return res.json()


def commit(client, owner, rows, expect=200):
    res = client.post("/transactions/import", headers=owner.headers, json={"rows": rows})
    assert res.status_code == expect, res.text
    return res.json()


def trades(client, owner):
    res = client.get("/transactions", headers=owner.headers)
    assert res.status_code == 200, res.text
    return res.json()


def export(client, owner):
    res = client.get("/transactions/export", headers=owner.headers)
    assert res.status_code == 200, res.text
    return res


ZENITH = """date,action,asset_type,symbol,quantity,price,currency,account_type,coin_id
2024-01-05T15:30:00+00:00,BUY,stock,aapl,10,150.25,USD,TFSA,
2024-02-01,BUY,crypto,BTC,0.5,60000,CAD,NON_REGISTERED,bitcoin
2024-03-01T10:00:00Z,SELL,stock,AAPL,4,170,USD,,
"""

WEALTHSIMPLE = """transaction_date,settlement_date,account_id,account_type,activity_type,activity_sub_type,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount
2024-01-10,2024-01-11,HQ123,TFSA,Trade,BUY,LONG,VFV,Vanguard S&P 500 Index ETF,CAD,10,120.50,0,-1205.00
2024-01-12,2024-01-15,HQ124,Personal,Trade,BUY,LONG,AAPL,Apple Inc,USD,2,185.00,0,-370.00
2024-01-20,,HQ123,TFSA,Dividend,,,VFV,Vanguard S&P 500 Index ETF,CAD,1.23,,,1.23
2024-01-21,,HQ123,TFSA,MoneyMovement,EFT,,,,CAD,500,,,500
2024-02-01,2024-02-01,CR1,Crypto,Trade,BUY,LONG,ETH,Ethereum,CAD,0.25,3200,8.00,-808.00
2024-02-15,2024-02-16,HQ124,Personal,Trade,SELL,LONG,AAPL,Apple Inc,USD,-1,190.00,0,190.00
2024-02-20,2024-02-21,LI1,LIRA,Trade,BUY,LONG,XEQT.TO,iShares Core Equity,CAD,3,28,0,-84
"As of 2024-03-01 13:19 GMT-05:00"
"""

QUESTRADE = """Transaction Date,Settlement Date,Action,Symbol,Description,Quantity,Price,Gross Amount,Commission,Net Amount,Currency,Account #,Activity Type,Account Type
2024-01-09 12:00:00 AM,2024-01-11 12:00:00 AM,Buy,SHOP.TO,SHOPIFY INC,10.00000,100.00000000,-1000.00,-4.95,-1004.95,CAD,11112222,Trades,Individual TFSA
2024-01-10 12:00:00 AM,2024-01-12 12:00:00 AM,Buy,ABC.VN,ABC MINING,100.00000,0.50000000,-50.00,-4.95,-54.95,CAD,11112222,Trades,Individual TFSA
2024-01-11 12:00:00 AM,2024-01-13 12:00:00 AM,Buy,DLR.U.TO,GLOBAL X US DOLLAR,5.00000,10.00000000,-50.00,0.00,-50.00,USD,33334444,Trades,Individual margin
2024-01-12 12:00:00 AM,2024-01-12 12:00:00 AM,DEP,,CONTRIBUTION,0.00000,0.00000000,0.00,0.00,1000.00,CAD,11112222,Deposits,Individual TFSA
2024-01-15 12:00:00 AM,2024-01-15 12:00:00 AM,DIV,SHOP.TO,SHOPIFY DIV,0.00000,0.00000000,0.00,0.00,2.10,CAD,11112222,Dividends,Individual TFSA
2024-02-01 12:00:00 AM,2024-02-05 12:00:00 AM,Sell,SHOP.TO,SHOPIFY INC,-4.00000,120.00000000,480.00,-4.95,475.05,CAD,11112222,Trades,Individual TFSA
2024-02-02 12:00:00 AM,2024-02-05 12:00:00 AM,Buy,RY,ROYAL BANK,1.00000,130.00000000,-130.00,0.00,-130.00,CAD,55556666,Trades,Individual RRSP
"""


# ---------------------------------------------------------------------------------------------------------------------
# Parsing (no database)
# ---------------------------------------------------------------------------------------------------------------------
def test_zenith_template_rows():
    parsed = parse_csv(ZENITH)
    assert parsed.format == "zenith" and parsed.skipped_non_trades == 0
    apple, btc, sell = [row.as_json() for row in parsed.rows]
    assert apple == {"line": 2, "date": "2024-01-05T15:30:00+00:00", "action": "BUY", "asset_type": "stock",
                     "symbol": "AAPL", "quantity": 10.0, "price": 150.25, "currency": "USD", "account_type": "TFSA",
                     "coin_id": None, "status": "ok", "message": None}
    # a day without a time is stored at noon UTC: the same calendar day across Canada
    assert btc["date"] == "2024-02-01T12:00:00+00:00"
    assert (btc["symbol"], btc["asset_type"], btc["coin_id"]) == ("btc", "crypto", "bitcoin")
    assert sell["date"] == "2024-03-01T10:00:00+00:00" and sell["account_type"] is None


def test_default_account_only_fills_rows_without_one():
    rows = parse_csv(ZENITH, default_account="RRSP").rows
    assert [row.account_type for row in rows] == ["TFSA", "NON_REGISTERED", "RRSP"]


def test_wealthsimple_buys_and_sells_only():
    parsed = parse_csv(WEALTHSIMPLE)
    assert parsed.format == "wealthsimple"
    assert parsed.skipped_non_trades == 2  # the dividend and the deposit; the "As of" footer isn't a row at all
    vfv, aapl, eth, sell, lira = parsed.rows
    assert all(row.status == "ok" for row in parsed.rows)

    assert (vfv.symbol, vfv.account_type, vfv.currency, vfv.price) == ("VFV", "TFSA", "CAD", Decimal("120.50"))
    # a CAD stock with no exchange in the file is probably on the TSX: say so instead of guessing
    assert ".TO (TSX)" in " ".join(vfv.notes)
    assert (aapl.account_type, aapl.notes) == ("NON_REGISTERED", [])  # "Personal" = non-registered; USD, no note
    assert (eth.asset_type, eth.symbol, eth.account_type) == ("crypto", "eth", "NON_REGISTERED")
    assert eth.price == Decimal("3200")  # the unit price, commission isn't added in
    assert (sell.action, sell.quantity) == ("SELL", Decimal("1"))  # exported as -1
    # a LIRA isn't one of our account types: left unset (or the default) with a note, never called non-registered
    assert lira.account_type is None and "LIRA" in lira.notes[0]
    assert parse_csv(WEALTHSIMPLE, default_account="TFSA").rows[4].account_type == "TFSA"


def test_wealthsimple_newer_layout_and_exchange_column():
    text = ("effective_date,effective_time,settlement_date,account_id,account_type,activity_type,activity_sub_type,"
            "description,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount,exchange\n"
            "2024-05-01,10:00:00,2024-05-02,A1,FHSA,Trade,BUY,\"Bought, FX Rate: 1.38\",LONG,CTC.A,Canadian Tire,"
            "CAD,2,150,0,-300,TSX\n"
            "2024-05-02,10:00:00,2024-05-03,A1,RESP,Trade,BUY,,LONG,ABC,Abc,CAD,4,,0,-10,TSXV\n")
    tire, abc = parse_csv(text).rows
    assert (tire.symbol, tire.account_type, tire.notes) == ("CTC-A.TO", "FHSA", [])
    # no unit price: worked out from the cash that moved, and said so
    assert (abc.symbol, abc.account_type, abc.price) == ("ABC.V", "RESP", Decimal("2.5"))
    assert "net amount" in abc.notes[0]


def test_questrade_rows():
    parsed = parse_csv(QUESTRADE)
    assert parsed.format == "questrade" and parsed.skipped_non_trades == 2
    shop, abc, dlr, sell, ry = parsed.rows
    assert all(row.status == "ok" for row in parsed.rows)
    # "12:00:00 AM" is just the day
    assert shop.date == datetime(2024, 1, 9, 12) and shop.date_only
    assert (shop.symbol, shop.account_type, shop.price) == ("SHOP.TO", "TFSA", Decimal("100"))
    assert abc.symbol == "ABC.V"  # Questrade's TSX Venture suffix is .VN, Yahoo's is .V
    assert (dlr.symbol, dlr.currency, dlr.account_type) == ("DLR-U.TO", "USD", "NON_REGISTERED")
    assert (sell.action, sell.quantity) == ("SELL", Decimal("4"))
    assert (ry.symbol, ry.account_type) == ("RY", "RRSP") and "TSX" in ry.notes[0]  # no suffix, CAD: check it


@pytest.mark.parametrize("symbol, expected", [("SHOP.TO", "SHOP.TO"), ("abc.vn", "ABC.V"), ("DLR.U.TO", "DLR-U.TO"),
                                              ("BRK.B", "BRK-B"), ("AAPL", "AAPL"), ("WEED.CN", "WEED.CN")])
def test_questrade_symbols(symbol, expected):
    assert questrade_symbol(symbol) == expected


@pytest.mark.parametrize("text, expected", [
    ("TFSA", "TFSA"), ("Individual TFSA", "TFSA"), ("Spousal RRSP", "RRSP"), ("Family RESP", "RESP"),
    ("fhsa", "FHSA"), ("Personal", "NON_REGISTERED"), ("Joint", "NON_REGISTERED"), ("Non-registered", "NON_REGISTERED"),
    ("NON_REGISTERED", "NON_REGISTERED"), ("Individual margin", "NON_REGISTERED"), ("Crypto", "NON_REGISTERED"),
    ("", None), ("Individual LIRA", "?"), ("RRIF", "?"), ("Chequing", "?"),
])
def test_account_mapping(text, expected):
    assert map_account_type(text) == expected


def test_auto_detect_and_unknown_files():
    assert parse_csv(ZENITH).format == "zenith"
    assert parse_csv(WEALTHSIMPLE).format == "wealthsimple"
    assert parse_csv(QUESTRADE).format == "questrade"
    # headers in another case / spacing still match
    assert parse_csv("Date, Action ,SYMBOL,Quantity,Price,Currency\n2024-01-01,buy,msft,1,10,usd\n").format == "zenith"
    with pytest.raises(FileError, match="couldn't recognise"):
        parse_csv("foo,bar\n1,2\n")
    with pytest.raises(FileError, match="Wealthsimple"):
        parse_csv(ZENITH, fmt="wealthsimple")


def test_row_errors_are_shown_not_raised():
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    text = ("date,action,symbol,quantity,price,currency\n"
            f"{tomorrow},BUY,AAPL,1,10,USD\n"
            "2024-01-01,BUY,AAPL,1,10,GBP\n"
            "2024-01-01,BUY,AAPL,0,10,USD\n"
            "2024-01-01,HOLD,AAPL,1,10,USD\n"
            "2024-01-01,BUY,=cmd|' /C calc'!A0,1,10,USD\n"
            "2024-01-01,BUY,AAPL,abc,10,USD\n"
            "1969-12-31,BUY,AAPL,1,10,USD\n"
            "03/04/2024,BUY,AAPL,1,10,USD\n"
            "2024-01-01,BUY,AAPL,1,0,USD\n"
            "2024-01-01,BUY,AAPL,1,10,USD\n")
    rows = [row.as_json() for row in parse_csv(text).rows]
    messages = [row["message"] for row in rows]
    assert [row["status"] for row in rows] == ["error"] * 9 + ["ok"]
    assert "future" in messages[0]
    assert "GBP" in messages[1]
    assert "greater than 0" in messages[2] and "greater than 0" in messages[8]
    assert "BUY or SELL" in messages[3]
    assert "isn't a ticker" in messages[4]
    assert "isn't a number" in messages[5]
    assert "1970" in messages[6]
    assert "two ways" in messages[7]
    assert rows[9]["line"] == 11


def test_numbers_and_dates():
    assert parse_number("1,234.50", "x") == Decimal("1234.50")
    assert parse_number("$12.30", "x") == Decimal("12.30")
    assert parse_number("(5.00)", "x") == Decimal("-5.00")
    assert parse_number("1,5", "x") == Decimal("1.5")
    assert parse_number("1,500", "x", decimal_comma=True) == Decimal("1.5")
    assert parse_number("1.234,5", "x") == Decimal("1234.5")
    assert parse_number("", "x") is None
    assert parse_trade_date("2024-03-01T10:00:00-05:00")[0] == datetime(2024, 3, 1, 15)
    assert parse_trade_date("2024-02-17 03:15:00 PM")[0] == datetime(2024, 2, 17, 15, 15)
    assert parse_trade_date("17/02/2024") == (datetime(2024, 2, 17, 12), True)
    # today's date alone is noon UTC, which may not have happened yet: never stored in the future
    now = datetime(2024, 6, 1, 8, 0)
    assert parse_trade_date("2024-06-01", now=now) == (now, True)


def test_semicolon_files_with_decimal_commas():
    text = "date;action;symbol;quantity;price;currency\n2024-01-02;BUY;SAP;1,5;120,25;EUR\n"
    [row] = parse_csv(text).rows
    assert (row.quantity, row.price, row.currency) == (Decimal("1.5"), Decimal("120.25"), "EUR")


def test_size_and_row_limits():
    with pytest.raises(FileError) as too_big:
        parse_csv("date,action,symbol,quantity,price,currency\n" + "x" * (2 * 1024 * 1024))
    assert too_big.value.status_code == 413

    rows = "".join("2024-01-01,BUY,AAPL,1,10,USD\n" for _ in range(5001))
    with pytest.raises(FileError, match="5,000 rows") as too_many:
        parse_csv("date,action,symbol,quantity,price,currency\n" + rows)
    assert too_many.value.status_code == 422
    assert len(parse_csv("date,action,symbol,quantity,price,currency\n" + rows[:-29]).rows) == 5000


def test_formula_injection_guard():
    assert csv_safe("=SUM(A1)") == "'=SUM(A1)"
    assert csv_safe("+1") == "'+1"
    assert csv_safe("@cmd") == "'@cmd"
    assert csv_safe("-x") == "'-x"
    assert csv_safe("\tx") == "'\tx"
    assert csv_safe("-12.5") == "-12.5"  # a plain negative number stays a number
    assert csv_safe("AAPL") == "AAPL"
    assert csv_safe(None) == ""


# ---------------------------------------------------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------------------------------------------------
def test_endpoints_need_a_login(client):
    assert client.get("/transactions/export").status_code == 401
    assert client.get("/transactions/import/template").status_code == 401
    assert client.post("/transactions/import/preview", json={"csv": ZENITH}).status_code == 401
    assert client.post("/transactions/import", json={"rows": []}).status_code == 401


def test_export_file(client, user, db, buy):
    first = buy(user, "AAPL", 2, 150)
    second = buy(user, "btc", 0.5, 60000, asset_type="crypto")
    db.set_created_at(first["id"], datetime(2023, 5, 1, 14, 0))
    res = export(client, user)

    assert res.headers["content-type"].startswith("text/csv")
    today = datetime.now(timezone.utc).date().isoformat()
    assert res.headers["content-disposition"] == f'attachment; filename="zenith-trades-{today}.csv"'
    assert res.headers["cache-control"] == "no-store"
    header, *rows = list(csv.reader(io.StringIO(res.text)))
    assert header == importer.EXPORT_COLUMNS
    # oldest first, the price as typed and its currency
    assert rows[0] == ["2023-05-01T14:00:00+00:00", "BUY", "stock", "AAPL", "2", "150", "CAD", "", ""]
    assert rows[1][1:7] == ["BUY", "crypto", "btc", "0.5", "60000", "CAD"]
    assert second["id"] not in res.text  # no ids or user ids in the file


def test_export_guards_formula_cells(client, user, buy):
    buy(user, "=1+1", 1, 10, api_id="X")  # the add-trade api doesn't restrict symbol characters
    res = export(client, user)
    [row] = list(csv.reader(io.StringIO(res.text)))[1:]
    assert row[3] == "'=1+1"


def test_older_trades_export_their_cad_price(client, user, db, buy, run):
    from sqlalchemy import update
    from backend.db.database import async_session_maker
    from backend.db_models.assets import Transaction
    tx = buy(user, "MSFT", 1, 300)

    async def forget_typed():
        async with async_session_maker() as session:
            await session.execute(update(Transaction).where(Transaction.id == tx["id"])
                                  .values(price_entered=None, currency_entered=None, price_of_one=420))
            await session.commit()
    run(forget_typed)
    [row] = list(csv.reader(io.StringIO(export(client, user).text)))[1:]
    assert row[5:7] == ["420", "CAD"]


def test_round_trip_into_a_new_account(client, make_user, db, buy, sell):
    source = make_user(currency="USD")
    a = buy(source, "AAPL", 10, 150)  # typed in USD
    s = sell(source, "AAPL", 4, 170.5)
    c = client.post("/transactions", headers=source.headers, json={
        "symbol": "btc", "api_id": "btc", "asset_type": "crypto", "action": "BUY", "price_of_one": 40000,
        "quantity": 0.12345678, "coin_id": "bitcoin", "account_type": "TFSA"}).json()
    db.set_created_at(a["id"], datetime(2022, 1, 3, 15, 30, 12))
    db.set_created_at(s["id"], datetime(2022, 6, 1, 9, 0))
    db.set_created_at(c["id"], datetime(2023, 2, 2, 2, 2, 2))
    text = export(client, source).text

    # back into the same account: everything is already there
    same = preview(client, source, text)
    assert same["format_detected"] == "zenith"
    assert same["summary"] == {"ok": 0, "duplicate": 3, "error": 0, "skipped_non_trades": 0}

    target = make_user(currency="CAD")
    result = preview(client, target, text)
    assert result["summary"]["ok"] == 3
    assert commit(client, target, result["rows"]) == {"imported": 3}

    def key(row):
        return (row["created_at"], row["action"], row["symbol"], row["quantity"], row["account_type"],
                row["coin_id"])
    assert sorted(map(key, trades(client, target))) == sorted(map(key, trades(client, source)))
    # the typed prices and currencies came across exactly
    assert export(client, target).text.split("\r\n")[1:] == text.split("\r\n")[1:]


def test_preview_saves_nothing_and_flags_duplicates(client, user, db, buy):
    tx = buy(user, "AAPL", 10, 150)
    db.set_created_at(tx["id"], datetime(2024, 1, 5, 15, 30, 40))
    text = ("date,action,asset_type,symbol,quantity,price,currency\n"
            "2024-01-05T15:30:00Z,BUY,stock,AAPL,10,150,CAD\n"  # same minute
            "2024-01-05,BUY,stock,AAPL,10,150,CAD\n"  # same day, but the saved trade is already matched
            "2024-01-05T15:30:00Z,BUY,stock,AAPL,11,150,CAD\n"  # other quantity
            "2024-01-05T15:30:00Z,SELL,stock,AAPL,10,150,CAD\n")  # other action
    result = preview(client, user, text)
    assert [row["status"] for row in result["rows"]] == ["duplicate", "ok", "ok", "ok"]
    assert "Already in your trades" in result["rows"][0]["message"]
    assert len(trades(client, user)) == 1


def test_day_only_rows_match_a_trade_that_day_in_another_currency(client, user, db, buy):
    tx = buy(user, "AAPL", 2, 280)  # typed in CAD = 200 USD at the test rate
    db.set_created_at(tx["id"], datetime(2024, 1, 12, 18, 45))
    result = preview(client, user, WEALTHSIMPLE.replace("185.00", "200.00"))
    apple = next(row for row in result["rows"] if row["symbol"] == "AAPL" and row["action"] == "BUY")
    assert apple["status"] == "duplicate"


def test_other_users_trades_are_not_duplicates(client, make_user, db, buy):
    owner, other = make_user(), make_user()
    tx = buy(other, "AAPL", 10, 150)
    db.set_created_at(tx["id"], datetime(2024, 1, 5, 15, 30))
    result = preview(client, owner, "date,action,symbol,quantity,price,currency\n2024-01-05T15:30:00Z,BUY,AAPL,10,150,CAD\n")
    assert result["rows"][0]["status"] == "ok"


def test_import_stores_prices_like_a_manual_trade(client, user, db):
    result = preview(client, user, ZENITH)
    commit(client, user, result["rows"])
    saved = {row["symbol"]: row for row in trades(client, user) if row["action"] == "BUY"}

    apple = db.get_transaction(saved["AAPL"]["id"])
    assert float(apple.price_entered) == 150.25 and apple.currency_entered == "USD"
    assert float(apple.price_of_one) == pytest.approx(150.25 / RATES["usd"])  # CAD at today's rate
    assert apple.created_at == datetime(2024, 1, 5, 15, 30) and apple.account_type == "TFSA"
    btc = db.get_transaction(saved["btc"]["id"])
    assert (btc.api_id, btc.coin_id, float(btc.price_of_one)) == ("btc", "bitcoin", 60000)
    # the sell's profit came from the replayed ledger, in its own currency: (170 - 150.25) * 4 USD
    sold = next(row for row in trades(client, user) if row["action"] == "SELL")
    assert db.get_transaction(sold["id"]).profit is not None
    assert sold["profit"] == pytest.approx((170 - 150.25) * 4 / RATES["usd"])


def test_commit_revalidates_every_row(client, user):
    rows = preview(client, user, ZENITH)["rows"]
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    for change in ({"date": future}, {"currency": "GBP"}, {"quantity": 0}, {"quantity": "NaN"}, {"date": None},
                   {"account_type": "LIRA"}, {"symbol": "=HYPERLINK()"}, {"action": "HOLD"}, {"price": 0}):
        tampered = [dict(rows[0], **change), *rows[1:]]
        res = client.post("/transactions/import", headers=user.headers, json={"rows": tampered})
        assert res.status_code == 422, change
        assert res.json()["detail"].startswith("Line 2:") and "Nothing was imported" in res.json()["detail"]
    assert commit(client, user, [], expect=422)
    assert trades(client, user) == []


def test_an_oversell_rolls_back_the_whole_import(client, user, buy):
    buy(user, "MSFT", 1, 100)
    text = ("date,action,symbol,quantity,price,currency\n"
            "2024-01-01,BUY,AAPL,5,100,USD\n"
            "2024-01-02,BUY,NVDA,5,100,USD\n"
            "2024-01-03,SELL,NVDA,6,120,USD\n")
    rows = preview(client, user, text)["rows"]
    res = client.post("/transactions/import", headers=user.headers, json={"rows": rows})
    assert res.status_code == 409
    assert "NVDA" in res.json()["detail"] and "line 4" in res.json()["detail"]
    assert [row["symbol"] for row in trades(client, user)] == ["MSFT"]  # AAPL wasn't kept either


def test_an_import_that_leaves_an_existing_sell_short(client, user, db, buy, sell):
    b = buy(user, "AAPL", 10, 100)
    s = sell(user, "AAPL", 10, 120)
    db.set_created_at(b["id"], datetime(2024, 1, 1, 15))
    db.set_created_at(s["id"], datetime(2024, 3, 1, 15))
    rows = preview(client, user, "date,action,symbol,quantity,price,currency\n2024-02-01,SELL,AAPL,5,110,CAD\n")["rows"]
    res = client.post("/transactions/import", headers=user.headers, json={"rows": rows})
    assert res.status_code == 409 and "existing AAPL sell on 2024-03-01" in res.json()["detail"]
    assert len(trades(client, user)) == 2


def test_import_limits_count_the_whole_batch(client, user, buy, monkeypatch):
    buy(user, "AAPL", 1, 100)
    rows = preview(client, user, "date,action,symbol,quantity,price,currency\n"
                                 "2024-01-01,BUY,MSFT,1,10,USD\n2024-01-01,BUY,NVDA,1,10,USD\n")["rows"]
    monkeypatch.setattr(import_routes, "MAX_SYMBOLS_PER_USER", 2)
    res = client.post("/transactions/import", headers=user.headers, json={"rows": rows})
    assert res.status_code == 422 and "different assets" in res.json()["detail"]

    monkeypatch.setattr(import_routes, "MAX_SYMBOLS_PER_USER", 200)
    monkeypatch.setattr(import_routes, "MAX_TRANSACTIONS_PER_USER", 2)
    res = client.post("/transactions/import", headers=user.headers, json={"rows": rows})
    assert res.status_code == 422 and "trades" in res.json()["detail"]
    assert len(trades(client, user)) == 1


def test_too_many_rows_in_one_commit(client, user, monkeypatch):
    rows = preview(client, user, ZENITH)["rows"]
    monkeypatch.setattr(import_routes, "MAX_ROWS", 2)
    res = client.post("/transactions/import", headers=user.headers, json={"rows": rows})
    assert res.status_code == 422 and "up to 2" in res.json()["detail"]


def test_preview_limits(client, user):
    res = client.post("/transactions/import/preview", headers=user.headers,
                      json={"csv": "date,action,symbol,quantity,price,currency\n" + "x" * (2 * 1024 * 1024 + 1)})
    assert res.status_code == 413 and "2 MB" in res.json()["detail"]
    res = client.post("/transactions/import/preview", headers=user.headers, json={"csv": "hello,world\n"})
    assert res.status_code == 422 and "recognise" in res.json()["detail"]
    res = client.post("/transactions/import/preview", headers=user.headers,
                      json={"csv": ZENITH, "default_account_type": "LIRA"})
    assert res.status_code == 422


def test_rate_limits(client, user, make_user):
    for _ in range(import_routes.IMPORT_RATE_LIMIT):
        preview(client, user, ZENITH)
    res = client.post("/transactions/import/preview", headers=user.headers, json={"csv": ZENITH})
    assert res.status_code == 429 and int(res.headers["retry-after"]) > 0
    preview(client, make_user(), ZENITH)  # per user

    rows = [dict(row) for row in preview(client, make_user(), ZENITH)["rows"]]
    for _ in range(import_routes.IMPORT_RATE_LIMIT):
        client.post("/transactions/import", headers=user.headers, json={"rows": []})
    res = client.post("/transactions/import", headers=user.headers, json={"rows": rows})
    assert res.status_code == 429


def test_other_users_data_is_never_touched(client, make_user, buy):
    owner, other = make_user(), make_user()
    buy(other, "AAPL", 3, 100)
    before = trades(client, other)
    commit(client, owner, preview(client, owner, ZENITH)["rows"])
    assert trades(client, other) == before
    assert "btc" not in export(client, other).text
    assert len(list(csv.reader(io.StringIO(export(client, owner).text)))) == 4


def test_template_previews_cleanly(client, user):
    res = client.get("/transactions/import/template", headers=user.headers)
    assert res.status_code == 200 and "zenith-import-template.csv" in res.headers["content-disposition"]
    header, *examples = list(csv.reader(io.StringIO(res.text)))
    assert header == importer.EXPORT_COLUMNS and len(examples) == 2
    assert preview(client, user, res.text)["summary"] == {"ok": 2, "duplicate": 0, "error": 0,
                                                          "skipped_non_trades": 0}


def test_broker_files_through_the_api(client, user):
    ws = preview(client, user, WEALTHSIMPLE, default_account_type="NON_REGISTERED")
    assert ws["format_detected"] == "wealthsimple"
    assert ws["summary"] == {"ok": 5, "duplicate": 0, "error": 0, "skipped_non_trades": 2}
    assert commit(client, user, ws["rows"]) == {"imported": 5}

    qt = preview(client, user, QUESTRADE, fmt="questrade")
    assert qt["summary"] == {"ok": 5, "duplicate": 0, "error": 0, "skipped_non_trades": 2}
    assert commit(client, user, qt["rows"]) == {"imported": 5}
    assert len(trades(client, user)) == 10
