"""
Screenshot import (backend/services/scan.py, backend/routes/scan.py): the trades on a trade confirmation come back
checked like CSV import rows, never saved. Read on the device (POST /transactions/scan/fields, the free default) or,
when switched on, by Gemini (POST /transactions/scan). Gemini's HTTP call is always faked.
"""
import base64
import json
import logging
import tempfile
from collections import deque
from datetime import datetime
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest

import backend.routes.scan as scan_routes
from backend.services import scan

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"SECRETPIXELS" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
HEIF = b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic" + b"\x00" * 64
AVIF = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 64

READ_FAILED = "Couldn't read the screenshot right now. Please try again, or add the trade by hand."


def trade(**overrides):
    """A trade as Gemini's schema returns it."""
    base = {"action": "BUY", "asset_type": "stock", "symbol": "AAPL", "exchange": "NASDAQ", "name": "Apple Inc.",
            "quantity": 2, "price": 150.25, "total": None, "currency": "USD", "date": "2025-03-04T10:30:00",
            "timezone": "ET", "account_type": "TFSA", "confidence": "high"}
    base.update(overrides)
    return base


class FakeGemini:
    """Stands in for httpx in services/scan.py: answers with `answer` (a dict, put in Gemini's envelope as JSON
    text), or `status`, or `text` (raw answer text), or raises `error`."""

    def __init__(self):
        self.answer = {"trades": [trade()], "more_trades": False}
        self.status = 200
        self.text = None
        self.envelope = None
        self.error = None
        self.calls = []
        outer = self

        class AsyncClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):
                outer.calls.append({"url": url, "body": json, "headers": headers, "timeout": self.kwargs})
                if outer.error is not None:
                    raise outer.error
                text = outer.text if outer.text is not None else _json.dumps(outer.answer)
                envelope = outer.envelope or {"candidates": [{"content": {"parts": [{"text": text}]}}]}
                return SimpleNamespace(status_code=outer.status, json=lambda: envelope)

        self.module = SimpleNamespace(AsyncClient=AsyncClient, HTTPError=httpx.HTTPError)


_json = json  # `json` is shadowed by the keyword argument of the fake post()


@pytest.fixture
def gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(scan, "httpx", fake.module)
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key-123")
    monkeypatch.setenv("SCAN_WITH_GEMINI", "1")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(scan_routes, "_scan_times", {})
    monkeypatch.setattr(scan_routes, "_global_scan_times", deque())
    return fake


@pytest.fixture
def fx_history(market, monkeypatch):
    """Daily USDCAD=X closes of 1.38 since 2022 (the current rate in RATES is 1 / 0.7 = 1.43)."""
    real_ticker = market.Ticker

    class FxTicker:
        def history(self, start=None, end=None, period=None, interval=None):
            index = pd.date_range(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp.now(tz="UTC").floor("D"),
                                  freq="D")
            return pd.DataFrame({"Close": [1.38] * len(index)}, index=index)

    monkeypatch.setattr(market, "Ticker",
                        lambda symbol: FxTicker() if symbol.upper() == "USDCAD=X" else real_ticker(symbol))


def post_scan(client, owner, data=PNG, filename="shot.png", content_type="image/png"):
    headers = owner.headers if owner else {}
    return client.post("/transactions/scan", headers=headers, files={"image": (filename, data, content_type)})


def scan_ok(client, owner, **kwargs):
    res = post_scan(client, owner, **kwargs)
    assert res.status_code == 200, res.text
    return res.json()


def slots_used():
    return sum(len(times) for times in scan_routes._scan_times.values()), len(scan_routes._global_scan_times)


# ---------------------------------------------------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------------------------------------------------
def test_tsx_stock_in_cad(client, user, gemini):
    gemini.answer = {"trades": [trade(symbol="SHOP", exchange="TSX", name="Shopify Inc.", quantity=10, price=120.5,
                                      currency="CAD", date="2025-10-30T10:05:00", timezone="ET",
                                      account_type="Individual TFSA")], "more_trades": False}
    body = scan_ok(client, user)
    assert body == {"trades": [{
        "action": "BUY", "asset_type": "stock", "symbol": "SHOP.TO", "name": "Shopify Inc.", "quantity": 10.0,
        "price": 120.5, "currency": "CAD", "price_in_user_currency": 120.5, "converted": False,
        "date": "2025-10-30T14:05:00",  # 10:05 Toronto daylight time = 14:05 UTC
        "date_only": False, "account_type": "TFSA", "confidence": "high", "notes": []}], "warnings": []}


def test_gemini_request(client, user, gemini):
    # the declared type doesn't matter, the bytes do: a PNG sent as octet-stream goes to Gemini as image/png
    scan_ok(client, user, filename="photo", content_type="application/octet-stream")
    [call] = gemini.calls
    assert call["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert call["headers"] == {"x-goog-api-key": "gm-test-key-123"}
    assert "gm-test-key-123" not in json.dumps(call["body"])  # only in the header
    image_part, prompt_part = call["body"]["contents"][0]["parts"]
    assert image_part == {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(PNG).decode()}}
    assert "Never output them" in prompt_part["text"]
    assert "account numbers" in prompt_part["text"]
    config = call["body"]["generationConfig"]
    assert config["temperature"] == 0 and config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["trades"]["maxItems"] == 10


def test_gemini_model_from_env(client, user, gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    scan_ok(client, user)
    assert gemini.calls[0]["url"].endswith("/models/gemini-2.0-flash:generateContent")


@pytest.mark.parametrize("data,mime", [(JPEG, "image/jpeg"), (WEBP, "image/webp"), (HEIC, "image/heic"),
                                       (HEIF, "image/heif")])
def test_other_image_types(client, user, gemini, data, mime):
    scan_ok(client, user, data=data, filename="x", content_type="image/png")
    assert gemini.calls[0]["body"]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == mime


def test_crypto_trade(client, user, gemini):
    gemini.answer = {"trades": [trade(action="SELL", asset_type="crypto", symbol="BTC-CAD", exchange=None,
                                      name="Bitcoin", quantity=0.05, price=90000, currency="CAD",
                                      date="2025-06-01", timezone=None, account_type=None)], "more_trades": False}
    [t] = scan_ok(client, user)["trades"]
    assert (t["action"], t["asset_type"], t["symbol"], t["name"]) == ("SELL", "crypto", "btc", "Bitcoin")
    assert (t["quantity"], t["price"], t["price_in_user_currency"]) == (0.05, 90000.0, 90000.0)
    # a day alone is stored like an imported one: 21:00 UTC
    assert (t["date"], t["date_only"], t["account_type"], t["notes"]) == ("2025-06-01T21:00:00", True, None, [])


def test_usd_price_converted_for_a_cad_user_at_the_trade_dates_rate(client, make_user, gemini, fx_history):
    cad_user = make_user(currency="CAD")
    [t] = scan_ok(client, cad_user)["trades"]
    assert (t["price"], t["currency"], t["converted"]) == (150.25, "USD", True)
    assert t["price_in_user_currency"] == pytest.approx(150.25 * 1.38)  # 2025's rate, not today's 1/0.7

    eur_user = make_user(currency="EUR")
    [t] = scan_ok(client, eur_user)["trades"]
    assert t["converted"] and t["price_in_user_currency"] == pytest.approx(150.25 * 1.38 * 0.6)


def test_usd_price_not_converted_for_a_usd_user(client, make_user, gemini):
    [t] = scan_ok(client, make_user(currency="USD"))["trades"]
    assert (t["price"], t["price_in_user_currency"], t["converted"]) == (150.25, 150.25, False)


def test_recent_or_undated_trade_uses_the_current_rate(client, user, gemini):
    gemini.answer = {"trades": [trade(date=None)], "more_trades": False}
    [t] = scan_ok(client, user)["trades"]
    assert t["converted"] and t["price_in_user_currency"] == pytest.approx(150.25 / 0.7)


def test_no_exchange_rates_leaves_the_conversion_empty(client, user, gemini, monkeypatch):
    from fastapi import HTTPException
    from backend.services import asset_services

    async def down():
        raise HTTPException(status_code=503, detail="down")

    monkeypatch.setattr(asset_services, "get_all_conversion_rates", down)
    [t] = scan_ok(client, user)["trades"]
    assert (t["price"], t["price_in_user_currency"], t["converted"]) == (150.25, None, False)
    assert scan.RATES_MISSING in t["notes"]


def test_price_from_total(client, user, gemini):
    gemini.answer = {"trades": [trade(price=None, total=1004.95, quantity=10)], "more_trades": False}
    [t] = scan_ok(client, user)["trades"]
    assert t["price"] == pytest.approx(100.495)
    assert t["notes"] == ["Price worked out from the total, so it includes any fees."]


def test_multiple_trades_keep_their_order_and_are_capped_at_ten(client, user, gemini):
    gemini.answer = {"trades": [trade(symbol=f"T{i}", quantity=i + 1) for i in range(12)], "more_trades": True}
    body = scan_ok(client, user)
    assert [t["symbol"] for t in body["trades"]] == [f"T{i}" for i in range(10)]
    assert body["warnings"] == ["Only the first 10 trades were read."]

    gemini.answer = {"trades": [trade(symbol="AAPL"), trade(symbol="MSFT", action="SELL")], "more_trades": True}
    body = scan_ok(client, user)
    assert [(t["symbol"], t["action"]) for t in body["trades"]] == [("AAPL", "BUY"), ("MSFT", "SELL")]
    assert body["warnings"] == ["Only the first 10 trades were read."]  # the screenshot showed more than 10


def test_unreadable_fields_are_null_with_notes(client, user, gemini):
    gemini.answer = {"trades": [trade(name=None, quantity=None, price=None, currency=None, date=None,
                                      account_type=None, confidence="high")], "more_trades": False}
    [t] = scan_ok(client, user)["trades"]
    assert {k: t[k] for k in ("name", "quantity", "price", "currency", "price_in_user_currency", "date",
                              "account_type")} == dict.fromkeys(("name", "quantity", "price", "currency",
                                                                 "price_in_user_currency", "date", "account_type"))
    assert (t["converted"], t["date_only"], t["confidence"]) == (False, False, "low")
    assert t["notes"] == [scan.QUANTITY_UNREADABLE, scan.PRICE_UNREADABLE, scan.CURRENCY_MISSING, scan.DATE_MISSING]


def test_price_without_currency_is_kept(client, user, gemini):
    gemini.answer = {"trades": [trade(currency="$")], "more_trades": False}
    [t] = scan_ok(client, user)["trades"]
    assert (t["price"], t["currency"], t["price_in_user_currency"]) == (150.25, None, None)
    assert t["notes"] == [scan.CURRENCY_MISSING] and t["confidence"] == "medium"


def test_invalid_values_from_the_model(client, user, gemini):
    gemini.answer = {"trades": [
        trade(symbol="AAPL", quantity=-5),  # sells are often shown negative: read as 5, like the import
        trade(symbol="MSFT", date="2099-01-01T10:00:00"),
        trade(symbol="VOD", currency="GBP"),
        trade(symbol="Apple Inc. common shares!!"),  # not a ticker: left out
        trade(symbol="=cmd|' /C calc'!A0"),  # formula: left out, like the import refuses it
        trade(symbol="+SUM(A1)"),
        trade(symbol="NVDA", quantity=1e12, price=0),
        trade(symbol="AMD", quantity="abc", price="12,50", account_type="LIRA"),
        trade(symbol="TSLA", date="2025-03-04T10:30:00", timezone=None),
        trade(symbol="GOOG", action="HOLD"),  # not a buy or sell: left out
        {"nonsense": True},
    ], "more_trades": False}
    body = scan_ok(client, user)
    by_symbol = {t["symbol"]: t for t in body["trades"]}
    assert list(by_symbol) == ["AAPL", "MSFT", "VOD", "NVDA", "AMD", "TSLA"]
    assert by_symbol["AAPL"]["quantity"] == 5.0 and by_symbol["AAPL"]["notes"] == []
    assert by_symbol["MSFT"]["date"] is None and by_symbol["MSFT"]["notes"] == [scan.DATE_FUTURE]
    vod = by_symbol["VOD"]
    assert (vod["currency"], vod["price"], vod["price_in_user_currency"]) == (None, None, None)
    assert vod["notes"] == [scan.CURRENCY_UNSUPPORTED]
    nvda = by_symbol["NVDA"]
    assert (nvda["quantity"], nvda["price"]) == (None, None)
    assert nvda["notes"] == [scan.QUANTITY_INVALID, scan.PRICE_INVALID]
    amd = by_symbol["AMD"]
    assert (amd["quantity"], amd["price"], amd["account_type"]) == (None, 12.5, None)
    assert amd["notes"] == [scan.QUANTITY_UNREADABLE, scan.ACCOUNT_UNKNOWN]
    tsla = by_symbol["TSLA"]  # a time with no time zone: only the day, never a guessed zone
    assert (tsla["date"], tsla["date_only"], tsla["notes"]) == ("2025-03-04T21:00:00", True, [scan.NO_TIMEZONE])
    assert body["warnings"] == ["5 items couldn't be read as buys or sells, so they were left out."]


def test_symbols_follow_the_import_listing_rules(client, user, gemini):
    gemini.answer = {"trades": [
        trade(symbol="BRK.B", exchange="NYSE"),
        trade(symbol="ABC.VN", exchange=None, currency="CAD"),
        trade(symbol="XYZ", exchange="TSX Venture", currency="CAD"),
        trade(symbol="CTC.A", exchange="TSX", currency="CAD"),
        trade(symbol="SHOP", exchange=None, currency="CAD"),  # CAD, no exchange: the TSX listing exists
        trade(symbol="ZZZQ", exchange=None, currency="CAD"),  # no such TSX listing: stays, with a hint
        trade(symbol="eth", asset_type=None, currency="CAD"),  # missing type: a well-known coin
    ], "more_trades": False}
    trades = scan_ok(client, user)["trades"]
    assert [t["symbol"] for t in trades] == ["BRK-B", "ABC.V", "XYZ.V", "CTC-A.TO", "SHOP.TO", "ZZZQ", "eth"]
    assert trades[4]["notes"] == ["No exchange was shown: it's a CAD trade, so it was matched to the TSX listing "
                                  "SHOP.TO."]
    assert trades[5]["notes"] == [scan.CHECK_LISTING]
    assert trades[6]["asset_type"] == "crypto" and trades[6]["notes"] == [scan.ASSET_TYPE_GUESSED]


def test_date_and_time_zone_reading():
    now = datetime(2026, 11, 1, 12)
    assert scan._date("2025-01-15T09:30:00", "ET", now) == (datetime(2025, 1, 15, 14, 30), False, None)  # EST
    assert scan._date("2025-07-15T09:30:00", "EST", now) == (datetime(2025, 7, 15, 13, 30), False, None)  # EDT
    assert scan._date("2025-07-15T09:30:00", "PDT", now) == (datetime(2025, 7, 15, 16, 30), False, None)
    assert scan._date("2025-07-15 9:30 PM", "GMT-4", now) == (datetime(2025, 7, 16, 1, 30), False, None)
    assert scan._date("2025-07-15T09:30:00", "+05:30", now) == (datetime(2025, 7, 15, 4, 0), False, None)
    assert scan._date("2025-07-15T09:30:00Z", None, now) == (datetime(2025, 7, 15, 9, 30), False, None)
    assert scan._date("2025-07-15T00:00:00", None, now) == (datetime(2025, 7, 15, 21), True, None)
    assert scan._date("2025-07-15T09:30:00", "Mars time", now) == (datetime(2025, 7, 15, 21), True, scan.NO_TIMEZONE)
    assert scan._date("1965-01-01", None, now) == (None, False, scan.DATE_TOO_OLD)
    assert scan._date("Oct 30", None, now) == (None, False, scan.DATE_MISSING)
    assert scan._date("2026-02-30", None, now) == (None, False, scan.DATE_MISSING)
    assert scan._date(20250101, None, now) == (None, False, scan.DATE_MISSING)
    # 5 minutes of clock skew are allowed, like a manual trade
    # (Nov 1 2026, 07:03 Toronto standard time = 12:03 UTC; stored as "now" like the import does)
    assert scan._date("2026-11-01T07:03:00", "ET", now) == (datetime(2026, 11, 1, 12), False, None)
    assert scan._date("2026-11-01T07:06:00", "ET", now) == (None, False, scan.DATE_FUTURE)


def test_image_type_from_bytes():
    assert scan.image_type(PNG) == "image/png"
    assert scan.image_type(JPEG) == "image/jpeg"
    assert scan.image_type(WEBP) == "image/webp"
    assert scan.image_type(HEIC) == "image/heic"
    assert scan.image_type(HEIF) == "image/heif"
    assert scan.image_type(AVIF) is None
    assert scan.image_type(b"GIF89a" + b"\x00" * 20) is None
    assert scan.image_type(b"%PDF-1.7") is None


def test_nothing_is_saved(client, user, gemini):
    scan_ok(client, user)
    assert client.get("/transactions", headers=user.headers).json() == []


# ---------------------------------------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------------------------------------
def test_no_trades_found(client, user, gemini):
    gemini.answer = {"trades": [], "more_trades": False}
    res = post_scan(client, user)
    assert res.status_code == 422
    assert res.json() == {"detail": "Couldn't find a buy or sell in this screenshot. Try a screenshot of the order "
                                    "confirmation or trade details."}
    gemini.answer = {"trades": [trade(symbol=None), trade(action=None)], "more_trades": False}
    assert post_scan(client, user).status_code == 422
    assert slots_used() == (2, 2)  # Gemini did read them: these count


@pytest.mark.parametrize("failure", ["429", "500", "timeout", "connect", "not json", "no candidates", "wrong shape",
                                     "blocked"])
def test_gemini_failures_are_502_and_refunded(client, user, gemini, failure):
    if failure in ("429", "500"):
        gemini.status = int(failure)
    elif failure == "timeout":
        gemini.error = httpx.ReadTimeout("slow")
    elif failure == "connect":
        gemini.error = httpx.ConnectError("down")
    elif failure == "not json":
        gemini.text = "Here are the trades: AAPL"
    elif failure == "no candidates":
        gemini.envelope = {"promptFeedback": {"blockReason": "SAFETY"}}
    elif failure == "wrong shape":
        gemini.text = json.dumps([{"symbol": "AAPL"}])
    else:
        gemini.envelope = {"candidates": [{"finishReason": "SAFETY"}]}
    res = post_scan(client, user)
    assert res.status_code == 502
    assert res.json() == {"detail": READ_FAILED}
    assert slots_used() == (0, 0)


def test_failures_dont_use_up_the_hourly_limit(client, user, gemini, monkeypatch):
    monkeypatch.setattr(scan_routes, "SCANS_PER_HOUR", 2)
    gemini.status = 429
    for _ in range(5):
        assert post_scan(client, user).status_code == 502
    gemini.status = 200
    assert post_scan(client, user).status_code == 200


def test_no_key(client, user, gemini, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    res = post_scan(client, user)
    assert res.status_code == 503
    assert res.json() == {"detail": "Screenshot import isn't available right now."}
    assert gemini.calls == [] and slots_used() == (0, 0)


@pytest.mark.parametrize("flag", [None, "", "0", "false", "no", "off", "2"])
def test_key_alone_doesnt_switch_gemini_on(client, user, gemini, monkeypatch, flag):
    # the key alone is for the analyst's rewording; sending screenshots to Google is a separate, explicit choice
    if flag is None:
        monkeypatch.delenv("SCAN_WITH_GEMINI")
    else:
        monkeypatch.setenv("SCAN_WITH_GEMINI", flag)
    res = post_scan(client, user)
    assert (res.status_code, res.json()) == (503, {"detail": "Screenshot import isn't available right now."})
    assert gemini.calls == [] and slots_used() == (0, 0)


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "Yes", " yes "])
def test_gemini_switched_on(client, user, gemini, monkeypatch, flag):
    monkeypatch.setenv("SCAN_WITH_GEMINI", flag)
    assert scan.scan_enabled()
    scan_ok(client, user)
    assert len(gemini.calls) == 1


def test_flag_without_a_key_stays_off(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SCAN_WITH_GEMINI", "1")
    assert not scan.scan_enabled()


def test_too_large(client, user, gemini):
    too_large = {"detail": "That image is too large. Please use a screenshot under 2.5 MB."}
    just_over = PNG + b"\x00" * (scan.MAX_IMAGE_BYTES + 1 - len(PNG))
    res = post_scan(client, user, data=just_over)
    assert (res.status_code, res.json()) == (413, too_large)
    res = post_scan(client, user, data=PNG + b"\x00" * (4 * 1024 * 1024))  # refused while reading the body
    assert (res.status_code, res.json()) == (413, too_large)
    assert gemini.calls == [] and slots_used() == (0, 0)
    # exactly the limit is fine
    assert post_scan(client, user, data=PNG + b"\x00" * (scan.MAX_IMAGE_BYTES - len(PNG))).status_code == 200


def test_big_upload_stays_in_memory(client, user, gemini, monkeypatch):
    # Starlette writes uploads over 1 MB to a temporary file; a screenshot must never touch the disk
    def no_disk(self):
        raise AssertionError("the upload was written to disk")

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", no_disk)
    big = PNG + b"\x00" * (2 * 1024 * 1024)
    assert post_scan(client, user, data=big).status_code == 200
    assert gemini.calls[0]["body"]["contents"][0]["parts"][0]["inline_data"]["data"] == base64.b64encode(big).decode()


def test_wrong_type(client, user, gemini):
    res = post_scan(client, user, data=b"just some notes\nnot an image", filename="notes.png")
    assert res.status_code == 415
    assert res.json() == {"detail": "Please choose a PNG, JPEG, WebP or HEIC screenshot."}
    for data in (AVIF, b"GIF89a" + b"\x00" * 50, b"%PDF-1.4 ...", b"<svg xmlns='http://www.w3.org/2000/svg'/>"):
        assert post_scan(client, user, data=data).status_code == 415
    assert gemini.calls == [] and slots_used() == (0, 0)


def test_empty_or_missing_image(client, user, gemini):
    assert post_scan(client, user, data=b"").status_code == 422
    res = client.post("/transactions/scan", headers=user.headers, files={"photo": ("a.png", PNG, "image/png")})
    assert res.status_code == 422
    res = client.post("/transactions/scan", headers=user.headers, data={"image": "not a file"})
    assert res.status_code == 422
    res = client.post("/transactions/scan", headers=user.headers, json={"image": "aGVsbG8="})
    assert res.status_code == 422
    assert gemini.calls == [] and slots_used() == (0, 0)


def test_per_user_rate_limit(client, make_user, gemini, monkeypatch):
    monkeypatch.setattr(scan_routes, "SCANS_PER_HOUR", 2)
    first, second = make_user(), make_user()
    assert post_scan(client, first).status_code == 200
    assert post_scan(client, first).status_code == 200
    res = post_scan(client, first)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    assert len(gemini.calls) == 2
    assert post_scan(client, second).status_code == 200  # someone else isn't affected


def test_default_limits():
    assert (scan_routes.SCANS_PER_HOUR, scan_routes.GLOBAL_SCANS_PER_HOUR, scan_routes.SCAN_WINDOW) == (15, 200, 3600)


def test_global_rate_limit(client, make_user, gemini, monkeypatch):
    monkeypatch.setattr(scan_routes, "GLOBAL_SCANS_PER_HOUR", 2)
    users = [make_user() for _ in range(3)]
    assert post_scan(client, users[0]).status_code == 200
    assert post_scan(client, users[1]).status_code == 200
    res = post_scan(client, users[2])
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    assert "busy" in res.json()["detail"]
    assert slots_used() == (2, 2)  # the refused one wasn't counted for its user either


def test_signed_in_and_verified_only(client, gemini, make_user, db):
    assert post_scan(client, None).status_code == 401
    unverified = make_user()
    db.set_user(unverified.email, is_verified=False)
    assert post_scan(client, unverified).status_code in (401, 403)
    assert gemini.calls == []


def test_nothing_personal_is_logged(client, user, gemini, caplog):
    caplog.set_level(logging.DEBUG)
    marker = "Jane Q Secretname, account 12345-678"
    gemini.answer = {"trades": [trade(name=marker)], "more_trades": False}
    assert post_scan(client, user).status_code == 200
    gemini.text = f"not json: {marker}"
    assert post_scan(client, user).status_code == 502
    gemini.text, gemini.status = None, 500
    assert post_scan(client, user).status_code == 502
    gemini.status, gemini.error = 200, httpx.ReadTimeout(marker)
    assert post_scan(client, user).status_code == 502

    logged = caplog.text + " ".join(str(r.args) for r in caplog.records)
    for secret in (marker, "Secretname", "12345-678", "SECRETPIXELS", base64.b64encode(PNG).decode()[:40],
                   "gm-test-key-123"):
        assert secret not in logged
    assert "Gemini HTTP 500" in caplog.text and "ReadTimeout" in caplog.text


# ---------------------------------------------------------------------------------------------------------------------
# Fields read on the device (POST /transactions/scan/fields)
# ---------------------------------------------------------------------------------------------------------------------
def device_trade(**overrides):
    """A trade as the frontend's rule parser sends it (dates as shown, "YYYY-MM-DD HH:MM")."""
    base = trade(date="2025-03-04 10:30")
    base.update(overrides)
    return base


@pytest.fixture
def fields(monkeypatch):
    """No Gemini at all (no key, not switched on, and any HTTP call from services/scan.py fails the test)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SCAN_WITH_GEMINI", raising=False)

    class NoHttp:
        def __init__(self, *args, **kwargs):
            raise AssertionError("the fields endpoint must never call Gemini")

    monkeypatch.setattr(scan, "httpx", SimpleNamespace(AsyncClient=NoHttp, HTTPError=httpx.HTTPError))
    monkeypatch.setattr(scan_routes, "_field_scan_times", {})
    monkeypatch.setattr(scan_routes, "_scan_times", {})
    monkeypatch.setattr(scan_routes, "_global_scan_times", deque())


def post_fields(client, owner, trades=None, more_trades=None, body=None):
    headers = owner.headers if owner else {}
    if body is None:
        body = {"trades": [device_trade()] if trades is None else trades}
        if more_trades is not None:
            body["more_trades"] = more_trades
    if isinstance(body, bytes):
        return client.post("/transactions/scan/fields", headers={**headers, "Content-Type": "application/json"},
                           content=body)
    return client.post("/transactions/scan/fields", headers=headers, json=body)


def fields_ok(client, owner, *args, **kwargs):
    res = post_fields(client, owner, *args, **kwargs)
    assert res.status_code == 200, res.text
    return res.json()


def test_fields_tsx_stock_in_cad(client, user, fields):
    body = fields_ok(client, user, [device_trade(symbol="SHOP", exchange="TSX", name="Shopify Inc.", quantity=10,
                                                 price=120.5, currency="CAD", date="2025-10-30 10:05:00",
                                                 timezone="ET", account_type="TFSA")])
    # exactly the image endpoint's shape
    assert body == {"trades": [{
        "action": "BUY", "asset_type": "stock", "symbol": "SHOP.TO", "name": "Shopify Inc.", "quantity": 10.0,
        "price": 120.5, "currency": "CAD", "price_in_user_currency": 120.5, "converted": False,
        "date": "2025-10-30T14:05:00", "date_only": False, "account_type": "TFSA", "confidence": "high",
        "notes": []}], "warnings": []}


def test_fields_cad_stock_with_no_exchange_is_matched_to_the_tsx(client, user, fields):
    [t] = fields_ok(client, user, [device_trade(symbol="SHOP", exchange=None, currency="CAD")])["trades"]
    assert t["symbol"] == "SHOP.TO"
    assert t["notes"] == ["No exchange was shown: it's a CAD trade, so it was matched to the TSX listing SHOP.TO."]


def test_fields_bare_dollar_on_a_canadian_listing_is_cad(client, user, fields):
    trades = fields_ok(client, user, [device_trade(symbol="XEQT", exchange="TSX", currency="$"),
                                      device_trade(symbol="DLR.U", exchange="TSX", currency="$"),
                                      device_trade(symbol="AAPL", exchange="NASDAQ", currency="$")])["trades"]
    assert [(t["symbol"], t["currency"]) for t in trades] == [("XEQT.TO", "CAD"), ("DLR-U.TO", None),
                                                              ("AAPL", None)]
    assert trades[0]["notes"] == [scan.CURRENCY_FROM_LISTING] and trades[0]["price_in_user_currency"] is not None
    assert trades[1]["notes"] == trades[2]["notes"] == [scan.CURRENCY_MISSING]


def test_fields_same_result_as_gemini(client, user, gemini):
    # the same fields through either endpoint give the same answer
    raw = [trade(symbol="SHOP", exchange=None, currency="CAD"), trade(symbol="eth", asset_type=None),
           trade(price=None, total=301, quantity=2, date="2025-03-04 10:30", timezone=None)]
    gemini.answer = {"trades": raw, "more_trades": False}
    assert fields_ok(client, user, raw) == scan_ok(client, user)


def test_fields_usd_stock_converted_for_a_cad_user(client, make_user, fields, fx_history):
    [t] = fields_ok(client, make_user(currency="CAD"))["trades"]
    assert (t["symbol"], t["price"], t["currency"], t["converted"]) == ("AAPL", 150.25, "USD", True)
    assert t["price_in_user_currency"] == pytest.approx(150.25 * 1.38)  # the trade date's rate


def test_fields_crypto(client, user, fields):
    [t] = fields_ok(client, user, [device_trade(action="SELL", asset_type="crypto", symbol="BTC", exchange=None,
                                                name="Bitcoin", quantity=0.05, price=90000, currency="CAD",
                                                date="2025-06-01", timezone=None, account_type=None)])["trades"]
    assert (t["action"], t["asset_type"], t["symbol"], t["quantity"], t["price"]) == \
        ("SELL", "crypto", "btc", 0.05, 90000.0)
    assert (t["price_in_user_currency"], t["notes"]) == (90000.0, [])


def test_fields_price_from_total(client, user, fields):
    [t] = fields_ok(client, user, [device_trade(price=None, total=1004.95, quantity=10)])["trades"]
    assert t["price"] == pytest.approx(100.495)
    assert t["notes"] == [scan.PRICE_FROM_TOTAL]


def test_fields_dates(client, user, fields):
    trades = fields_ok(client, user, [
        device_trade(symbol="A", date="2025-03-04 10:30", timezone="ET"),  # EST: 15:30 UTC
        device_trade(symbol="B", date="2025-07-15 09:30:15", timezone="EDT"),
        device_trade(symbol="C", date="2025-07-15 09:30", timezone="GMT-4"),
        device_trade(symbol="D", date="2025-06-01", timezone=None),
        device_trade(symbol="E", date="2025-06-01 14:00", timezone=None),
        device_trade(symbol="F", date=None),
    ])["trades"]
    got = [(t["date"], t["date_only"]) for t in trades]
    assert got == [("2025-03-04T15:30:00", False), ("2025-07-15T13:30:15", False), ("2025-07-15T13:30:00", False),
                   ("2025-06-01T21:00:00", True), ("2025-06-01T21:00:00", True), (None, False)]
    assert trades[4]["notes"] == [scan.NO_TIMEZONE] and trades[5]["notes"] == [scan.DATE_MISSING]


def test_fields_account_types(client, user, fields):
    trades = fields_ok(client, user, [device_trade(account_type="TFSA"), device_trade(account_type="rrsp"),
                                      device_trade(account_type="Non-registered"), device_trade(account_type=None),
                                      device_trade(account_type="LIRA")])["trades"]
    assert [t["account_type"] for t in trades] == ["TFSA", "RRSP", "NON_REGISTERED", None, None]
    assert trades[4]["notes"] == [scan.ACCOUNT_UNKNOWN]


def test_fields_missing_keys_and_nulls(client, user, fields):
    # only what the parser found: everything else may be missing or null
    body = fields_ok(client, user, body={"trades": [{"action": "BUY", "symbol": "AAPL", "quantity": 3,
                                                      "currency": None, "unknown_new_key": "ignored"}]})
    [t] = body["trades"]
    assert (t["symbol"], t["asset_type"], t["quantity"], t["price"], t["confidence"]) == \
        ("AAPL", "stock", 3.0, None, "low")
    assert t["notes"] == [scan.ASSET_TYPE_GUESSED, scan.PRICE_UNREADABLE, scan.CURRENCY_MISSING, scan.DATE_MISSING]
    assert body["warnings"] == []
    body = fields_ok(client, user, [device_trade()], more_trades=True)
    assert body["warnings"] == ["Only the first 10 trades were read."]


def test_fields_garbage_values(client, user, fields):
    body = fields_ok(client, user, [
        device_trade(symbol="AAPL", quantity=-5),  # a sell shown negative: its size, like the import and Gemini
        device_trade(symbol="MSFT", date="2099-01-01 10:00"),
        device_trade(symbol="VOD", currency="GBP"),
        device_trade(symbol="SAP", currency="dollars"),
        device_trade(symbol="NVDA", quantity=1e12, price=0),
        device_trade(symbol="AMD", action="buy", confidence="certain"),
        device_trade(symbol="=cmd|' /C calc'!A0"),  # formula: left out
        device_trade(symbol="Apple Inc. common shares"),  # not a ticker: left out
        device_trade(symbol="GOOG", action="HOLD"),  # not a buy or sell: left out
        {},
    ])
    by_symbol = {t["symbol"]: t for t in body["trades"]}
    assert list(by_symbol) == ["AAPL", "MSFT", "VOD", "SAP", "NVDA", "AMD"]
    assert by_symbol["AAPL"]["quantity"] == 5.0 and by_symbol["AAPL"]["notes"] == []
    assert by_symbol["MSFT"]["date"] is None and by_symbol["MSFT"]["notes"] == [scan.DATE_FUTURE]
    assert (by_symbol["VOD"]["price"], by_symbol["VOD"]["notes"]) == (None, [scan.CURRENCY_UNSUPPORTED])
    assert (by_symbol["SAP"]["currency"], by_symbol["SAP"]["notes"]) == (None, [scan.CURRENCY_MISSING])
    assert by_symbol["NVDA"]["notes"] == [scan.QUANTITY_INVALID, scan.PRICE_INVALID]
    assert (by_symbol["AMD"]["action"], by_symbol["AMD"]["confidence"]) == ("BUY", "medium")
    assert body["warnings"] == ["4 items couldn't be read as buys or sells, so they were left out."]


@pytest.mark.parametrize("raw", [
    b'{"trades": [{"action": "BUY", "symbol": "AAPL", "quantity": NaN}]}',
    b'{"trades": [{"action": "BUY", "symbol": "AAPL", "price": Infinity}]}',
    b'{"trades": [{"action": "BUY", "symbol": "AAPL", "quantity": 1e999}]}',
    b'{"trades": [{"action": "BUY", "symbol": "AAPL", "quantity": "NaN"}]}',
    b'{"trades": [{"action": "BUY", "symbol": "AAPL", "price": "12.50"}]}',
    b'{"trades": [{"action": "BUY", "symbol": "AAPL", "quantity": true}]}',
    b'{"trades": [{"action": "BUY", "symbol": 123}]}',
    b'{"trades": [{"action": ["BUY"], "symbol": "AAPL"}]}',
    b'{"trades": {"action": "BUY"}}',
    b'{"trades": ["AAPL"]}',
    b'{"trades": [], "more_trades": "yes"}',
    b'[]',
    b'not json',
])
def test_fields_wrong_types_are_422(client, user, fields, raw):
    res = post_fields(client, user, body=raw)
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], list)  # FastAPI's validation shape
    assert not scan_routes._field_scan_times.get(user.id)  # a bad request isn't counted


@pytest.mark.parametrize("body", [{"trades": []}, {}, b"", {"trades": [device_trade(symbol=None)]},
                                  {"trades": [device_trade(action=None), device_trade(symbol="=1+1"), {}]}])
def test_fields_nothing_usable(client, user, fields, body):
    res = post_fields(client, user, body=body)
    assert res.status_code == 422
    assert res.json() == {"detail": scan.NO_TRADES}


def test_fields_at_most_ten_trades(client, user, fields):
    assert len(fields_ok(client, user, [device_trade(symbol=f"T{i}") for i in range(10)])["trades"]) == 10
    res = post_fields(client, user, [device_trade(symbol=f"T{i}") for i in range(11)])
    assert res.status_code == 422
    assert res.json()["detail"][0]["loc"] == ["body", "trades"]


@pytest.mark.parametrize("key", ["action", "asset_type", "symbol", "exchange", "name", "currency", "date",
                                 "timezone", "account_type", "confidence"])
def test_fields_long_text_is_422_and_not_echoed(client, user, fields, key):
    assert post_fields(client, user, [device_trade(**{key: "Z" * 100})]).status_code in (200, 422)  # at the limit
    secret = "Jane Q Secretname " + "x" * 90
    res = post_fields(client, user, [device_trade(**{key: secret})])
    assert res.status_code == 422
    assert "Secretname" not in res.text
    assert res.json()["detail"][0]["loc"] == ["body", "trades", 0, key]


def test_fields_name_at_the_limit_is_kept(client, user, fields):
    [t] = fields_ok(client, user, [device_trade(name="N" * 100)])["trades"]
    assert t["name"] == "N" * 100


def test_fields_body_too_large(client, user, fields):
    res = post_fields(client, user, body=b'{"trades": [], "pad": "' + b"x" * (64 * 1024) + b'"}')
    assert (res.status_code, res.json()) == (413, {"detail": scan.FIELDS_TOO_LARGE})


def test_fields_rate_limit(client, make_user, fields, monkeypatch):
    monkeypatch.setattr(scan_routes, "FIELD_SCANS_PER_HOUR", 2)
    first, second = make_user(), make_user()
    assert post_fields(client, first).status_code == 200
    assert post_fields(client, first, []).status_code == 422  # nothing found still counts: the work was done
    res = post_fields(client, first)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    assert post_fields(client, second).status_code == 200  # someone else isn't affected
    assert slots_used() == (0, 0)  # separate from the Gemini scans' limits


def test_fields_default_limit():
    assert scan_routes.FIELD_SCANS_PER_HOUR == 60


def test_fields_signed_in_and_verified_only(client, make_user, db, fields):
    assert post_fields(client, None).status_code == 401
    unverified = make_user()
    db.set_user(unverified.email, is_verified=False)
    assert post_fields(client, unverified).status_code in (401, 403)


def test_fields_work_with_gemini_off(client, user, fields):
    assert not scan.scan_enabled()
    assert post_scan(client, user).status_code == 503  # the image endpoint is off...
    assert fields_ok(client, user)["trades"][0]["symbol"] == "AAPL"  # ...the free one isn't


def test_fields_nothing_saved_or_logged(client, user, fields, caplog):
    caplog.set_level(logging.DEBUG)
    marker = "Jane Q Secretname 12345-678"
    assert post_fields(client, user, [device_trade(name=marker, account_type="Secretname TFSA")]).status_code == 200
    assert post_fields(client, user, [device_trade(name=marker + "y" * 100)]).status_code == 422
    logged = caplog.text + " ".join(str(r.args) for r in caplog.records)
    assert "Secretname" not in logged and "12345-678" not in logged
    assert client.get("/transactions", headers=user.headers).json() == []


# ---------------------------------------------------------------------------------------------------------------------
# GET /transactions/scan/options
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key,flag,ai", [(None, None, False), ("gm-key", None, False), ("gm-key", "0", False),
                                         (None, "1", False), ("gm-key", "1", True), ("gm-key", "Yes", True)])
def test_options(client, user, monkeypatch, key, flag, ai):
    for name, value in (("GEMINI_API_KEY", key), ("SCAN_WITH_GEMINI", flag)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    res = client.get("/transactions/scan/options", headers=user.headers)
    assert (res.status_code, res.json()) == (200, {"ai": ai})


def test_options_signed_in_only(client):
    assert client.get("/transactions/scan/options").status_code == 401


def test_scan_paths_arent_taken_by_the_transaction_routes(client, user, fields):
    # GET /transactions/{trans_id} (user_router) answers other one-segment GETs, like this one; the options path
    # has two segments and the scan router is included first in main.py, so it must still reach scan_options
    assert client.get("/transactions/scan", headers=user.headers).status_code != 200
    res = client.get("/transactions/scan/options", headers=user.headers)
    assert (res.status_code, res.json()) == (200, {"ai": False})
    assert post_fields(client, user).status_code == 200
