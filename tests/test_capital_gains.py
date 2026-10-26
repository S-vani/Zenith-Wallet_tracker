"""
Canadian capital gains (ACB) report: the pure calculation (backend/services/reports.py) and the /reports routes.
"""
import csv
import io
import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.reports import (CRA_SUPERFICIAL_LOSS_URL, capital_gains, report_csv, safe_cell,
                                      security_keys, taxable_sale_years)

_ids = itertools.count()
NOW = datetime(2026, 6, 1)


def trade(action, qty, price, when, symbol="AAPL", account=None, asset_type="stock", api_id=None, coin_id=None,
          currency="CAD", tid=None):
    """One stored trade as the report sees it (price_of_one in CAD, naive UTC date)."""
    return SimpleNamespace(
        id=tid or f"t{next(_ids):05d}", action=action, quantity=qty, price_of_one=price, created_at=when,
        symbol=symbol, api_id=api_id or symbol, asset_type=asset_type, coin_id=coin_id, account_type=account,
        currency_entered=currency, price_entered=price)


def buy(*args, **kwargs):
    return trade("BUY", *args, **kwargs)


def sell(*args, **kwargs):
    return trade("SELL", *args, **kwargs)


def d(year, month, day, *time):
    """A stored (naive UTC) time; with no time given, midday in Toronto, so the Toronto date is the one written."""
    return datetime(year, month, day, *time) if time else datetime(year, month, day, 17)


def report(trades, year, now=NOW):
    return capital_gains(trades, year, now=now)


# ---------------------------------------------------------------------------------------------------------------------
# ACB maths
# ---------------------------------------------------------------------------------------------------------------------
def test_average_cost_carries_over_years_and_partial_sells():
    trades = [
        buy(10, 100, d(2023, 1, 5)),
        buy(10, 200, d(2023, 6, 5)),  # ACB 3000 for 20 -> 150 each
        sell(5, 300, d(2023, 9, 1)),  # ACB 750, proceeds 1500, gain 750; left 15 @ 150 = 2250
        buy(5, 50, d(2024, 2, 1)),  # 2500 for 20 -> 125 each
        sell(4, 100, d(2024, 3, 1)),  # ACB 500, proceeds 400, loss -100
        sell(16, 160, d(2024, 11, 1)),  # sells everything: ACB 2000, proceeds 2560, gain 560
    ]
    r2023 = report(trades, 2023)
    [only] = r2023["sales"]
    assert (only["proceeds"], only["acb"], only["gain"]) == (1500.0, 750.0, 750.0)

    r = report(trades, 2024)
    assert [(s["date"], s["quantity"], s["proceeds"], s["acb"], s["gain"]) for s in r["sales"]] == [
        ("2024-03-01", 4.0, 400.0, 500.0, -100.0),
        ("2024-11-01", 16.0, 2560.0, 2000.0, 560.0),
    ]
    # the March loss is possibly superficial (5 bought a month before, still held): flagged, still counted
    assert r["totals"] == {"proceeds": 2960.0, "acb": 2500.0, "net": 460.0, "gains": 560.0, "losses": -100.0,
                           "possibly_superficial": 100.0, "taxable_at_50pct": 230.0}
    assert r["currency"] == "CAD" and r["year"] == 2024
    assert all(s["outlays"] == 0 for s in r["sales"])  # commissions aren't stored


def test_fractional_quantities_are_exact():
    trades = [buy(0.1, 30000, d(2024, 1, 1), symbol="BTC", asset_type="crypto", api_id="btc"),
              buy(0.2, 60000, d(2024, 2, 1), symbol="BTC", asset_type="crypto", api_id="btc"),
              sell(0.3, 70000, d(2024, 3, 1), symbol="BTC", asset_type="crypto", api_id="btc")]
    [s] = report(trades, 2024)["sales"]
    assert (s["proceeds"], s["acb"], s["gain"], s["oversold"]) == (21000.0, 15000.0, 6000.0, False)


def test_securities_are_pooled_separately():
    trades = [buy(1, 100, d(2024, 1, 1), symbol="AAPL"), buy(1, 500, d(2024, 1, 1), symbol="MSFT"),
              sell(1, 150, d(2024, 2, 1), symbol="AAPL"), sell(1, 400, d(2024, 2, 1), symbol="MSFT")]
    sales = {s["symbol"]: s for s in report(trades, 2024)["sales"]}
    assert sales["AAPL"]["gain"] == 50.0 and sales["MSFT"]["gain"] == -100.0
    # a stock and a coin can share a ticker; they're different securities
    trades = [buy(1, 100, d(2024, 1, 1), symbol="BTC"), buy(1, 50000, d(2024, 1, 1), symbol="BTC",
                                                            asset_type="crypto", api_id="btc"),
              sell(1, 120, d(2024, 2, 1), symbol="BTC")]
    assert report(trades, 2024)["sales"][0]["acb"] == 100.0


def test_crypto_pools_by_coin_id_and_older_trades_join_the_only_coin():
    kw = dict(symbol="UNI", asset_type="crypto", api_id="uni")
    trades = [buy(1, 10, d(2024, 1, 1), coin_id="uniswap", **kw),
              buy(1, 1, d(2024, 1, 1), coin_id="other-uni", **kw),
              sell(1, 12, d(2024, 2, 1), coin_id="uniswap", **kw)]
    assert report(trades, 2024)["sales"][0]["acb"] == 10.0

    # no coin_id (logged before it was stored) + one coin with that ticker = the same security
    trades = [buy(1, 10, d(2024, 1, 1), **kw), sell(1, 12, d(2024, 2, 1), coin_id="uniswap", **kw)]
    keys = security_keys(trades)
    assert len(set(keys.values())) == 1
    [s] = report(trades, 2024)["sales"]
    assert s["acb"] == 10.0 and not s["oversold"]


def test_registered_accounts_are_excluded_and_unset_counts_as_taxable():
    trades = [
        buy(10, 100, d(2024, 1, 1), account="NON_REGISTERED"),
        buy(10, 10, d(2024, 1, 2), account="TFSA"),  # cheap TFSA buy must not lower the taxable ACB
        sell(10, 50, d(2024, 2, 1), account="TFSA"),
        sell(5, 120, d(2024, 3, 1), account=None),  # not set = taxable
        sell(5, 130, d(2024, 3, 2), account="NON_REGISTERED"),
    ]
    for account in ("RRSP", "FHSA", "RESP"):
        trades.append(buy(1, 1, d(2024, 1, 3), account=account))
        trades.append(sell(1, 1000, d(2024, 1, 4), account=account))
    r = report(trades, 2024)
    assert [(s["acb"], s["gain"]) for s in r["sales"]] == [(500.0, 100.0), (500.0, 150.0)]
    assert r["totals"]["net"] == 250.0


def test_same_tick_buy_replays_before_sell():
    when = d(2024, 5, 5, 12)
    trades = [sell(1, 150, when, tid="a"), buy(1, 100, when, tid="b")]  # the sell has the smaller id
    [s] = report(trades, 2024)["sales"]
    assert s["gain"] == 50.0 and not s["oversold"]


def test_year_filtering_and_years_list():
    # Dec 31 2021 (a Friday) settles T+2 business days later, after the Jan 3 New Year holiday: Jan 5, 2022
    trades = [buy(10, 100, d(2021, 1, 1)), sell(1, 110, d(2021, 12, 31, 23, 59)), sell(1, 120, d(2023, 1, 1)),
              sell(1, 10, d(2025, 6, 1), account="TFSA")]
    assert report(trades, 2021)["sales"] == []
    assert report(trades, 2021)["totals"]["net"] == 0
    [s] = report(trades, 2022)["sales"]
    assert (s["date"], s["settlement_date"]) == ("2021-12-31", "2022-01-05")
    assert taxable_sale_years(trades) == [2023, 2022]  # 2025 only has a TFSA sale
    assert taxable_sale_years([]) == []


def test_order_given_doesnt_matter():
    trades = [buy(2, 100, d(2024, 1, 1)), buy(2, 300, d(2024, 2, 1)), sell(2, 250, d(2024, 3, 1))]
    assert report(list(reversed(trades)), 2024) == report(trades, 2024)


def test_net_loss_has_nothing_taxable():
    trades = [buy(1, 100, d(2024, 1, 1)), sell(1, 40, d(2024, 2, 1))]
    t = report(trades, 2024)["totals"]
    assert t["net"] == -60.0 and t["losses"] == -60.0 and t["gains"] == 0 and t["taxable_at_50pct"] == 0


def test_rounding_to_cents_keeps_rows_and_totals_consistent():
    trades = [buy(3, 10, d(2024, 1, 1)), buy(3, 10.01, d(2024, 1, 2)), sell(1, 11, d(2024, 2, 1)),
              sell(1, 11, d(2024, 2, 2))]
    r = report(trades, 2024)
    for s in r["sales"]:
        assert round(s["proceeds"] - s["acb"], 2) == s["gain"]
        assert s["acb"] == 10.01  # 10.005 rounds half up
    assert r["totals"]["net"] == round(sum(s["gain"] for s in r["sales"]), 2)


# ---------------------------------------------------------------------------------------------------------------------
# Superficial loss
# ---------------------------------------------------------------------------------------------------------------------
LOSS_DAY = d(2024, 3, 1, 15)


def loss_trades(*extra):
    return [buy(10, 100, d(2023, 1, 1)), sell(10, 80, LOSS_DAY), *extra]


def flagged(trades):
    [s] = [s for s in report(trades, 2024)["sales"] if s["date"] == "2024-03-01"]
    return s


@pytest.mark.parametrize("days, expected", [(30, True), (31, False), (0, True)])
def test_buy_back_after_the_sale(days, expected):
    s = flagged(loss_trades(buy(1, 85, LOSS_DAY.replace(hour=20) + timedelta(days=days))))
    assert s["superficial_loss"] is expected
    if expected:
        assert any("superficial loss" in note for note in s["notes"])
        assert s["gain"] == -200.0  # flagged only, never adjusted


@pytest.mark.parametrize("days, expected", [(30, True), (31, False)])
def test_buy_before_the_sale(days, expected):
    # 06:00 UTC is 01:00 in Toronto: the same calendar day there
    trades = [buy(10, 100, d(2023, 1, 1)), buy(5, 90, LOSS_DAY.replace(hour=6) - timedelta(days=days)),
              sell(10, 80, LOSS_DAY)]  # still holds 5 at the end of the period
    s = flagged(trades)
    assert s["superficial_loss"] is expected


def test_buy_in_a_registered_account_counts():
    s = flagged(loss_trades(buy(1, 85, LOSS_DAY + timedelta(days=5), account="TFSA")))
    assert s["superficial_loss"] is True


def test_sold_out_by_the_end_of_the_period_is_not_superficial():
    s = flagged(loss_trades(buy(1, 85, LOSS_DAY + timedelta(days=5), account="RRSP"),
                            sell(1, 85, LOSS_DAY + timedelta(days=30), account="RRSP")))
    assert s["superficial_loss"] is False
    # sold one second into the day after the period ended (Toronto time): still held at the end of it
    s = flagged(loss_trades(buy(1, 85, LOSS_DAY + timedelta(days=5)),
                            sell(1, 85, d(2024, 4, 1, 4, 0, 1))))
    assert s["superficial_loss"] is True


def test_gains_are_never_superficial():
    trades = [buy(10, 100, d(2023, 1, 1)), sell(5, 120, LOSS_DAY), buy(1, 100, LOSS_DAY + timedelta(days=1))]
    s = flagged(trades)
    assert s["superficial_loss"] is False and s["notes"] == []


def test_other_security_doesnt_count():
    s = flagged(loss_trades(buy(1, 85, LOSS_DAY + timedelta(days=1), symbol="MSFT")))
    assert s["superficial_loss"] is False


def test_period_still_open():
    now = LOSS_DAY + timedelta(days=10)
    [s] = report(loss_trades(), 2024, now=now)["sales"]
    assert s["superficial_loss"] is False
    assert any("2024-03-31" in note for note in s["notes"])  # "if you buy it again by ..."

    [s] = report(loss_trades(buy(1, 85, LOSS_DAY + timedelta(days=2))), 2024, now=now)["sales"]
    assert s["superficial_loss"] is True
    assert any("end on 2024-03-31" in note for note in s["notes"])


# ---------------------------------------------------------------------------------------------------------------------
# Oversold (taxable history sells more than it holds)
# ---------------------------------------------------------------------------------------------------------------------
def test_oversold_sale_is_flagged_and_computed():
    trades = [buy(10, 100, d(2024, 1, 1), account="TFSA"), buy(2, 50, d(2024, 1, 2)),
              sell(5, 120, d(2024, 2, 1), account="NON_REGISTERED"),
              buy(1, 200, d(2024, 3, 1)), sell(1, 210, d(2024, 4, 1))]
    first, second = report(trades, 2024)["sales"]
    assert first["oversold"] is True
    assert (first["proceeds"], first["acb"], first["gain"]) == (600.0, 100.0, 500.0)
    assert any("Check the account types of earlier buys" in n and "3 more" in n for n in first["notes"])
    # the pool starts again from empty afterwards
    assert second["oversold"] is False and second["acb"] == 200.0 and second["gain"] == 10.0


def test_sell_with_nothing_held():
    [s] = report([sell(1, 10, d(2024, 1, 1))], 2024)["sales"]
    assert s["oversold"] is True and s["acb"] == 0 and s["gain"] == 10.0


def test_selling_a_hair_more_than_held_counts_as_selling_everything():
    trades = [buy(1, 100, d(2024, 1, 1)), sell(1.000000000000001, 120, d(2024, 2, 1))]
    [s] = report(trades, 2024)["sales"]
    assert s["oversold"] is False and s["acb"] == 100.0


# ---------------------------------------------------------------------------------------------------------------------
# Foreign currency and notes
# ---------------------------------------------------------------------------------------------------------------------
def test_foreign_currency_sales_are_surfaced():
    trades = [buy(1, 100, d(2024, 1, 1), currency="USD"), buy(1, 100, d(2024, 1, 2)),
              sell(1, 150, d(2024, 2, 1), currency="CAD"), sell(1, 150, d(2024, 2, 2), currency="EUR"),
              buy(1, 100, d(2024, 3, 1), symbol="SHOP.TO", currency=None),
              sell(1, 100, d(2024, 3, 2), symbol="SHOP.TO", currency=None)]
    cad_sale, eur_sale, shop = report(trades, 2024)["sales"]
    assert cad_sale["foreign_currency"] is True  # its ACB includes a USD buy
    assert any("USD" in n for n in cad_sale["notes"])
    assert eur_sale["currency_entered"] == "EUR" and any("Entered in EUR" in n for n in eur_sale["notes"])
    assert shop["foreign_currency"] is False and shop["notes"] == []


def test_report_notes_and_link():
    r = report([], 2024)
    text = " ".join(r["notes"])
    for phrase in ("Toronto", "settles", "May 28, 2024", "Commissions", "T5008", "Not tax advice", "spouse", "TFSA",
                   "open.er-api", "Yahoo Finance's daily closing rate"):
        assert phrase in text, phrase
    assert r["superficial_loss_url"] == CRA_SUPERFICIAL_LOSS_URL
    assert r["warnings"] == []
    assert r["totals"] == {"proceeds": 0, "acb": 0, "net": 0, "gains": 0, "losses": 0, "possibly_superficial": 0,
                           "taxable_at_50pct": 0}


# ---------------------------------------------------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [
    ("=HYPERLINK(\"x\")", "'=HYPERLINK(\"x\")"), ("+1+2", "'+1+2"), ("@SUM(A1)", "'@SUM(A1)"),
    ("-2+3", "'-2+3"), ("-12.50", "-12.50"), ("-3", "-3"), ("AAPL", "AAPL"), ("\tx", "'\tx"), (None, ""),
    (12.5, "12.5"),
])
def test_safe_cell(value, expected):
    assert safe_cell(value) == expected


def test_csv_rows_and_totals():
    trades = [buy(2, 100, d(2024, 1, 1), symbol="=CMD()"), sell(1, 90, d(2024, 2, 1), symbol="=CMD()"),
              buy(1, 10, d(2024, 1, 1), symbol="X"), sell(1, 30.5, d(2024, 2, 1), symbol="X")]
    rows = list(csv.reader(io.StringIO(report_csv(report(trades, 2024)))))
    assert rows[0][:9] == ["Trade date", "Settlement date", "Symbol", "Type", "Quantity", "Proceeds (CAD)",
                           "ACB (CAD)", "Outlays (CAD)", "Gain or loss (CAD)"]
    assert rows[1][:9] == ["2024-02-01", "2024-02-05", "'=CMD()", "stock", "1", "90.00", "100.00", "0.00", "-10.00"]
    assert rows[2][:9] == ["2024-02-01", "2024-02-05", "X", "stock", "1", "30.50", "10.00", "0.00", "20.50"]
    assert rows[3][0] == "Total 2024" and rows[3][5:9] == ["120.50", "110.00", "0.00", "10.50"]
    assert "Not tax advice" in rows[3][-1]
    assert len(rows) == 4


# ---------------------------------------------------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------------------------------------------------
def post(client, owner, expect=200, **overrides):
    body = {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
            "api_id": "AAPL"}
    body.update(overrides)
    res = client.post("/transactions", headers=owner.headers, json=body)
    assert res.status_code == expect, res.text
    return res.json()


def at(*args):
    return datetime(*args, tzinfo=timezone.utc).isoformat()


@pytest.fixture
def history(client, user):
    post(client, user, quantity=10, price_of_one=100, created_at=at(2023, 1, 1))
    post(client, user, action="SELL", quantity=4, price_of_one=150, created_at=at(2023, 6, 1),
         account_type="NON_REGISTERED")
    post(client, user, quantity=2, price_of_one=10, created_at=at(2024, 1, 1), account_type="TFSA")
    post(client, user, action="SELL", quantity=2, price_of_one=20, created_at=at(2024, 2, 1), account_type="TFSA")
    post(client, user, action="SELL", quantity=6, price_of_one=50, created_at=at(2025, 3, 1))
    return user


def test_years_endpoint(client, history):
    res = client.get("/reports/capital-gains/years", headers=history.headers)
    assert res.status_code == 200
    assert res.json() == {"years": [2025, 2023]}  # 2024 only has a TFSA sale


def test_report_endpoint(client, history):
    res = client.get("/reports/capital-gains", headers=history.headers, params={"year": 2025})
    assert res.status_code == 200, res.text
    body = res.json()
    [s] = body["sales"]
    assert (s["date"], s["symbol"], s["quantity"], s["proceeds"], s["acb"], s["gain"]) == \
           ("2025-02-28", "AAPL", 6.0, 300.0, 600.0, -300.0)
    # stored at midnight UTC on Mar 1: Feb 28 in Toronto (a Friday), settling Monday Mar 3
    assert s["settlement_date"] == "2025-03-03"
    assert s["superficial_loss"] is False and s["oversold"] is False and s["currency_entered"] == "CAD"
    assert body["totals"]["losses"] == -300.0 and body["totals"]["taxable_at_50pct"] == 0
    assert body["currency"] == "CAD" and body["notes"]


def test_report_is_in_cad_for_a_usd_user(client, make_user):
    usd = make_user(currency="USD")
    post(client, usd, quantity=1, price_of_one=70, created_at=at(2024, 1, 1))  # 70 USD = 100 CAD (0.7)
    post(client, usd, action="SELL", quantity=1, price_of_one=84, created_at=at(2024, 2, 1))  # 120 CAD
    [s] = client.get("/reports/capital-gains", headers=usd.headers, params={"year": 2024}).json()["sales"]
    assert (round(s["proceeds"], 2), round(s["acb"], 2), round(s["gain"], 2)) == (120.0, 100.0, 20.0)
    assert s["currency_entered"] == "USD" and s["foreign_currency"] is True


def test_csv_endpoint(client, history):
    res = client.get("/reports/capital-gains.csv", headers=history.headers, params={"year": 2023})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == 'attachment; filename="zenith-capital-gains-2023.csv"'
    assert res.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[1][:9] == ["2023-05-31", "2023-06-02", "AAPL", "stock", "4", "600.00", "400.00", "0.00", "200.00"]
    assert rows[-1][0] == "Total 2023"


@pytest.mark.parametrize("path", ["/reports/capital-gains", "/reports/capital-gains.csv"])
@pytest.mark.parametrize("year", ["1999", str(datetime.now(timezone.utc).year + 2), "abc", "", None])
def test_year_is_validated(client, user, path, year):
    params = {} if year is None else {"year": year}
    assert client.get(path, headers=user.headers, params=params).status_code == 422


def test_current_year_and_empty_years_are_fine(client, user):
    year = datetime.now(timezone.utc).year
    res = client.get("/reports/capital-gains", headers=user.headers, params={"year": year})
    assert res.status_code == 200 and res.json()["sales"] == []
    assert client.get("/reports/capital-gains", headers=user.headers, params={"year": 2000}).status_code == 200
    assert client.get("/reports/capital-gains/years", headers=user.headers).json() == {"years": []}


@pytest.mark.parametrize("path", ["/reports/capital-gains/years", "/reports/capital-gains?year=2024",
                                  "/reports/capital-gains.csv?year=2024"])
def test_requires_sign_in(client, path):
    assert client.get(path).status_code == 401


def test_users_only_see_their_own_sales(client, history, make_user):
    other = make_user()
    assert client.get("/reports/capital-gains/years", headers=other.headers).json() == {"years": []}
    assert client.get("/reports/capital-gains", headers=other.headers, params={"year": 2025}).json()["sales"] == []
    rows = list(csv.reader(io.StringIO(
        client.get("/reports/capital-gains.csv", headers=other.headers, params={"year": 2025}).text)))
    assert len(rows) == 2  # header + totals only


# ---------------------------------------------------------------------------------------------------------------------
# Settlement dates and Toronto dates (hand-computed)
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("when, asset_type, trade_day, settles", [
    # T+1 (trades from 2024-05-28): Tuesday Dec 31 2024 settles after the Jan 1 holiday, on Thursday Jan 2 2025
    (d(2024, 12, 31, 15), "stock", "2024-12-31", "2025-01-02"),
    (d(2024, 12, 30, 15), "stock", "2024-12-30", "2024-12-31"),  # Monday -> Tuesday, same year
    # T+2 (before 2024-05-28): Thursday Dec 28 2023 -> Friday 29, (Jan 1 holiday), Tuesday Jan 2 2024
    (d(2023, 12, 28, 15), "stock", "2023-12-28", "2024-01-02"),
    (d(2023, 12, 27, 15), "stock", "2023-12-27", "2023-12-29"),
    # Christmas on a Saturday (2021): Dec 27 and 28 are the holidays, so Thursday Dec 23 + 2 = Dec 24, Dec 29
    (d(2021, 12, 23, 15), "stock", "2021-12-23", "2021-12-29"),
    # the switch: Monday May 27 2024 (T+2) and Tuesday May 28 2024 (T+1) both settle on Wednesday May 29
    (d(2024, 5, 27, 15), "stock", "2024-05-27", "2024-05-29"),
    (d(2024, 5, 28, 15), "stock", "2024-05-28", "2024-05-29"),
    # 9:30 pm on Friday Dec 31 2021 in Toronto is stored as Jan 1 2022 02:30 UTC: a Dec 31 trade
    (d(2022, 1, 1, 2, 30), "crypto", "2021-12-31", "2021-12-31"),
    (d(2024, 12, 31, 15), "crypto", "2024-12-31", "2024-12-31"),  # crypto has no settlement cycle
])
def test_trade_and_settlement_dates(when, asset_type, trade_day, settles):
    kw = dict(symbol="BTC", api_id="btc", asset_type="crypto") if asset_type == "crypto" else {}
    trades = [buy(1, 100, d(2020, 6, 1), **kw), sell(1, 150, when, **kw)]
    year = int(settles[:4])
    [s] = report(trades, year)["sales"]
    assert (s["date"], s["settlement_date"]) == (trade_day, settles)
    assert taxable_sale_years(trades) == [year]


def test_a_stock_sold_on_the_last_trading_day_counts_next_year():
    trades = [buy(1, 100, d(2024, 1, 2)), sell(1, 150, d(2024, 12, 31, 15))]
    assert report(trades, 2024)["sales"] == []
    [s] = report(trades, 2025)["sales"]
    assert s["gain"] == 50.0
    # the same trade in crypto stays in 2024
    kw = dict(symbol="ETH", api_id="eth", asset_type="crypto")
    trades = [buy(1, 100, d(2024, 1, 2), **kw), sell(1, 150, d(2024, 12, 31, 15), **kw)]
    assert [s["gain"] for s in report(trades, 2024)["sales"]] == [50.0]


def test_evening_trades_keep_their_toronto_date():
    # 8 pm in Toronto on Dec 31 2023 is 01:00 UTC on Jan 1 2024: the crypto sale is a 2023 sale
    kw = dict(symbol="ETH", api_id="eth", asset_type="crypto")
    trades = [buy(1, 100, d(2023, 6, 1), **kw), sell(1, 120, d(2024, 1, 1, 1), **kw)]
    assert [s["date"] for s in report(trades, 2023)["sales"]] == ["2023-12-31"]
    assert report(trades, 2024)["sales"] == []


# ---------------------------------------------------------------------------------------------------------------------
# Superficial loss: CRA's least of (sold, bought in the window, held at its end), hand-computed
# ---------------------------------------------------------------------------------------------------------------------
def test_an_old_holding_outside_the_window_alone_is_not_superficial():
    # 100 in a TFSA since 2022, nothing bought around the sale: held at the end is 100 but bought in the window 0
    trades = [buy(100, 50, d(2022, 1, 1), account="TFSA"), *loss_trades()]
    s = flagged(trades)
    assert s["superficial_loss"] is False and s["superficial_amount"] == 0


def test_only_part_of_the_loss_is_superficial():
    # sold 10 at a loss of 20 each (-200); bought back 4 within 30 days and still held them: 4/10 of the loss
    s = flagged(loss_trades(buy(4, 85, LOSS_DAY + timedelta(days=10))))
    assert s["superficial_loss"] is True and s["gain"] == -200.0  # flagged, not adjusted
    assert s["superficial_amount"] == 80.0
    assert any("CRA may deny all or part of this loss" in n and "4 of the 10 units sold" in n and "$80.00" in n
               for n in s["notes"])


def test_the_units_held_at_the_end_limit_the_superficial_part():
    # bought back 6, sold 4 of them again before the window ended: least of (10, 6, 2) = 2 -> 2/10 of 200 = 40
    s = flagged(loss_trades(buy(6, 85, LOSS_DAY + timedelta(days=5)), sell(4, 86, LOSS_DAY + timedelta(days=20))))
    assert s["superficial_loss"] is True and s["superficial_amount"] == 40.0


def test_bought_back_more_than_sold_is_the_whole_loss():
    s = flagged(loss_trades(buy(25, 85, LOSS_DAY + timedelta(days=3))))
    assert s["superficial_amount"] == 200.0
    assert any("all of this loss" in n for n in s["notes"])


def test_registered_repurchase_wording():
    s = flagged(loss_trades(buy(10, 85, LOSS_DAY + timedelta(days=5), account="TFSA")))
    text = " ".join(s["notes"])
    assert "lost for good" in text and "isn't added to any ACB" in text
    assert "added to the ACB of the shares bought back in your non-registered" not in text

    s = flagged(loss_trades(buy(10, 85, LOSS_DAY + timedelta(days=5))))
    text = " ".join(s["notes"])
    assert "added to the ACB of the shares bought back in your non-registered account" in text
    assert "lost for good" not in text


def test_a_later_sale_of_the_repurchased_shares_says_its_acb_may_rise():
    trades = loss_trades(buy(4, 85, LOSS_DAY + timedelta(days=10)), sell(4, 90, d(2024, 9, 3)),
                         buy(1, 1, d(2024, 1, 2), symbol="MSFT"), sell(1, 1, d(2024, 9, 3), symbol="MSFT"))
    sales = {s["symbol"]: s for s in report(trades, 2024)["sales"] if s["date"] == "2024-09-03"}
    assert sales["AAPL"]["acb_may_rise"] is True
    assert any("Its ACB may be too low" in n and "2024-03-01" in n and "$80.00" in n
               for n in sales["AAPL"]["notes"])
    assert sales["MSFT"]["acb_may_rise"] is False  # another security


def test_a_registered_repurchase_never_raises_a_later_acb():
    trades = loss_trades(buy(4, 85, LOSS_DAY + timedelta(days=10), account="TFSA"), buy(4, 90, d(2024, 8, 1)),
                         sell(4, 95, d(2024, 9, 3)))
    later = [s for s in report(trades, 2024)["sales"] if s["date"] == "2024-09-03"][0]
    assert later["acb_may_rise"] is False


def test_a_sale_before_the_repurchase_has_no_acb_note():
    # flagged loss, a gain sale of other shares, and only then the repurchase: that middle sale isn't affected
    trades = [buy(20, 100, d(2023, 1, 1)), sell(10, 80, LOSS_DAY), sell(5, 120, LOSS_DAY + timedelta(days=2)),
              buy(5, 85, LOSS_DAY + timedelta(days=10)), sell(10, 90, d(2024, 9, 3))]
    middle, last = [s for s in report(trades, 2024)["sales"] if s["date"] != "2024-03-01"]
    assert middle["acb_may_rise"] is False
    assert last["acb_may_rise"] is True


def test_losses_total_says_how_much_is_possibly_superficial():
    trades = loss_trades(buy(4, 85, LOSS_DAY + timedelta(days=10)), buy(1, 10, d(2023, 1, 1), symbol="X"),
                         sell(1, 5, d(2024, 6, 3), symbol="X"))
    r = report(trades, 2024)
    assert r["totals"]["losses"] == -205.0
    assert r["totals"]["possibly_superficial"] == 80.0  # still included in the losses, only flagged
    rows = list(csv.reader(io.StringIO(report_csv(r))))
    assert "includes up to 80.00 of possibly superficial losses" in rows[-1][-1]
    flagged_row = next(row for row in rows[1:-1] if row[10] == "Yes")
    assert flagged_row[11] == "80.00"


# ---------------------------------------------------------------------------------------------------------------------
# Interlisted shares
# ---------------------------------------------------------------------------------------------------------------------
def test_interlisted_shares_are_warned_about():
    trades = [buy(1, 100, d(2024, 1, 2), symbol="SHOP"), buy(1, 140, d(2024, 1, 3), symbol="SHOP.TO"),
              sell(1, 150, d(2024, 3, 4), symbol="SHOP.TO"), buy(1, 50, d(2024, 1, 2), symbol="AAPL"),
              sell(1, 60, d(2024, 3, 4), symbol="AAPL")]
    r = report(trades, 2024)
    [warning] = r["warnings"]
    assert warning.startswith("SHOP and SHOP.TO") and "identical property" in warning
    sales = {s["symbol"]: s for s in r["sales"]}
    assert sales["SHOP.TO"]["interlisted"] is True and sales["AAPL"]["interlisted"] is False
    assert any("Also traded as SHOP" in n for n in sales["SHOP.TO"]["notes"])
    rows = list(csv.reader(io.StringIO(report_csv(r))))
    assert "SHOP and SHOP.TO" in rows[-1][-1]


def test_interlisted_only_counts_taxable_trades_of_both_listings():
    trades = [buy(1, 100, d(2024, 1, 2), symbol="RY", account="TFSA"), buy(1, 140, d(2024, 1, 3), symbol="RY.TO"),
              sell(1, 150, d(2024, 3, 4), symbol="RY.TO"), buy(1, 10, d(2024, 1, 2), symbol="BB.V"),
              buy(1, 10, d(2024, 1, 2), symbol="BB")]
    assert report(trades, 2024)["warnings"] == []


def test_report_endpoint_has_the_new_fields(client, user):
    post(client, user, symbol="SHOP", api_id="SHOP", created_at=at(2024, 1, 2, 15))
    post(client, user, symbol="SHOP.TO", api_id="SHOP.TO", created_at=at(2024, 1, 2, 15))
    post(client, user, symbol="SHOP.TO", api_id="SHOP.TO", action="SELL", created_at=at(2024, 12, 31, 15))
    assert client.get("/reports/capital-gains/years", headers=user.headers).json() == {"years": [2025]}
    body = client.get("/reports/capital-gains", headers=user.headers, params={"year": 2025}).json()
    [s] = body["sales"]
    assert (s["date"], s["settlement_date"], s["interlisted"]) == ("2024-12-31", "2025-01-02", True)
    assert len(body["warnings"]) == 1 and body["totals"]["possibly_superficial"] == 0
