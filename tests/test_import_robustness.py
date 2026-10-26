"""
CSV import edge cases: cells that used to crash the preview, duplicate matching speed and time zones, same-day
ordering, oversells shown in the preview, TSX listings for Wealthsimple rows, asset types, number and date formats,
symbols an export writes, and retries of an import (import id, duplicates checked again).
"""
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import backend.routes.imports as import_routes
import backend.services.imports as importer
from backend.services.imports import ImportRow, mark_duplicates, parse_csv, parse_number, parse_trade_date


@pytest.fixture(autouse=True)
def fresh_import_state(monkeypatch):
    monkeypatch.setattr(import_routes, "_preview_times", {})
    monkeypatch.setattr(import_routes, "_import_times", {})
    monkeypatch.setattr(import_routes, "_commit_attempts", {})
    monkeypatch.setattr(import_routes, "_finished_imports", {})
    monkeypatch.setattr(importer, "_tsx_cache", {})


def preview(client, owner, text, fmt="auto", expect=200):
    res = client.post("/transactions/import/preview", headers=owner.headers, json={"csv": text, "format": fmt})
    assert res.status_code == expect, res.text
    return res.json()


def commit(client, owner, rows, expect=200, **extra):
    res = client.post("/transactions/import", headers=owner.headers, json={"rows": rows, **extra})
    assert res.status_code == expect, res.text
    return res.json()


def trades(client, owner):
    return client.get("/transactions", headers=owner.headers).json()


HEADER = "date,action,asset_type,symbol,quantity,price,currency\n"
WS_HEADER = ("transaction_date,account_type,activity_type,activity_sub_type,symbol,currency,quantity,unit_price,"
             "net_cash_amount\n")


# ---------------------------------------------------------------------------------------------------------------------
# 1. One bad cell is a row error, never a 500
# ---------------------------------------------------------------------------------------------------------------------
BAD_CELLS = (HEADER
             + "2024-01-02,BUY,stock,AAPL,1e20,10,USD\n"
             + "2024-02-30 10:00:00 AM,BUY,stock,AAPL,1,10,USD\n"
             + "2024-01-01 10:99:00 AM,BUY,stock,AAPL,1,10,USD\n"
             + "0001-01-01T00:00:00+05:00,BUY,stock,AAPL,1,10,USD\n"
             + "2024-01-01 13:00:00 PM,BUY,stock,AAPL,1,10,USD\n"
             + "2024-01-02,BUY,stock,AAPL,1,1e999999999,USD\n"
             + "2024-01-02,BUY,stock,AAPL,1,10,USD\n")


def test_bad_cells_are_row_errors():
    rows = parse_csv(BAD_CELLS).rows
    assert [row.status for row in rows] == ["error"] * 6 + ["ok"]
    assert "too large" in rows[0].notes[0]
    assert all("date" in row.notes[0].lower() for row in rows[1:5])
    assert "too large" in rows[5].notes[0]


def test_net_amount_that_overflows_is_a_row_error():
    text = WS_HEADER + "2024-01-02,TFSA,Trade,BUY,XEQT.TO,CAD,1e-999990,,-1e999990\n"
    text += "2024-01-02,TFSA,Trade,BUY,XEQT.TO,CAD,1e-30,,-1e30\n"
    first, second = parse_csv(text).rows
    assert first.status == second.status == "error"


@pytest.mark.parametrize("value", ["2024-02-30 10:00:00 AM", "2024-01-01 10:99:00 AM", "0001-01-01T00:00:00+05:00",
                                   "9999-12-31T23:59:59-05:00", "2024-13-01T00:00:00"])
def test_dates_only_raise_row_errors(value):
    with pytest.raises(importer.RowError):
        parse_trade_date(value)


def test_bad_cells_through_the_api(client, user):
    result = preview(client, user, BAD_CELLS)
    assert result["summary"]["error"] == 6 and result["summary"]["ok"] == 1
    row = {"line": 2, "date": "2024-01-02", "action": "BUY", "asset_type": "stock", "symbol": "AAPL",
           "quantity": "1e20", "price": 10, "currency": "USD"}
    for change in ({}, {"quantity": "1", "date": "0001-01-01T00:00:00+05:00"}, {"quantity": "1", "price": "1e999999"}):
        res = client.post("/transactions/import", headers=user.headers, json={"rows": [dict(row, **change)]})
        assert res.status_code == 422, (change, res.text)
    assert trades(client, user) == []


# ---------------------------------------------------------------------------------------------------------------------
# 2. Duplicates are indexed, and the heavy work runs off the event loop
# ---------------------------------------------------------------------------------------------------------------------
def test_duplicate_check_is_fast_with_many_saved_trades():
    start = datetime(2020, 1, 1, 15)
    existing = [SimpleNamespace(id=i, symbol=f"S{i % 50}", action="BUY", created_at=start + timedelta(hours=i),
                                quantity=1.0, price_of_one=10.0, price_entered=10.0, currency_entered="CAD")
                for i in range(20_000)]
    rows = []
    for i in range(1000):
        row = ImportRow(line=i + 2, date=start + timedelta(hours=i * 7), action="BUY", symbol=f"S{(i * 7) % 50}",
                        quantity=Decimal(1), price=Decimal(10), currency="CAD")
        rows.append(row)
    began = time.perf_counter()
    mark_duplicates(rows, existing, None)
    assert time.perf_counter() - began < 1.5  # was ~12 s before the index
    assert all(row.status == "duplicate" for row in rows)


def test_preview_and_import_parse_in_a_worker_thread(client, user, monkeypatch):
    seen = []
    real_parse, real_clean = import_routes.parse_csv, import_routes._clean_commit_rows

    def parse(*args, **kwargs):
        seen.append(threading.current_thread())
        return real_parse(*args, **kwargs)

    def clean(*args, **kwargs):
        seen.append(threading.current_thread())
        return real_clean(*args, **kwargs)
    monkeypatch.setattr(import_routes, "parse_csv", parse)
    monkeypatch.setattr(import_routes, "_clean_commit_rows", clean)
    rows = preview(client, user, HEADER + "2024-01-02,BUY,stock,AAPL,1,10,USD\n")["rows"]
    commit(client, user, rows)
    loop_thread = client.portal.call(threading.current_thread)  # the thread the event loop runs on
    assert len(seen) == 2 and all(thread is not loop_thread for thread in seen)


# ---------------------------------------------------------------------------------------------------------------------
# 3. A day-only row matches a trade logged that evening in Canada (the next day in UTC)
# ---------------------------------------------------------------------------------------------------------------------
QUESTRADE_HEADER = ("Transaction Date,Settlement Date,Action,Symbol,Description,Quantity,Price,Gross Amount,"
                    "Commission,Net Amount,Currency,Account #,Activity Type,Account Type\n")


def test_evening_trade_in_toronto_is_a_duplicate(client, user, db, buy):
    tx = buy(user, "SHOP.TO", 10, 100)
    db.set_created_at(tx["id"], datetime(2024, 1, 15, 2, 0))  # 9 pm on Jan 14 in Toronto
    text = QUESTRADE_HEADER + ("2024-01-14 12:00:00 AM,2024-01-16 12:00:00 AM,Buy,SHOP.TO,SHOPIFY,10,100,-1000,0,"
                               "-1000,CAD,1,Trades,Individual TFSA\n"
                               "2024-01-12 12:00:00 AM,2024-01-16 12:00:00 AM,Buy,SHOP.TO,SHOPIFY,10,100,-1000,0,"
                               "-1000,CAD,1,Trades,Individual TFSA\n")
    statuses = [row["status"] for row in preview(client, user, text)["rows"]]
    assert statuses == ["duplicate", "ok"]  # two days earlier isn't the same trade


# ---------------------------------------------------------------------------------------------------------------------
# 4. A day-only sell on the day of a hand-logged buy goes after it
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bought_at", [datetime(2024, 3, 5, 15, 0), datetime(2024, 3, 5, 22, 30)])
def test_same_day_buy_then_file_sell(client, user, db, buy, bought_at):
    tx = buy(user, "RY.TO", 10, 130)
    db.set_created_at(tx["id"], bought_at)
    result = preview(client, user, HEADER + "2024-03-05,SELL,stock,RY.TO,10,135,CAD\n")
    [row] = result["rows"]
    assert row["status"] == "ok", row["message"]
    assert datetime.fromisoformat(row["date"]).replace(tzinfo=None) > bought_at
    assert row["date"].startswith("2024-03-05")
    assert commit(client, user, result["rows"])["imported"] == 1


# ---------------------------------------------------------------------------------------------------------------------
# 5. The preview replays the ledger: an oversell is a problem row, not "Ready"
# ---------------------------------------------------------------------------------------------------------------------
def test_preview_marks_an_oversell(client, user):
    text = HEADER + "2024-01-02,BUY,stock,MSFT,3,100,USD\n2024-01-03,SELL,stock,MSFT,50,120,USD\n"
    result = preview(client, user, text)
    bought, sold = result["rows"]
    assert bought["status"] == "ok"
    assert sold["status"] == "error" and "sells 50 MSFT" in sold["message"] and "only own 3" in sold["message"]
    assert result["summary"]["error"] == 1
    # what the preview says is ready imports
    assert commit(client, user, [r for r in result["rows"] if r["status"] == "ok"])["imported"] == 1


def test_preview_counts_saved_trades_and_marks_a_sell_that_leaves_a_saved_one_short(client, user, db, buy, sell):
    b = buy(user, "AAPL", 10, 100)
    s = sell(user, "AAPL", 10, 120)
    db.set_created_at(b["id"], datetime(2024, 1, 1, 15))
    db.set_created_at(s["id"], datetime(2024, 3, 1, 15))
    text = HEADER + "2024-02-01,SELL,stock,AAPL,5,110,CAD\n2024-04-01,BUY,stock,AAPL,1,110,CAD\n"
    sold, bought = preview(client, user, text)["rows"]
    assert sold["status"] == "error" and "saved AAPL sell on 2024-03-01" in sold["message"]
    assert bought["status"] == "ok"
    # a sell covered by saved buys is fine
    later = preview(client, user, HEADER + "2024-02-01,SELL,stock,AAPL,1,110,CAD\n")["rows"]
    assert later[0]["status"] == "error"  # still leaves the saved March sell short
    ok = preview(client, user, HEADER + "2024-04-01,BUY,stock,AAPL,2,110,CAD\n2024-04-02,SELL,stock,AAPL,2,110,CAD\n")
    assert [row["status"] for row in ok["rows"]] == ["ok", "ok"]


def test_oversell_with_buys_and_sells_in_order():
    text = (HEADER + "2024-01-01,BUY,stock,X,5,1,USD\n2024-01-02,SELL,stock,X,3,1,USD\n"
            "2024-01-03,SELL,stock,X,3,1,USD\n2024-01-04,SELL,stock,X,2,1,USD\n")
    rows = parse_csv(text).rows
    importer.check_against_saved(rows, [], None)
    assert [row.status for row in rows] == ["ok", "ok", "error", "ok"]


# ---------------------------------------------------------------------------------------------------------------------
# 6. Wealthsimple CAD rows without an exchange are TSX listings when Yahoo knows them
# ---------------------------------------------------------------------------------------------------------------------
def test_wealthsimple_cad_rows_find_their_tsx_listing(client, user, market):
    market.prices.update({"XEQT.TO": 30.0, "T.TO": 20.0, "L.TO": 150.0})
    text = WS_HEADER + ("2024-01-02,TFSA,Trade,BUY,XEQT,CAD,10,30,-300\n"
                        "2024-01-02,TFSA,Trade,BUY,T,CAD,10,20,-200\n"
                        "2024-01-02,TFSA,Trade,BUY,L,CAD,1,150,-150\n"
                        "2024-01-02,TFSA,Trade,BUY,ZZZZ,CAD,1,10,-10\n"
                        "2024-01-02,TFSA,Trade,BUY,T,USD,1,15,-15\n")
    rows = preview(client, user, text)["rows"]
    assert [row["symbol"] for row in rows] == ["XEQT.TO", "T.TO", "L.TO", "ZZZZ", "T"]
    assert "TSX listing XEQT.TO" in rows[0]["message"]
    assert ".TO (TSX)" in rows[3]["message"]  # unknown on the TSX: the note stays
    assert rows[4]["message"] is None  # a USD row is the US listing
    # answers are cached: a second preview asks Yahoo nothing new
    asked = len(market.requested)
    preview(client, user, text)
    assert len(market.requested) == asked


def test_converted_wealthsimple_rows_stay_us_listings(client, user, market):
    market.prices["AAPL.TO"] = 30.0
    text = ("transaction_date,account_type,activity_type,activity_sub_type,description,symbol,currency,quantity,"
            "unit_price,net_cash_amount\n"
            "2024-01-02,TFSA,Trade,BUY,\"Bought, FX Rate: 1.38\",AAPL,CAD,1,250,-250\n")
    [row] = preview(client, user, text)["rows"]
    assert row["symbol"] == "AAPL"


def test_tsx_lookup_failure_keeps_the_note(client, user, monkeypatch):
    async def broken(symbols):
        raise RuntimeError("Yahoo is down")
    monkeypatch.setattr(importer.asset_services, "get_latest_stock_quotes", broken)
    [row] = preview(client, user, WS_HEADER + "2024-01-02,TFSA,Trade,BUY,XEQT,CAD,10,30,-300\n")["rows"]
    assert row["symbol"] == "XEQT" and ".TO (TSX)" in row["message"] and row["status"] == "ok"


# ---------------------------------------------------------------------------------------------------------------------
# 7. Asset types and the currency of a price worked out from the net amount
# ---------------------------------------------------------------------------------------------------------------------
def test_zenith_rows_without_an_asset_type():
    text = ("date,action,symbol,quantity,price,currency,coin_id\n"
            "2024-01-02,BUY,BTC,0.1,50000,CAD,\n"
            "2024-01-02,BUY,eth,1,3000,CAD,ethereum\n"
            "2024-01-02,BUY,MSFT,1,300,USD,\n")
    btc, eth, msft = parse_csv(text).rows
    assert btc.status == "error" and "asset_type" in btc.notes[0]
    assert (eth.status, eth.asset_type, eth.symbol, eth.coin_id) == ("ok", "crypto", "eth", "ethereum")
    assert (msft.status, msft.asset_type) == ("ok", "stock")


def test_wealthsimple_crypto_outside_a_crypto_account():
    text = WS_HEADER + ("2024-01-02,Personal,Trade,BUY,BTC,CAD,0.01,60000,-600\n"
                        "2024-01-02,Non-registered,CRYPTO_BUY,,SOL,CAD,1,200,-200\n"
                        "2024-01-02,TFSA,Trade,CRYPTO_SELL,ETH,CAD,0.1,3000,300\n"
                        "2024-01-02,Personal,Trade,BUY,DASH,USD,1,100,-100\n")
    btc, sol, eth, dash = parse_csv(text).rows
    assert (btc.asset_type, btc.symbol) == ("crypto", "btc")
    assert (sol.asset_type, sol.action) == ("crypto", "BUY")
    assert (eth.asset_type, eth.action) == ("crypto", "SELL")
    assert (dash.asset_type, dash.symbol) == ("stock", "DASH")  # DoorDash, in USD


def test_net_amount_in_another_currency_needs_a_unit_price():
    text = ("transaction_date,account_type,activity_type,activity_sub_type,description,symbol,currency,quantity,"
            "unit_price,net_cash_amount,net_cash_currency\n"
            "2024-01-02,TFSA,Trade,BUY,,AAPL,USD,2,,-500,CAD\n"
            "2024-01-02,TFSA,Trade,BUY,\"Bought, FX Rate: 1.38\",AAPL,USD,2,,-500,\n"
            "2024-01-02,TFSA,Trade,BUY,\"Bought, FX Rate: 1.38\",AAPL,CAD,2,,-500,\n"
            "2024-01-02,TFSA,Trade,BUY,,AAPL,USD,2,,-300,USD\n")
    other, converted_usd, converted_cad, same = parse_csv(text).rows
    assert other.status == converted_usd.status == "error" and "unit price" in other.notes[0]
    assert converted_cad.status == "ok" and converted_cad.price == Decimal(250)  # CAD cash for a CAD row
    assert same.status == "ok" and same.price == Decimal(150)


# ---------------------------------------------------------------------------------------------------------------------
# 8. Numbers and dates as spreadsheets re-save them
# ---------------------------------------------------------------------------------------------------------------------
def test_excel_resaved_questrade_dates():
    for text in ("2024-01-09 00:00:00", "2024-01-09 0:00", "2024-01-09T00:00"):
        assert parse_trade_date(text) == (datetime(2024, 1, 9, 21), True), text
    assert parse_trade_date("2024-01-09 9:30") == (datetime(2024, 1, 9, 9, 30), False)
    # an offset makes midnight a real time
    assert parse_trade_date("2024-01-09T00:00:00+00:00") == (datetime(2024, 1, 9), False)


def test_ambiguous_slash_dates_follow_the_file():
    body = "date,action,symbol,quantity,price,currency\n{},BUY,AAPL,1,10,USD\n{},BUY,AAPL,1,10,USD\n"
    month_first = parse_csv(body.format("1/9/2024 0:00", "1/25/2024 0:00")).rows
    assert month_first[0].date == datetime(2024, 1, 9, 21) and month_first[0].date_only
    day_first = parse_csv(body.format("1/9/2024 0:00", "25/1/2024 0:00")).rows
    assert day_first[0].date == datetime(2024, 9, 1, 21)
    unknown = parse_csv(body.format("1/9/2024", "2/3/2024")).rows
    assert all(row.status == "error" and "two ways" in row.notes[0] for row in unknown)


def test_number_separators():
    assert parse_number("0,500", "x") == Decimal("0.500")  # not five hundred
    assert parse_number("1,500", "x") == Decimal("1500")
    assert parse_number("1 234,50", "x", decimal_comma=True) == Decimal("1234.50")
    assert parse_number("1 234.50", "x") == Decimal("1234.50")
    assert parse_number("12 345", "x") == Decimal("12345")
    # semicolon files: a single ".ddd" group is ambiguous, the rest isn't
    with pytest.raises(importer.RowError, match="could mean"):
        parse_number("1.234", "Quantity", decimal_comma=True)
    assert parse_number("1.234.567", "x", decimal_comma=True) == Decimal("1234567")
    assert parse_number("1.234.567,5", "x", decimal_comma=True) == Decimal("1234567.5")
    assert parse_number("0.123", "x", decimal_comma=True) == Decimal("0.123")
    assert parse_number("1.5", "x", decimal_comma=True) == Decimal("1.5")
    assert parse_number("1.234", "x") == Decimal("1.234")  # comma files: a decimal point


# ---------------------------------------------------------------------------------------------------------------------
# 9. Every symbol a manual trade accepts reads back in, formulas still don't
# ---------------------------------------------------------------------------------------------------------------------
def test_export_round_trip_with_unusual_symbols(client, make_user):
    source = make_user()
    for symbol, asset_type in (("usd+", "crypto"), ("BRK-B", "stock"), ("btc.b", "crypto")):
        res = client.post("/transactions", headers=source.headers, json={
            "symbol": symbol, "api_id": symbol, "asset_type": asset_type, "action": "BUY", "price_of_one": 1,
            "quantity": 2})
        assert res.status_code == 200, res.text
    text = client.get("/transactions/export", headers=source.headers).text
    target = make_user()
    result = preview(client, target, text)
    assert result["summary"]["ok"] == 3, result["rows"]
    assert commit(client, target, result["rows"])["imported"] == 3
    assert sorted(t["symbol"] for t in trades(client, target)) == ["BRK-B", "btc.b", "usd+"]


@pytest.mark.parametrize("symbol", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", " ", "A\tB", "X" * 33])
def test_formula_and_odd_symbols_are_refused(symbol):
    rows = parse_csv(HEADER + f"2024-01-02,BUY,stock,\"{symbol}\",1,10,USD\n").rows
    assert rows[0].status == "error"


# ---------------------------------------------------------------------------------------------------------------------
# 11. A retried import never imports twice
# ---------------------------------------------------------------------------------------------------------------------
def test_import_id_makes_a_retry_return_the_first_answer(client, user, make_user):
    rows = preview(client, user, HEADER + "2024-01-02,BUY,stock,AAPL,1,10,USD\n2024-01-03,BUY,stock,MSFT,2,10,USD\n")
    rows = rows["rows"]
    import_id = str(uuid.uuid4())
    first = commit(client, user, rows, import_id=import_id)
    again = commit(client, user, rows, import_id=import_id)
    assert first == again == {"imported": 2, "skipped_duplicates": 0}
    assert len(trades(client, user)) == 2
    # a new id is a new import, and the duplicate check still stops it adding anything
    assert commit(client, user, rows, import_id=str(uuid.uuid4())) == {"imported": 0, "skipped_duplicates": 2}
    # ids are per user: someone else's import with the same id is their own
    other = make_user()
    assert commit(client, other, rows[:1], import_id=import_id) == {"imported": 1, "skipped_duplicates": 0}
    assert len(trades(client, other)) == 1


def test_commit_checks_duplicates_again(client, user):
    text = HEADER + "2024-01-02,BUY,stock,AAPL,1,10,USD\n2024-01-02,BUY,stock,AAPL,1,10,USD\n"
    rows = preview(client, user, text)["rows"]
    assert commit(client, user, rows) == {"imported": 2, "skipped_duplicates": 0}
    # the same rows again (an old app's retry): nothing new
    assert commit(client, user, rows) == {"imported": 0, "skipped_duplicates": 2}
    # a duplicate the user ticked is imported
    again = preview(client, user, text)["rows"]
    assert [row["status"] for row in again] == ["duplicate", "duplicate"]
    ticked = [dict(again[0], include_duplicate=True), again[1]]
    assert commit(client, user, ticked) == {"imported": 1, "skipped_duplicates": 1}
    assert len(trades(client, user)) == 3


def test_failed_import_with_an_id_can_be_retried(client, user):
    rows = [{"line": 2, "date": "2024-01-02", "action": "SELL", "asset_type": "stock", "symbol": "NVDA",
             "quantity": 1, "price": 10, "currency": "USD"}]
    import_id = str(uuid.uuid4())
    commit(client, user, rows, expect=409, import_id=import_id)
    fixed = [dict(rows[0], action="BUY")]
    assert commit(client, user, fixed, import_id=import_id)["imported"] == 1


# ---------------------------------------------------------------------------------------------------------------------
# 12. The commit only needs the trade's own fields
# ---------------------------------------------------------------------------------------------------------------------
def test_commit_accepts_the_minimal_rows_the_page_sends(client, user):
    [row] = preview(client, user, HEADER + "2024-01-02,BUY,stock,AAPL,1,10,USD\n")["rows"]
    minimal = {key: row[key] for key in ("line", "date", "date_only", "action", "asset_type", "symbol", "quantity",
                                         "price", "currency", "account_type", "coin_id")}
    assert commit(client, user, [minimal])["imported"] == 1
    saved = trades(client, user)[0]
    assert saved["created_at"].startswith("2024-01-02T21:00")


def test_today_as_a_day_is_never_in_the_future():
    # "now" is pinned: reading the clock in the test and again inside parse_trade_date made the second reading a few
    # microseconds later, so this failed now and then (it did in CI)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    moment, date_only = parse_trade_date(now.date().isoformat(), now=now)
    assert date_only and moment <= now

    # without a pinned clock the result is still never later than a reading taken after the call
    moment, _ = parse_trade_date(now.date().isoformat())
    assert moment <= datetime.now(timezone.utc).replace(tzinfo=None)
