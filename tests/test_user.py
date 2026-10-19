"""/user, /user/information and /user/email."""
from datetime import datetime

import pytest

from conftest import PASSWORD, login, register, unique_email


def test_get_user(client, make_user):
    me = make_user(currency="EUR", name="Grace")
    body = client.get("/user", headers=me.headers).json()

    assert body["email"] == me.email
    assert body["name"] == "Grace"
    assert body["currency"] == "EUR"
    assert body["isVerified"] is True
    assert body["id"].replace("-", "") == me.id.replace("-", "")


def test_date_joined_has_a_timezone(client, user):
    joined = datetime.fromisoformat(client.get("/user", headers=user.headers).json()["date_joined"])
    assert joined.tzinfo is not None
    assert joined.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("saved", ["", "GBP", "usd"])
def test_unsupported_saved_currency_falls_back_to_cad(client, user, db, saved):
    db.set_user(user.email, currency=saved)
    assert client.get("/user", headers=user.headers).json()["currency"] == "CAD"


def test_empty_saved_currency_still_lists_transactions(client, user, db, buy):
    buy(user, "AAPL", 1, 100)
    db.set_user(user.email, currency="")
    [row] = client.get("/transactions", headers=user.headers).json()
    assert row["price_of_one"] == pytest.approx(100)


# ---------------------------------------------------------------------------------------------------------------------
# PUT /user/information
# ---------------------------------------------------------------------------------------------------------------------
def test_update_name_and_currency(client, user):
    res = client.put("/user/information", headers=user.headers, json={"name": "  New Name  ", "currency": "USD"})
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "New Name"
    assert res.json()["currency"] == "USD"

    again = client.get("/user", headers=user.headers).json()
    assert again["name"] == "New Name"
    assert again["currency"] == "USD"


def test_partial_update_keeps_other_fields(client, make_user):
    me = make_user(name="Keep Me")
    res = client.put("/user/information", headers=me.headers, json={"currency": "EUR"}).json()
    assert res["name"] == "Keep Me"
    assert res["currency"] == "EUR"


def test_update_cannot_change_email_or_verification(client, user, db):
    res = client.put("/user/information", headers=user.headers, json={
        "name": "Sneaky", "email": "other@example.com", "is_verified": False, "isVerified": False,
        "is_superuser": True, "id": "00000000-0000-0000-0000-000000000000",
    })
    assert res.status_code == 200
    stored = db.get_user(user.email)
    assert stored is not None
    assert stored.name == "Sneaky"
    assert stored.is_verified is True
    assert stored.is_superuser is False
    assert str(stored.id).replace("-", "") == user.id.replace("-", "")


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"currency": "GBP"},
                                  {"currency": "usd"}, {"currency": ""}])
def test_update_rejects_invalid_values(client, user, body):
    assert client.put("/user/information", headers=user.headers, json=body).status_code == 422


# ---------------------------------------------------------------------------------------------------------------------
# PUT /user/email (the bodies carry current_password since the security hardening: a token alone isn't enough)
# ---------------------------------------------------------------------------------------------------------------------
def test_change_email_marks_user_unverified(client, user, db):
    new_email = unique_email("changed")
    res = client.put("/user/email", headers=user.headers, json={"email": new_email, "current_password": PASSWORD})
    assert res.status_code == 200, res.text

    stored = db.get_user(new_email)
    assert stored is not None
    assert stored.is_verified is False
    assert db.get_user(user.email) is None

    # the old session can no longer use verified-only routes, and logging in needs verification first
    assert client.get("/user", headers=user.headers).status_code in (401, 403)
    assert login(client, new_email).json()["detail"] == "LOGIN_USER_NOT_VERIFIED"


def test_change_email_to_one_already_in_use(client, make_user, db):
    alice, bob = make_user(), make_user()
    for taken in (bob.email, bob.email.upper()):
        res = client.put("/user/email", headers=alice.headers, json={"email": taken, "current_password": PASSWORD})
        assert res.status_code == 409
        assert res.json()["detail"] == "That email is already in use"
    assert db.get_user(alice.email).is_verified is True


def test_change_email_to_unverified_accounts_email_is_also_rejected(client, user):
    other = unique_email()
    register(client, email=other)
    assert client.put("/user/email", headers=user.headers, json={"email": other, "current_password": PASSWORD}).status_code == 409


def test_change_email_rejects_invalid_email(client, user):
    assert client.put("/user/email", headers=user.headers, json={"email": "nope", "current_password": PASSWORD}).status_code == 422


def test_change_email_to_same_email(client, user):
    assert client.put("/user/email", headers=user.headers, json={"email": user.email, "current_password": PASSWORD}).status_code == 200
