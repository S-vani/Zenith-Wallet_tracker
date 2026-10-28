"""
Regression tests for the security review (proof-of-concept scripts in the QA pass): rate limits and cooldowns,
login lockout, token revocation, re-entering the password for sensitive changes, change password, the Google
link takeover, deleting never-verified accounts, long app tokens, closed API docs, headers and the database pool.
"""
import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request

import backend.db_models.assets as models_module
import backend.main as main_module
import backend.ratelimit as ratelimit
import backend.routes.assets as routes_module
import backend.routes.oauth as oauth
from backend.authentication.authentication import APP_TOKEN_LIFETIME, WEB_TOKEN_LIFETIME
from backend.authentication.cleanup import delete_stale_unverified_users
from backend.db.database import ADDED_COLUMNS, add_missing_columns, async_session_maker, engine
from backend.db_models.assets import OAuthAccount, Transaction, User
from conftest import PASSWORD, login, register, unique_email

NEW_PASSWORD = "Brand-new-pass-1"
SECRET = "test-secret-not-used-anywhere-else-0123456789"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def token_claims(token):
    return jwt.decode(token, options={"verify_signature": False})


class FakeClock:
    """Replaces time.monotonic inside the limiter so windows can pass instantly."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(ratelimit.limiter, "clock", fake)
    return fake


@pytest.fixture
def sent(monkeypatch):
    """Capture verification / reset emails instead of logging them."""
    emails = []

    async def capture(user, page, token, subject, intro):
        emails.append((str(user.email), page, token))

    monkeypatch.setattr(models_module, "send_link_email", capture)
    return emails


# =====================================================================================================================
# 1. Rate limits, cooldowns and the login lockout
# =====================================================================================================================
def test_repeated_wrong_passwords_lock_the_account_for_a_while(client, user, clock):
    for i in range(ratelimit.LOGIN_FAILURES_PER_EMAIL[0]):
        assert login(client, user.email, password=f"guess-{i}").json()["detail"] == "LOGIN_BAD_CREDENTIALS"

    locked = login(client, user.email)  # even the right password waits now
    assert locked.status_code == 429
    assert "Too many failed sign-in attempts" in locked.json()["detail"]
    assert int(locked.headers["retry-after"]) > 0

    clock.now += ratelimit.LOGIN_FAILURES_PER_EMAIL[1] + 1
    assert login(client, user.email).status_code == 200


def test_lockout_is_per_account_and_a_good_login_resets_it(client, make_user):
    target, bystander = make_user(), make_user()
    for i in range(ratelimit.LOGIN_FAILURES_PER_EMAIL[0]):
        login(client, target.email, password=f"guess-{i}")
    assert login(client, target.email).status_code == 429
    assert login(client, bystander.email).status_code == 200

    # a successful login clears the count
    for i in range(ratelimit.LOGIN_FAILURES_PER_EMAIL[0] - 1):
        login(client, bystander.email, password=f"guess-{i}")
    assert login(client, bystander.email).status_code == 200
    login(client, bystander.email, password="one-more-wrong")
    assert login(client, bystander.email).status_code == 200


def test_login_attempts_are_limited_per_ip(client):
    limit = ratelimit.LOGIN_PER_IP[0]
    codes = [login(client, unique_email("stuffing")).status_code for _ in range(limit + 1)]
    assert codes[:limit] == [400] * limit
    assert codes[-1] == 429


def test_forgot_password_has_a_cooldown_per_address_whether_or_not_it_exists(client, user, sent, clock):
    for email in (user.email, "nobody-here@example.com"):
        assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202
        again = client.post("/auth/forgot-password", json={"email": email.upper()})
        assert again.status_code == 429  # same answer for both, so it doesn't reveal who has an account
        assert "Please wait" in again.json()["detail"]
    assert len(sent) == 1

    clock.now += ratelimit.EMAIL_COOLDOWN[1] + 1
    assert client.post("/auth/forgot-password", json={"email": user.email}).status_code == 202
    assert len(sent) == 2


def test_only_a_few_emails_per_address_per_hour(client, user, sent, clock):
    for _ in range(ratelimit.EMAILS_PER_ADDRESS[0]):
        assert client.post("/auth/forgot-password", json={"email": user.email}).status_code == 202
        clock.now += ratelimit.EMAIL_COOLDOWN[1] + 1
    assert client.post("/auth/forgot-password", json={"email": user.email}).status_code == 429
    assert len(sent) == ratelimit.EMAILS_PER_ADDRESS[0]


def test_resending_verification_has_a_cooldown(client, sent):
    email = unique_email()
    register(client, email=email)
    assert len(sent) == 1  # the sign-up email itself
    assert client.post("/auth/request-verify-token", json={"email": email}).status_code == 202
    assert client.post("/auth/request-verify-token", json={"email": email}).status_code == 429
    assert len(sent) == 2


def test_email_requests_are_limited_per_ip(client, sent):
    limit = ratelimit.EMAILS_PER_IP[0]
    codes = [client.post("/auth/forgot-password", json={"email": unique_email()}).status_code
             for _ in range(limit + 1)]
    assert codes[-1] == 429 and codes[:limit] == [202] * limit


def test_registrations_are_limited_per_ip(client):
    limit = ratelimit.REGISTER_PER_IP[0]
    codes = [register(client).status_code for _ in range(limit + 1)]
    assert codes[:limit] == [201] * limit
    assert codes[-1] == 429


def test_reset_password_submissions_are_limited_per_ip(client):
    limit = ratelimit.TOKEN_SUBMITS_PER_IP[0]
    codes = [client.post("/auth/reset-password", json={"token": "x", "password": NEW_PASSWORD}).status_code
             for _ in range(limit + 1)]
    assert codes[-1] == 429


def test_spoofed_forwarded_headers_dont_dodge_the_limit(client):
    # the test client isn't 127.0.0.1, so X-Forwarded-For / X-Real-IP from it are ignored
    limit = ratelimit.LOGIN_PER_IP[0]
    codes = [client.post("/auth/jwt/login", data={"username": unique_email(), "password": "x"},
                         headers={"X-Forwarded-For": f"10.0.0.{i}", "X-Real-IP": f"10.0.1.{i}"}).status_code
             for i in range(limit + 1)]
    assert codes[-1] == 429


def _request(host, headers=None):
    scope = {"type": "http", "client": (host, 1234), "headers": [(k.lower().encode(), v.encode())
                                                                  for k, v in (headers or {}).items()]}
    return Request(scope)


def test_client_ip_trusts_proxy_headers_only_from_localhost():
    assert ratelimit.client_ip(_request("203.0.113.9", {"X-Real-IP": "1.1.1.1"})) == "203.0.113.9"
    assert ratelimit.client_ip(_request("127.0.0.1", {"X-Real-IP": "1.1.1.1"})) == "1.1.1.1"
    # only the last X-Forwarded-For entry was added by nginx; the ones before it come from the client
    assert ratelimit.client_ip(_request("127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 2.2.2.2"})) == "2.2.2.2"
    assert ratelimit.client_ip(_request("::1", {})) == "::1"


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = ratelimit.SlidingWindowLimiter(clock=clock)
    assert [limiter.hit("k", 2, 10) for _ in range(3)] == [0, 0, 10]
    clock.now += 10
    assert limiter.hit("k", 2, 10) == 0


# =====================================================================================================================
# 6. Emails are sent in the background: forgot-password answers just as fast for every address
# =====================================================================================================================
class SlowSMTP:
    sent = []

    def __init__(self, *args, **kwargs):
        time.sleep(0.6)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, *args):
        pass

    def sendmail(self, sender, to, message):
        SlowSMTP.sent.append(to)


async def _wait_for_emails():
    await asyncio.gather(*list(models_module._pending_emails))


def test_forgot_password_never_waits_for_the_email(client, user, monkeypatch, run):
    monkeypatch.setenv("GMAIL_USER", "sender@example.com")
    monkeypatch.setenv("GMAIL_PASS", "app-password")
    monkeypatch.setattr(models_module.smtplib, "SMTP", SlowSMTP)
    SlowSMTP.sent = []

    timings = {}
    for email in (user.email, "nobody-here@example.com"):
        started = time.perf_counter()
        assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202
        timings[email] = time.perf_counter() - started

    assert max(timings.values()) < 0.4, timings  # the SMTP conversation alone takes 0.6 s
    run(_wait_for_emails)
    assert SlowSMTP.sent == [user.email]


# =====================================================================================================================
# 3. Token revocation (token_version)
# =====================================================================================================================
def test_tokens_carry_the_token_version(client, user):
    assert token_claims(user.headers["Authorization"].split()[1])["ver"] == 0


def test_log_out_of_all_devices_revokes_every_token(client, user):
    second = bearer(login(client, user.email).json()["access_token"])
    res = client.post("/user/logout-all", headers=user.headers)
    assert res.status_code == 200

    assert client.get("/user", headers=user.headers).status_code == 401
    assert client.get("/user", headers=second).status_code == 401
    fresh = bearer(login(client, user.email).json()["access_token"])
    assert client.get("/user", headers=fresh).status_code == 200


def test_password_reset_signs_out_existing_sessions(client, user, sent):
    client.post("/auth/forgot-password", json={"email": user.email})
    [(_, _, token)] = sent
    assert client.post("/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}).status_code == 200

    assert client.get("/user", headers=user.headers).status_code == 401
    assert login(client, user.email, NEW_PASSWORD).status_code == 200


def test_tokens_from_before_versioning_still_work_until_a_bump(client, user):
    from fastapi_users.jwt import generate_jwt

    old_style = generate_jwt({"sub": user.id, "aud": ["fastapi-users:auth"]}, SECRET, 3600)
    assert client.get("/user", headers=bearer(old_style)).status_code == 200
    client.post("/user/logout-all", headers=user.headers)
    assert client.get("/user", headers=bearer(old_style)).status_code == 401


def test_a_token_with_a_forged_version_is_rejected(client, user):
    from fastapi_users.jwt import generate_jwt

    forged = generate_jwt({"sub": user.id, "aud": ["fastapi-users:auth"], "ver": "0"}, SECRET, 3600)
    assert client.get("/user", headers=bearer(forged)).status_code == 401


@pytest.mark.parametrize("claims", [
    {"ver": 0},  # no "sub"
    {"sub": None, "ver": 0},
    {"sub": ["not", "an", "id"], "ver": 0},
    {"sub": "USER", "ver": 0, "nbf": [1]},
])
def test_signed_but_malformed_tokens_are_401_not_500(client, user, claims):
    # only someone with the SECRET could make these, but they must still be refused, not crash the request
    claims = {k: (user.id if v == "USER" else v) for k, v in claims.items()}
    token = jwt.encode({**claims, "aud": ["fastapi-users:auth"], "exp": int(time.time()) + 3600}, SECRET, "HS256")
    assert client.get("/user", headers=bearer(token)).status_code == 401


def test_a_reset_token_whose_fingerprint_isnt_a_hash_is_refused(client, user):
    from fastapi_users.jwt import generate_jwt

    token = generate_jwt({"sub": user.id, "password_fgpt": "plain-0", "aud": "fastapi-users:reset"}, SECRET, 3600)
    res = client.post("/auth/reset-password", json={"token": token, "password": "Totally-new-pass-1"})
    assert res.status_code == 400 and res.json()["detail"] == "RESET_PASSWORD_BAD_TOKEN"


# =====================================================================================================================
# 4. Sensitive actions need the current password; change password
# =====================================================================================================================
def change_email(client, owner, email, password=PASSWORD):
    return client.put("/user/email", headers=owner.headers, json={"email": email, "current_password": password})


def change_password(client, owner, current=PASSWORD, new=NEW_PASSWORD, headers=None):
    return client.post("/user/password", headers=headers or owner.headers,
                       json={"current_password": current, "new_password": new})


def test_email_change_needs_the_current_password(client, user, db):
    new_email = unique_email("taken-over")
    assert client.put("/user/email", headers=user.headers, json={"email": new_email}).status_code == 422
    wrong = change_email(client, user, new_email, password="attacker-guess")
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Your current password is incorrect."
    assert db.get_user(new_email) is None
    assert db.get_user(user.email).is_verified is True


def test_email_change_signs_out_everywhere_and_tells_the_old_address(client, user, db, monkeypatch, sent):
    notices = []

    async def capture(to_address, subject, body):
        notices.append((to_address, subject, body))

    monkeypatch.setattr(routes_module, "send_notice_email", capture)
    new_email = unique_email("moved")
    assert change_email(client, user, new_email).status_code == 200

    assert [(e, p) for e, p, _ in sent] == [(new_email, "verify")]
    [(to, subject, body)] = notices
    assert to == user.email and new_email in body and "changed" in subject

    db.set_user(new_email, is_verified=True)  # even once the new address is confirmed...
    assert client.get("/user", headers=user.headers).status_code == 401  # ...the old token stays dead


def test_wrong_current_passwords_are_rate_limited(client, user):
    for i in range(ratelimit.REAUTH_FAILURES_PER_USER[0]):
        assert change_password(client, user, current=f"guess-{i}").status_code == 400
    blocked = change_password(client, user)
    assert blocked.status_code == 429
    assert "Too many wrong passwords" in blocked.json()["detail"]


def test_change_password(client, user):
    other_device = bearer(login(client, user.email).json()["access_token"])
    res = change_password(client, user)
    assert res.status_code == 200, res.text

    assert login(client, user.email).json()["detail"] == "LOGIN_BAD_CREDENTIALS"
    assert login(client, user.email, NEW_PASSWORD).status_code == 200
    # every other session ends, the one that made the change gets a fresh token
    assert client.get("/user", headers=user.headers).status_code == 401
    assert client.get("/user", headers=other_device).status_code == 401
    assert client.get("/user", headers=bearer(res.json()["access_token"])).status_code == 200


@pytest.mark.parametrize("new, message", [
    ("short", "Password must be at least 8 characters."),
    (PASSWORD, "Choose a new password that's different from your current one."),
    ("password123", "That password is too common and easy to guess. Please choose another."),
    ("xxxxxxxxxx", "Password can't be one character repeated."),
])
def test_change_password_rejects_bad_new_passwords(client, user, new, message):
    res = change_password(client, user, new=new)
    assert res.status_code == 400
    assert res.json()["detail"] == message
    assert login(client, user.email).status_code == 200


def test_change_password_uses_validate_password(client, user):
    res = change_password(client, user, new=user.email.upper())
    assert res.json()["detail"] == "Password can't be your email address."


def test_change_password_needs_login(client):
    assert client.post("/user/password", json={"current_password": "a", "new_password": "b" * 8}).status_code == 401


# =====================================================================================================================
# 5. Google: the first link replaces an existing password; new Google accounts have no password
# =====================================================================================================================
class FakeGoogle:
    def __init__(self, email, account_id=None):
        self.email = email
        self.account_id = account_id or f"google-{uuid.uuid4().hex}"

    async def get_authorization_url(self, redirect_uri, state=None, scope=None, extras_params=None, **kwargs):
        return f"https://accounts.google.test/auth?state={state}"

    async def get_access_token(self, code, redirect_uri, code_verifier=None):
        return {"access_token": "google-access-token"}

    async def get_id_email(self, token):
        return self.account_id, self.email

    async def get_profile(self, token):
        return {"names": [{"displayName": "Victim"}]}


@pytest.fixture
def google_sign_in(client, monkeypatch):
    def _sign_in(email, account_id="victim-google-id"):
        monkeypatch.setattr(oauth, "google_client", lambda: FakeGoogle(email, account_id))
        client.cookies.clear()
        start = client.get("/auth/google/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        res = client.get("/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
        client.cookies.clear()
        return {k: v[0] for k, v in parse_qs(urlparse(res.headers["location"]).fragment).items()}

    yield _sign_in
    client.cookies.clear()


def test_pre_registered_password_stops_working_when_the_owner_links_google(client, sent, google_sign_in):
    # the PoC: an attacker registers the victim's address with their own password, the victim clicks the
    # verification link, then signs in with Google
    victim = unique_email("victim")
    attacker_password = "attacker-chosen-pw"
    register(client, email=victim, password=attacker_password)
    [(_, _, verify_token)] = sent
    assert client.post("/auth/verify", json={"token": verify_token}).status_code == 200
    attacker_session = bearer(login(client, victim, attacker_password).json()["access_token"])

    data = google_sign_in(victim)
    assert data["notice"] == "password_replaced"
    assert login(client, victim, attacker_password).json()["detail"] == "LOGIN_BAD_CREDENTIALS"
    assert client.get("/user", headers=attacker_session).status_code == 401
    assert client.get("/user", headers=bearer(data["token"])).json()["hasPassword"] is False

    # signing in with Google again doesn't replace anything (and keeps the earlier session)
    again = google_sign_in(victim)
    assert "notice" not in again
    assert client.get("/user", headers=bearer(data["token"])).status_code == 200


def test_google_only_accounts_are_told_to_use_forgot_password(client, google_sign_in, sent):
    email = unique_email("google-only")
    data = google_sign_in(email, account_id=f"g-{uuid.uuid4().hex}")
    headers = bearer(data["token"])
    me = client.get("/user", headers=headers).json()
    assert me["hasPassword"] is False

    res = client.post("/user/password", headers=headers,
                      json={"current_password": "anything", "new_password": NEW_PASSWORD})
    assert res.status_code == 400
    assert "Use Forgot password to set one first" in res.json()["detail"]
    deleting = client.request("DELETE", "/user", headers=headers, json={"current_password": "anything"})
    assert "Use Forgot password to set one first" in deleting.json()["detail"]

    # setting one through Forgot password makes the password features work
    client.post("/auth/forgot-password", json={"email": email})
    [(_, _, token)] = sent
    assert client.post("/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    fresh = bearer(login(client, email, NEW_PASSWORD).json()["access_token"])
    assert client.get("/user", headers=fresh).json()["hasPassword"] is True


# =====================================================================================================================
# 7. Never-verified accounts are deleted after 7 days
# =====================================================================================================================
async def _age_user(email, days, **values):
    async with async_session_maker() as session:
        user = (await session.execute(select(User).where(User.email == email))).unique().scalars().one()
        user.date_joined = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        for key, value in values.items():
            setattr(user, key, value)
        await session.commit()
        return user.id


async def _transactions_of(user_id):
    async with async_session_maker() as session:
        result = await session.execute(select(Transaction).where(Transaction.user_id == user_id))
        return result.scalars().all()


async def _link_google(user_id, email):
    async with async_session_maker() as session:
        session.add(OAuthAccount(oauth_name="google", access_token="", account_id=f"g-{user_id}",
                                 account_email=email, user_id=user_id))
        await session.commit()


def test_unverified_accounts_older_than_7_days_are_deleted_with_their_data(client, make_user, buy, run, db):
    stale_email, fresh_email = unique_email("stale"), unique_email("fresh")
    register(client, email=stale_email)
    register(client, email=fresh_email)
    stale_id = run(_age_user, stale_email, 8)
    run(_age_user, fresh_email, 6)

    # a stale account that somehow has data (e.g. made before verification was enforced)
    odd = make_user()
    buy(odd, "AAPL", 1, 100)
    odd_id = run(lambda: _age_user(odd.email, 30, is_verified=False, ever_verified=False))
    run(_link_google, odd_id, odd.email)

    # verified once and only unverified because the email was just changed: kept, data and all
    moved = make_user()
    buy(moved, "AAPL", 1, 100)
    run(lambda: _age_user(moved.email, 30, is_verified=False, ever_verified=True))
    old_verified = make_user()
    run(_age_user, old_verified.email, 400)

    assert run(delete_stale_unverified_users) >= 2
    assert db.get_user(stale_email) is None
    assert db.get_user(odd.email) is None
    assert run(_transactions_of, odd_id) == []
    assert db.get_user(fresh_email) is not None
    assert db.get_user(moved.email) is not None
    assert db.get_user(old_verified.email) is not None
    assert stale_id is not None


def test_verifying_marks_the_account_as_ever_verified(client, sent, db):
    email = unique_email()
    register(client, email=email)
    [(_, _, token)] = sent
    assert db.get_user(email).ever_verified is False
    client.post("/auth/verify", json={"token": token})
    assert db.get_user(email).ever_verified is True


async def _migrate_old_database(path):
    old_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with old_engine.begin() as conn:
            # the user table as it was before these columns existed
            await conn.execute(text('CREATE TABLE "user" (id CHAR(32) PRIMARY KEY, email VARCHAR NOT NULL, '
                                    'hashed_password VARCHAR NOT NULL, is_active BOOLEAN NOT NULL, '
                                    'is_superuser BOOLEAN NOT NULL, is_verified BOOLEAN NOT NULL, name VARCHAR, '
                                    'date_joined DATETIME, currency VARCHAR)'))
            await conn.execute(text("CREATE TABLE transactions (id VARCHAR PRIMARY KEY, user_id CHAR(32))"))
            await conn.execute(text("""INSERT INTO "user" VALUES ('a', 'a@x.co', 'h', 1, 0, 1, 'A', NULL, 'CAD'),
                                       ('b', 'b@x.co', 'h', 1, 0, 0, 'B', NULL, 'CAD'),
                                       ('c', 'c@x.co', 'h', 1, 0, 0, 'C', NULL, 'CAD')"""))
            await conn.execute(text("INSERT INTO transactions VALUES ('t1', 'c')"))
            await add_missing_columns(conn)
            await add_missing_columns(conn)  # running it again is a no-op
            rows = await conn.execute(text('SELECT id, token_version, has_password, ever_verified FROM "user" '
                                           'ORDER BY id'))
            return [tuple(row) for row in rows]
    finally:
        await old_engine.dispose()


def test_added_columns_reach_an_existing_database(run, tmp_path):
    assert {name for name, _, _ in ADDED_COLUMNS["user"]} >= {"token_version", "has_password", "ever_verified"}
    rows = run(_migrate_old_database, (tmp_path / "old.db").as_posix())
    # verified, or has transactions (only possible once verified) -> counts as verified once
    assert rows == [("a", 0, 1, 1), ("b", 0, 1, 0), ("c", 0, 1, 1)]


# =====================================================================================================================
# 8. Long tokens for the iPhone app only
# =====================================================================================================================
def _lifetime(response):
    return token_claims(response.json()["access_token"])["exp"] - time.time()


def test_app_logins_get_a_30_day_token_and_the_website_1_hour(client, user):
    web = client.post("/auth/jwt/login", data={"username": user.email, "password": PASSWORD})
    app = client.post("/auth/jwt/login", data={"username": user.email, "password": PASSWORD},
                      headers={"X-Zenith-Client": "ios-app"})
    assert WEB_TOKEN_LIFETIME - 60 < _lifetime(web) <= WEB_TOKEN_LIFETIME
    assert APP_TOKEN_LIFETIME - 60 < _lifetime(app) <= APP_TOKEN_LIFETIME
    assert APP_TOKEN_LIFETIME == 30 * 24 * 3600
    # and revoking works on the long one too
    client.post("/user/logout-all", headers=user.headers)
    assert client.get("/user", headers=bearer(app.json()["access_token"])).status_code == 401


def test_the_app_renews_its_token_while_it_is_still_valid(client, user):
    app_headers = {"X-Zenith-Client": "ios-app"}
    old = client.post("/auth/jwt/login", data={"username": user.email, "password": PASSWORD},
                      headers=app_headers).json()["access_token"]
    renewed = client.post("/user/token", headers={**bearer(old), **app_headers})
    assert renewed.status_code == 200
    assert APP_TOKEN_LIFETIME - 60 < _lifetime(renewed) <= APP_TOKEN_LIFETIME
    assert client.get("/user", headers=bearer(renewed.json()["access_token"])).status_code == 200

    # a website token can't be turned into a 30-day one (or kept alive by renewing it), asked for as the app or not
    assert client.post("/user/token", headers={**user.headers, **app_headers}).status_code == 403
    assert client.post("/user/token", headers=user.headers).status_code == 403
    # nor can the app's token be renewed by a client that doesn't say it's the app
    assert client.post("/user/token", headers=bearer(old)).status_code == 403


def test_a_revoked_token_cant_be_renewed(client, user):
    client.post("/user/logout-all", headers=user.headers)
    assert client.post("/user/token", headers=user.headers).status_code == 401


# =====================================================================================================================
# 9. Production hygiene: no public API docs, security headers
# =====================================================================================================================
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_by_default(client, path):
    assert client.get(path).status_code == 404


def test_api_docs_can_be_switched_on(monkeypatch):
    monkeypatch.setenv("ENABLE_API_DOCS", "1")
    assert main_module.api_docs_enabled() is True
    monkeypatch.setenv("ENABLE_API_DOCS", "")
    assert main_module.api_docs_enabled() is False


@pytest.mark.parametrize("path", ["/auth/providers", "/user", "/does-not-exist"])
def test_security_headers_on_every_response(client, path):
    headers = client.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_rate_limit_responses_still_get_cors_headers(client):
    for _ in range(ratelimit.REGISTER_PER_IP[0]):
        register(client)
    res = client.post("/auth/register", json={"email": unique_email(), "password": PASSWORD, "name": "x"},
                      headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 429
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"  # so the page can read the detail


# =====================================================================================================================
# 2. The database pool: one slow request no longer blocks everyone
# =====================================================================================================================
async def _journal_mode():
    async with engine.connect() as conn:
        return (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()


def test_sqlite_uses_wal_and_a_real_pool(run):
    assert run(_journal_mode).lower() == "wal"
    assert engine.pool.size() >= 5


async def _request_while_a_connection_is_busy(headers):
    async with async_session_maker() as slow:
        await slow.execute(text("SELECT 1"))  # like a request holding its session during a slow Yahoo call
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main_module.app),
                                     base_url="http://test") as other:
            res = await asyncio.wait_for(other.get("/user", headers=headers), timeout=10)
        return res.status_code


def test_a_held_connection_doesnt_block_other_users(run, user):
    assert run(_request_while_a_connection_is_busy, user.headers) == 200


def test_logged_link_still_appears_without_gmail(client, caplog):
    # local development: no Gmail account, so the link is logged straight away (nothing in the background)
    email = unique_email()
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        register(client, email=email)
    assert any(re.search(r"verify\?token=", r.getMessage()) and email in r.getMessage() for r in caplog.records)
