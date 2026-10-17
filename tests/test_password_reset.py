"""Forgot / reset password: POST /auth/forgot-password and /auth/reset-password (links are logged, never emailed)."""
import logging
import re

from conftest import login

NEW_PASSWORD = "Brand-new-pass-1"


def request_reset_link(client, caplog, email):
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        res = client.post("/auth/forgot-password", json={"email": email})
    assert res.status_code == 202
    links = [r.getMessage() for r in caplog.records if "Password reset link" in r.getMessage() and email in r.getMessage()]
    return links


def test_reset_password_end_to_end(client, user, caplog):
    [line] = request_reset_link(client, caplog, user.email)
    token = re.search(r"http://localhost:5173/reset-password\?token=(\S+)", line).group(1)

    res = client.post("/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})
    assert res.status_code == 200, res.text

    assert login(client, user.email).status_code == 400  # the old password stops working
    assert login(client, user.email, NEW_PASSWORD).status_code == 200


def test_unknown_email_looks_the_same_and_sends_nothing(client, caplog):
    # same 202 either way, so the form can't be used to find out who has an account
    assert request_reset_link(client, caplog, "nobody-here@example.com") == []


def test_reset_token_works_once(client, user, caplog):
    [line] = request_reset_link(client, caplog, user.email)
    token = re.search(r"token=(\S+)", line).group(1)
    assert client.post("/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    again = client.post("/auth/reset-password", json={"token": token, "password": "Another-pass-22"})
    assert again.status_code == 400
    assert again.json()["detail"] == "RESET_PASSWORD_BAD_TOKEN"


def test_reset_rejects_bad_tokens_and_weak_passwords(client, user, caplog):
    bad = client.post("/auth/reset-password", json={"token": "nonsense", "password": NEW_PASSWORD})
    assert bad.json()["detail"] == "RESET_PASSWORD_BAD_TOKEN"

    [line] = request_reset_link(client, caplog, user.email)
    token = re.search(r"token=(\S+)", line).group(1)
    weak = client.post("/auth/reset-password", json={"token": token, "password": "short"})
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "RESET_PASSWORD_INVALID_PASSWORD"
