"""Registration, login, verification and access control."""
import logging
import re

import pytest

from conftest import PASSWORD, FakeSMTP, login, register, unique_email


# ---------------------------------------------------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------------------------------------------------
def test_register_creates_an_unverified_user(client, db):
    email = unique_email()
    res = register(client, email=email, name="  Ada Lovelace  ", currency="USD")

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["email"] == email
    assert body["name"] == "Ada Lovelace"  # surrounding spaces stripped
    assert body["currency"] == "USD"
    assert body["is_verified"] is False
    assert "password" not in body and "hashed_password" not in body
    assert db.get_user(email).hashed_password != PASSWORD


def test_register_defaults_currency_to_cad(client):
    res = register(client, currency=None)
    assert res.status_code == 201, res.text
    assert res.json()["currency"] == "CAD"


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_register_rejects_passwords_under_8_characters(client, password):
    res = register(client, password=password)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "REGISTER_INVALID_PASSWORD"


def test_register_accepts_exactly_8_characters(client):
    assert register(client, password="k3v!n9pq").status_code == 201


@pytest.mark.parametrize("password", ["password", "12345678", "Password1", "QWERTYUIOP", "iloveyou", "1q2w3e4r5t"])
def test_register_rejects_very_common_passwords(client, password):
    res = register(client, password=password)
    assert res.status_code == 400
    assert res.json()["detail"] == {"code": "REGISTER_INVALID_PASSWORD",
                                    "reason": "That password is too common and easy to guess. Please choose another."}


@pytest.mark.parametrize("password", ["aaaaaaaa", "zzzzzzzzzzzz", "!!!!!!!!!", "1" * 20])
def test_register_rejects_one_repeated_character(client, password):
    res = register(client, password=password)
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == "Password can't be one character repeated."


def test_common_password_list_is_small_and_only_lists_long_enough_ones():
    from backend.db_models.common_passwords import COMMON_PASSWORDS
    assert 100 <= len(COMMON_PASSWORDS) <= 500
    assert all(p == p.lower() for p in COMMON_PASSWORDS)  # compared in lowercase
    assert all(len(p) >= 8 for p in COMMON_PASSWORDS)  # shorter ones are refused by the length rule already
    assert "correct-horse-battery" not in COMMON_PASSWORDS


@pytest.mark.parametrize("password", ["aaaaaaab", "password-for-zenith", "Tr0ub4dor&3x"])
def test_register_still_accepts_uncommon_passwords(client, password):
    assert register(client, password=password).status_code == 201


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_register_rejects_blank_or_too_long_names(client, name):
    assert register(client, name=name).status_code == 422


@pytest.mark.parametrize("currency", ["GBP", "cad", ""])
def test_register_rejects_unsupported_currency(client, currency):
    assert register(client, currency=currency).status_code == 422


def test_register_rejects_invalid_email(client):
    assert register(client, email="not-an-email").status_code == 422


def test_register_rejects_duplicate_email(client):
    email = unique_email()
    assert register(client, email=email).status_code == 201
    res = register(client, email=email)
    assert res.status_code == 400
    assert res.json()["detail"] == "REGISTER_USER_ALREADY_EXISTS"


def test_register_never_sends_email_without_gmail_settings(client):
    assert register(client).status_code == 201
    assert FakeSMTP.instances == []


# ---------------------------------------------------------------------------------------------------------------------
# login and verification
# ---------------------------------------------------------------------------------------------------------------------
def test_login_unverified_user_fails(client):
    email = unique_email()
    register(client, email=email)

    res = login(client, email)
    assert res.status_code == 400
    assert res.json()["detail"] == "LOGIN_USER_NOT_VERIFIED"


def test_login_with_wrong_password_fails(client, user):
    res = login(client, user.email, password="wrong-password")
    assert res.status_code == 400
    assert res.json()["detail"] == "LOGIN_BAD_CREDENTIALS"


def test_login_unknown_email_fails(client):
    res = login(client, unique_email())
    assert res.status_code == 400
    assert res.json()["detail"] == "LOGIN_BAD_CREDENTIALS"


def test_verification_link_is_logged_and_verifies_the_account(client, caplog):
    email = unique_email()
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        assert register(client, email=email).status_code == 201

    links = [r.getMessage() for r in caplog.records if "Verification link" in r.getMessage() and email in r.getMessage()]
    assert links, "the verification link should be logged when no email account is configured"
    match = re.search(r"http://localhost:5173/verify\?token=(\S+)", links[-1])
    assert match

    verified = client.post("/auth/verify", json={"token": match.group(1)})
    assert verified.status_code == 200, verified.text
    assert verified.json()["is_verified"] is True

    res = login(client, email)
    assert res.status_code == 200
    assert res.json()["token_type"] == "bearer"


def test_verify_with_bad_token(client):
    res = client.post("/auth/verify", json={"token": "not-a-token"})
    assert res.status_code == 400
    assert res.json()["detail"] == "VERIFY_USER_BAD_TOKEN"


def test_logged_in_user_can_access_protected_routes(client, user):
    assert client.get("/user", headers=user.headers).status_code == 200


def test_invalid_token_is_rejected(client):
    assert client.get("/user", headers={"Authorization": "Bearer garbage"}).status_code == 401


# ---------------------------------------------------------------------------------------------------------------------
# protected routes without a token
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method, path, body", [
    ("get", "/transactions", None),
    ("post", "/transactions", {"symbol": "AAPL", "action": "BUY", "asset_type": "stock", "price_of_one": 1,
                               "quantity": 1, "api_id": "AAPL"}),
    ("get", "/transactions/some-id", None),
    ("put", "/transactions/some-id", {"quantity": 1}),
    ("delete", "/transactions/some-id", None),
    ("get", "/holdings", None),
    ("get", "/dashboard?current_timeperiod=all", None),
    ("get", "/prices/history?symbol=AAPL&type=stock&range=1D", None),
    ("get", "/portfolio/history?range=7", None),
    ("get", "/assets/search/stock?asset=AAPL", None),
    ("get", "/assets/search/crypto?asset=btc", None),
    ("get", "/user", None),
    ("put", "/user/information", {"name": "Hacker"}),
    ("put", "/user/email", {"email": "someone@example.com"}),
])
def test_protected_routes_require_login(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    res = client.request(method.upper(), path, **kwargs)
    assert res.status_code == 401


def test_user_count_is_public(client):
    before = client.get("/users")
    assert before.status_code == 200
    assert isinstance(before.json(), int)

    register(client)
    assert client.get("/users").json() == before.json() + 1
