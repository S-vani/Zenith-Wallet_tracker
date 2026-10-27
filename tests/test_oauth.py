"""
"Continue with Google" sign in: /auth/providers, /auth/google/start and /auth/google/callback.
Google itself is replaced by a fake client, so nothing leaves the machine.
"""
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import update

import backend.routes.oauth as oauth
from backend.db.database import async_session_maker
from backend.db_models.assets import User
from tests.conftest import PASSWORD, login, register, unique_email

FRONTEND = "http://localhost:5173"


class FakeGoogle:
    """Stands in for httpx_oauth's GoogleOAuth2."""

    def __init__(self, email, account_id=None, display_name="Jane Google", fail_token=False):
        self.email = email
        self.account_id = account_id or f"google-{uuid.uuid4().hex}"  # real Google ids are unique per account
        self.display_name = display_name
        self.fail_token = fail_token
        self.authorization_calls = []

    async def get_authorization_url(self, redirect_uri, state=None, scope=None, extras_params=None, **kwargs):
        self.authorization_calls.append({"redirect_uri": redirect_uri, "state": state, "scope": scope})
        return f"https://accounts.google.test/auth?state={state}"

    async def get_access_token(self, code, redirect_uri, code_verifier=None):
        if self.fail_token:
            raise RuntimeError("bad code")
        return {"access_token": "google-access-token", "expires_at": None, "refresh_token": None}

    async def get_id_email(self, token):
        return self.account_id, self.email

    async def get_profile(self, token):
        return {"names": [{"displayName": self.display_name}]}


@pytest.fixture
def google(monkeypatch):
    """Install a fake Google client; returns a function to configure it."""
    state = {}

    def _install(**kwargs):
        fake = FakeGoogle(**kwargs)
        state["fake"] = fake
        monkeypatch.setattr(oauth, "google_client", lambda: fake)
        return fake

    return _install


def start(client, next_path="/dashboard"):
    res = client.get("/auth/google/start", params={"next": next_path}, follow_redirects=False)
    assert res.status_code == 302, res.text
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    return res, state


def finish(client, state, code="auth-code"):
    res = client.get("/auth/google/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert res.status_code == 302, res.text
    return urlparse(res.headers["location"])


def fragment(location):
    return {k: v[0] for k, v in parse_qs(location.fragment).items()}


def query(location):
    return {k: v[0] for k, v in parse_qs(location.query).items()}


@pytest.fixture(autouse=True)
def fresh_cookies(client):
    client.cookies.clear()
    yield
    client.cookies.clear()


def test_providers_reports_google_disabled_without_credentials(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert client.get("/auth/providers").json() == {"google": False}


def test_providers_reports_google_enabled_with_credentials(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert client.get("/auth/providers").json() == {"google": True}


def test_start_without_credentials_sends_user_back_with_error(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    res = client.get("/auth/google/start", follow_redirects=False)
    location = urlparse(res.headers["location"])
    assert location.path == "/login"
    assert query(location)["oauth_error"] == "google_not_configured"


def test_start_redirects_to_google_with_state_and_csrf_cookie(client, google):
    fake = google(email=unique_email())
    res, state = start(client)
    assert res.headers["location"].startswith("https://accounts.google.test/")
    assert oauth.CSRF_COOKIE in res.cookies
    assert fake.authorization_calls[0]["redirect_uri"].endswith("/auth/google/callback")
    assert "email" in fake.authorization_calls[0]["scope"]


def test_new_google_user_is_created_verified_and_logged_in(client, google, db):
    email = unique_email("google")
    google(email=email, display_name="Jane Google")
    _, state = start(client, "/holdings")
    location = finish(client, state)

    assert location.geturl().startswith(f"{FRONTEND}/auth/callback")
    data = fragment(location)
    assert data["new"] == "1"
    assert data["next"] == "/holdings"

    me = client.get("/user", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["name"] == "Jane Google"
    assert me.json()["currency"] == "CAD"
    assert me.json()["isVerified"] is True


def test_returning_google_user_gets_same_account(client, google):
    email = unique_email("google")
    google(email=email, account_id="same-google-id")
    _, state = start(client)
    first = fragment(finish(client, state))

    client.cookies.clear()
    google(email=email, account_id="same-google-id")
    _, state = start(client)
    second = fragment(finish(client, state))

    assert second["new"] == "0"
    a = client.get("/user", headers={"Authorization": f"Bearer {first['token']}"}).json()
    b = client.get("/user", headers={"Authorization": f"Bearer {second['token']}"}).json()
    assert a["id"] == b["id"]


def test_google_links_to_existing_password_account_and_keeps_its_data(client, google, make_user):
    existing = make_user(name="Password Person", currency="USD")
    google(email=existing.email)
    _, state = start(client)
    data = fragment(finish(client, state))

    assert data["new"] == "0"
    me = client.get("/user", headers={"Authorization": f"Bearer {data['token']}"}).json()
    assert me["id"] == existing.id
    assert me["name"] == "Password Person"  # not overwritten by the Google name
    assert me["currency"] == "USD"
    # Changed with the security hardening: the old password used to keep working. It could belong to someone who
    # registered the address before its owner, so the first Google link replaces it and tells the user why.
    assert data["notice"] == "password_replaced"
    assert login(client, existing.email).json()["detail"] == "LOGIN_BAD_CREDENTIALS"
    assert me["hasPassword"] is False


def move_email(run, old, new, **values):
    async def go():
        async with async_session_maker() as session:
            await session.execute(update(User).where(User.email == old).values(email=new, **values))
            await session.commit()
    run(go)


def test_returning_google_user_who_changed_email_keeps_password_and_is_not_new(client, google, db, run):
    google_email = unique_email("google")
    google(email=google_email, account_id="moved-google-id")
    _, state = start(client)
    assert fragment(finish(client, state))["new"] == "1"

    # later the user chose a password and moved their Zenith account to another (confirmed) address
    moved = unique_email("moved")
    move_email(run, google_email, moved, has_password=True, is_verified=True)

    client.cookies.clear()
    google(email=google_email, account_id="moved-google-id")
    _, state = start(client)
    data = fragment(finish(client, state))
    assert data["new"] == "0"
    assert "notice" not in data
    assert db.get_user(moved).has_password is True  # used to be marked unknown, blocking password changes


def test_google_doesnt_verify_an_address_it_didnt_check(client, google, db, run):
    google_email = unique_email("google")
    google(email=google_email, account_id="typo-google-id")
    _, state = start(client)
    finish(client, state)

    # the user changed their Zenith email to an address they haven't confirmed (maybe a typo)
    typo = unique_email("typo")
    move_email(run, google_email, typo, is_verified=False)

    client.cookies.clear()
    google(email=google_email, account_id="typo-google-id")
    _, state = start(client)
    finish(client, state)
    assert db.get_user(typo).is_verified is False


def test_google_verifies_an_unverified_password_account(client, google, db):
    email = unique_email("pending")
    assert register(client, email=email).status_code == 201
    assert login(client, email).json()["detail"] == "LOGIN_USER_NOT_VERIFIED"

    google(email=email)
    _, state = start(client)
    finish(client, state)

    assert db.get_user(email).is_verified is True
    # the unconfirmed password could belong to someone who registered the address first, so it no longer works
    assert login(client, email, PASSWORD).json()["detail"] == "LOGIN_BAD_CREDENTIALS"


def test_callback_without_csrf_cookie_is_rejected(client, google):
    google(email=unique_email())
    _, state = start(client)
    client.cookies.clear()  # e.g. the callback was opened in another browser
    location = finish(client, state)
    assert location.path == "/login"
    assert query(location)["oauth_error"] == "invalid_state"


def test_callback_with_forged_state_is_rejected(client, google):
    google(email=unique_email())
    start(client)
    location = finish(client, "not-a-real-state")
    assert query(location)["oauth_error"] == "invalid_state"


def test_callback_when_user_cancels_on_google(client, google):
    google(email=unique_email())
    res = client.get("/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert query(urlparse(res.headers["location"]))["oauth_error"] == "cancelled"


def test_callback_when_google_rejects_the_code(client, google):
    google(email=unique_email(), fail_token=True)
    _, state = start(client)
    assert query(finish(client, state))["oauth_error"] == "google_error"


@pytest.mark.parametrize("unsafe", ["https://evil.example.com", "//evil.example.com", "javascript:alert(1)",
                                    "/\evil.example.com", "/	evil"])
def test_next_cannot_point_outside_the_site(client, google, unsafe):
    google(email=unique_email())
    _, state = start(client, unsafe)
    assert fragment(finish(client, state))["next"] == "/dashboard"


def test_email_verification_is_not_requested_for_google_users(client, google, monkeypatch):
    calls = []

    async def spy(self, user, request=None):
        calls.append(user.email)

    monkeypatch.setattr("backend.db_models.assets.UserManager.request_verify", spy)
    google(email=unique_email("noverify"))
    _, state = start(client)
    finish(client, state)
    assert calls == []


def test_google_tokens_are_not_stored(client, google, run):
    # Google's access/refresh tokens are only needed during sign-in, so the linked row keeps no copy
    from sqlalchemy import select

    from backend.db.database import async_session_maker
    from backend.db_models.assets import OAuthAccount

    email = unique_email()
    google(email=email)
    _, state = start(client)
    finish(client, state)

    async def linked_row():
        async with async_session_maker() as session:
            result = await session.execute(select(OAuthAccount).where(OAuthAccount.account_email == email))
            return result.scalars().one()

    row = run(linked_row)
    assert row.access_token == ""
    assert row.refresh_token is None and row.expires_at is None
