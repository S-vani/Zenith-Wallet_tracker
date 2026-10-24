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


def d(*args):
    return datetime(*args)


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
    assert r["totals"] == {"proceeds": 2960.0, "acb": 2500.0, "net": 460.0, "gains": 560.0, "losses": -100.0,
                           "taxable_at_50pct": 230.0}
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
    trades = [buy(10, 100, d(2021, 1, 1)), sell(1, 110, d(2021, 12, 31, 23, 59)), sell(1, 120, d(2023, 1, 1)),
              sell(1, 10, d(2025, 6, 1), account="TFSA")]
    assert [s["date"] for s in report(trades, 2021)["sales"]] == ["2021-12-31"]
    assert report(trades, 2022)["sales"] == []
    assert report(trades, 2022)["totals"]["net"] == 0
    assert taxable_sale_years(trades) == [2023, 2021]  # 2025 only has a TFSA sale
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
    trades = [buy(10, 100, d(2023, 1, 1)), buy(5, 90, LOSS_DAY.replace(hour=1) - timedelta(days=days)),
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
    # sold one day after the period ended: still held at the end of it
    s = flagged(loss_trades(buy(1, 85, LOSS_DAY + timedelta(days=5)),
                            sell(1, 85, d(2024, 4, 1, 0, 0, 1))))
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
    for phrase in ("UTC", "Commissions", "T5008", "Not tax advice", "spouse", "TFSA"):
        assert phrase in text
    assert r["superficial_loss_url"] == CRA_SUPERFICIAL_LOSS_URL
    assert r["totals"] == {"proceeds": 0, "acb": 0, "net": 0, "gains": 0, "losses": 0, "taxable_at_50pct": 0}


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
    assert rows[0][:8] == ["Date (UTC)", "Symbol", "Type", "Quantity", "Proceeds (CAD)", "ACB (CAD)",
                           "Outlays (CAD)", "Gain or loss (CAD)"]
    assert rows[1][:8] == ["2024-02-01", "'=CMD()", "stock", "1", "90.00", "100.00", "0.00", "-10.00"]
    assert rows[2][:8] == ["2024-02-01", "X", "stock", "1", "30.50", "10.00", "0.00", "20.50"]
    assert rows[3][0] == "Total 2024" and rows[3][4:8] == ["120.50", "110.00", "0.00", "10.50"]
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
           ("2025-03-01", "AAPL", 6.0, 300.0, 600.0, -300.0)
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
    assert rows[1][:8] == ["2023-06-01", "AAPL", "stock", "4", "600.00", "400.00", "0.00", "200.00"]
    assert rows[-1][0] == "Total 2023"


@pytest.mark.parametrize("path", ["/reports/capital-gains", "/reports/capital-gains.csv"])
@pytest.mark.parametrize("year", ["1999", str(datetime.now(timezone.utc).year + 1), "abc", "", None])
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
