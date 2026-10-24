"""Signup and password reset hash passwords in a worker thread, not on the event loop (UserManager in
backend/db_models/assets.py), while behaving exactly like fastapi-users' own code."""
import asyncio
import logging
import re

import fastapi_users
import pytest
from fastapi_users.password import PasswordHelper

from conftest import PASSWORD, login, register, unique_email

NEW_PASSWORD = "Brand-new-pass-1"


@pytest.fixture
def hash_calls(monkeypatch):
    """Records, for every hash / verify, whether it ran with an event loop running in that thread."""
    calls = []

    def on_loop():
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    real_hash, real_verify = PasswordHelper.hash, PasswordHelper.verify_and_update

    def hash_(self, password):
        calls.append(("hash", on_loop()))
        return real_hash(self, password)

    def verify(self, plain, hashed):
        calls.append(("verify", on_loop()))
        return real_verify(self, plain, hashed)

    monkeypatch.setattr(PasswordHelper, "hash", hash_)
    monkeypatch.setattr(PasswordHelper, "verify_and_update", verify)
    return calls


def reset_token(client, caplog, email):
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202
    [line] = [r.getMessage() for r in caplog.records
              if "Password reset link" in r.getMessage() and email in r.getMessage()]
    return re.search(r"token=(\S+)", line).group(1)


def test_signup_hashes_off_the_event_loop(client, db, hash_calls):
    email = unique_email("offloop")
    res = register(client, email=email)
    assert res.status_code == 201, res.text
    assert ("hash", False) in hash_calls
    assert all(not on_loop for _, on_loop in hash_calls), hash_calls

    db.set_user(email, is_verified=True)
    assert login(client, email).status_code == 200  # the stored hash is a real one


def test_signup_keeps_its_checks(client, hash_calls):
    email = unique_email("offloop")
    assert register(client, email=email).status_code == 201
    again = register(client, email=email)
    assert again.status_code == 400
    assert again.json()["detail"] == "REGISTER_USER_ALREADY_EXISTS"

    weak = register(client, password="short")
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "REGISTER_INVALID_PASSWORD"


def test_signup_still_sends_the_verification_email(client, caplog):
    email = unique_email("offloop")
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        assert register(client, email=email).status_code == 201
    assert any("verify" in r.getMessage().lower() and email in r.getMessage() for r in caplog.records)


def test_forgot_and_reset_hash_off_the_event_loop(client, user, db, caplog, hash_calls):
    before = db.get_user(user.email).token_version
    hash_calls.clear()
    token = reset_token(client, caplog, user.email)
    res = client.post("/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})
    assert res.status_code == 200, res.text

    kinds = {kind for kind, _ in hash_calls}
    assert kinds == {"hash", "verify"}  # fingerprint hash, fingerprint check, new password hash
    assert all(not on_loop for _, on_loop in hash_calls), hash_calls

    # same results as before: new password works, old one doesn't, other sessions signed out, link used up
    assert login(client, user.email).status_code == 400
    assert login(client, user.email, NEW_PASSWORD).status_code == 200
    assert db.get_user(user.email).token_version == before + 1
    again = client.post("/auth/reset-password", json={"token": token, "password": "Another-pass-22"})
    assert again.json()["detail"] == "RESET_PASSWORD_BAD_TOKEN"


def test_reset_keeps_its_errors(client, user, caplog):
    for bad in ("nonsense", "eyJhbGciOiJIUzI1NiJ9.e30.x"):
        res = client.post("/auth/reset-password", json={"token": bad, "password": NEW_PASSWORD})
        assert res.status_code == 400
        assert res.json()["detail"] == "RESET_PASSWORD_BAD_TOKEN"

    token = reset_token(client, caplog, user.email)
    weak = client.post("/auth/reset-password", json={"token": token, "password": user.email})
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "RESET_PASSWORD_INVALID_PASSWORD"
    assert login(client, user.email, PASSWORD).status_code == 200  # nothing changed


def test_copied_library_code_matches_the_installed_version():
    # UserManager copies create / forgot_password / reset_password / _update from fastapi-users 15 to move the
    # hashing off the loop; an upgrade must re-check those copies against the new library code.
    assert fastapi_users.__version__.startswith("15."), fastapi_users.__version__
