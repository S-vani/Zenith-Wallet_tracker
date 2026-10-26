"""
Failure paths: a trade deleted while its edit waits on exchange rates, a cold start while the rate provider is
down, and a half-finished email setup (which must never log a working link).
"""
import asyncio
import logging
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

import backend.db_models.assets as models_module
import backend.routes.assets as routes_module
import backend.services.asset_services as services
from backend.db.database import async_session_maker
from backend.db_models.assets import Transaction
from conftest import REAL_GET_ALL_CONVERSION_RATES


# ---------------------------------------------------------------------------------------------------------------------
# Editing a trade that's deleted meanwhile: 404, not a 500 (StaleDataError)
# ---------------------------------------------------------------------------------------------------------------------
def test_edit_of_a_trade_deleted_while_rates_load_is_a_404(client, user, monkeypatch):
    res = client.post("/transactions", headers=user.headers, json={
        "symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 100, "quantity": 1,
        "api_id": "AAPL"})
    tx_id = res.json()["id"]

    async def delete_meanwhile(price, currency, at, rates):
        # another request (another tab) deletes the trade while this edit waits on the exchange rates
        async with async_session_maker() as session:
            await session.execute(delete(Transaction).where(Transaction.id == tx_id))
            await session.commit()
        return float(price)

    monkeypatch.setattr(routes_module, "to_cad_on_trade_date", delete_meanwhile)
    res = client.put(f"/transactions/{tx_id}", headers=user.headers, json={"price_of_one": 120})
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "Transaction not found"


# ---------------------------------------------------------------------------------------------------------------------
# Cold start with the rate provider down: one attempt, then a quick 503 for a while
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def rates_down(monkeypatch):
    state = type("State", (), {"calls": 0, "down": True})()

    async def fetch(value):
        state.calls += 1
        await asyncio.sleep(0.05)
        if state.down:
            raise RuntimeError("open.er-api is down")
        return value

    monkeypatch.setattr(services, "get_usd_to_cad", lambda: fetch(1.4))
    monkeypatch.setattr(services, "get_usd", lambda: fetch(0.7))
    monkeypatch.setattr(services, "get_eur", lambda: fetch(0.6))
    monkeypatch.setattr(services, "_rates_cache", {})
    monkeypatch.setattr(services, "_rates_cache_time", 0)
    monkeypatch.setattr(services, "_rates_retry_at", 0)
    return state


def test_cold_start_outage_is_tried_once_for_queued_requests(rates_down, monkeypatch):
    async def burst():
        return await asyncio.gather(*[REAL_GET_ALL_CONVERSION_RATES() for _ in range(8)], return_exceptions=True)

    results = asyncio.run(burst())
    assert all(isinstance(r, HTTPException) and r.status_code == 503 for r in results)
    assert rates_down.calls == 3  # one attempt (three currencies), not one per waiting request

    # within the failure window: a 503 straight away, no new attempt
    with pytest.raises(HTTPException) as err:
        asyncio.run(REAL_GET_ALL_CONVERSION_RATES())
    assert err.value.status_code == 503 and rates_down.calls == 3

    # once it has passed, it's tried again (and works when the provider is back)
    monkeypatch.setattr(services, "_rates_failed_at", time.time() - services.FX_COLD_FAILURE_SECONDS - 1)
    rates_down.down = False
    assert asyncio.run(REAL_GET_ALL_CONVERSION_RATES()) == {"usd_to_cad": 1.4, "usd": 0.7, "eur": 0.6}
    assert services._rates_failed_at == 0


def test_the_failure_window_is_30_to_60_seconds():
    assert 30 <= services.FX_COLD_FAILURE_SECONDS <= 60


# ---------------------------------------------------------------------------------------------------------------------
# Email: links are only logged when no email provider is configured at all
# ---------------------------------------------------------------------------------------------------------------------
EMAIL_SETTINGS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_FROM", "GMAIL_USER", "GMAIL_PASS")


@pytest.fixture
def no_email_settings(monkeypatch):
    for name in EMAIL_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _send_reset(run):
    user = type("U", (), {"email": "private-person@example.com"})()
    run(lambda: models_module.send_link_email(user, "reset-password", "secret-token-123", subject="Reset",
                                              intro="Click"))


@pytest.mark.parametrize("settings", [
    {"SMTP_HOST": "smtp.provider.test"},  # no EMAIL_FROM / SMTP_USER
    {"SMTP_HOST": "smtp.provider.test", "SMTP_PASS": "x"},
    {"GMAIL_USER": "sender@gmail.example"},  # no GMAIL_PASS
    {"GMAIL_PASS": "app-password"},
])
def test_a_broken_email_setup_never_logs_the_link_or_address(no_email_settings, run, caplog, settings):
    for name, value in settings.items():
        no_email_settings.setenv(name, value)
    with caplog.at_level(logging.DEBUG, logger="uvicorn.error"):
        _send_reset(run)
        run(lambda: models_module.send_notice_email("private-person@example.com", "Notice", "Body"))
    assert "secret-token-123" not in caplog.text and "private-person" not in caplog.text
    assert any(r.levelno == logging.ERROR and "incomplete" in r.getMessage() for r in caplog.records)


def test_no_email_setup_at_all_logs_the_link_for_development(no_email_settings, run, caplog):
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        _send_reset(run)
    assert "secret-token-123" in caplog.text
