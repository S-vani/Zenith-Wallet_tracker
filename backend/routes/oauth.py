"""
"Continue with Google" sign in.

Flow (all full-page redirects, so it works even when the frontend and backend live on different domains):
1. The frontend sends the browser to GET /auth/google/start
2. We set a short-lived CSRF cookie and redirect to Google's consent screen
3. Google redirects back to GET /auth/google/callback on this backend
4. We check the CSRF state, find or create the user, and redirect to the frontend's /auth/callback page with the
   login token in the URL fragment (fragments are never sent to servers); the frontend stores it and clears the URL
"""
import os
import secrets
from urllib.parse import quote, urlencode

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi_users.jwt import decode_jwt, generate_jwt
from httpx_oauth.clients.google import GoogleOAuth2

from backend.authentication.authentication import auth_backend, get_user_manager
from backend.db_models.assets import UserManager

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_AUDIENCE = "zenith:google-oauth-state"
CSRF_COOKIE = "zenith_google_csrf"
STATE_LIFETIME_SECONDS = 600


def google_client() -> GoogleOAuth2 | None:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return GoogleOAuth2(client_id, client_secret)


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def frontend_url() -> str:
    # FRONTEND_URL may list several origins for CORS, the first one is where users are sent back to
    return os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")[0].strip().rstrip("/")


def callback_url() -> str:
    # this exact URL must be listed under "Authorized redirect URIs" in the Google Cloud console
    return f"{backend_url()}/auth/google/callback"


def safe_next(path: str | None) -> str:
    # only allow paths inside our own site, never a full URL to somewhere else
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return "/dashboard"


def fail(reason: str) -> RedirectResponse:
    return RedirectResponse(f"{frontend_url()}/login?{urlencode({'oauth_error': reason})}", status_code=302)


@router.get("/providers")
async def auth_providers():
    """
    Which outside sign in options are set up, so the frontend only shows buttons that work.
    """
    return {"google": google_client() is not None}


@router.get("/google/start")
async def google_start(next: str | None = None):
    client = google_client()
    if client is None:
        return fail("google_not_configured")

    csrf = secrets.token_urlsafe(32)
    state = generate_jwt({"aud": STATE_AUDIENCE, "csrf": csrf, "next": safe_next(next)},
                         os.getenv("SECRET"), STATE_LIFETIME_SECONDS)

    authorization_url = await client.get_authorization_url(
        callback_url(), state=state, scope=["openid", "email", "profile"],
        extras_params={"prompt": "select_account"},
    )

    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(CSRF_COOKIE, csrf, max_age=STATE_LIFETIME_SECONDS, httponly=True, samesite="lax",
                        secure=backend_url().startswith("https"), path="/auth/google")
    return response


@router.get("/google/callback")
async def google_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        user_manager: UserManager = Depends(get_user_manager),
        strategy=Depends(auth_backend.get_strategy),
):
    client = google_client()
    if client is None:
        return fail("google_not_configured")
    if error or not code or not state:
        return fail("cancelled")  # e.g. the user closed the Google consent screen

    try:
        state_data = decode_jwt(state, os.getenv("SECRET"), [STATE_AUDIENCE])
    except jwt.PyJWTError:
        return fail("expired")

    cookie = request.cookies.get(CSRF_COOKIE)
    if not cookie or not secrets.compare_digest(cookie, state_data.get("csrf", "")):
        return fail("invalid_state")

    try:
        token = await client.get_access_token(code, callback_url())
        account_id, account_email = await client.get_id_email(token["access_token"])
    except Exception:
        return fail("google_error")

    if not account_email:
        return fail("no_email")

    existing = True
    try:
        await user_manager.get_by_email(account_email)
    except Exception:
        existing = False

    # finds the linked account, links an existing account with the same (Google-verified) email, or creates one
    user = await user_manager.oauth_callback(
        "google", token["access_token"], account_id, account_email,
        token.get("expires_at"), token.get("refresh_token"), request,
        associate_by_email=True, is_verified_by_default=True,
    )
    if not user.is_active:
        return fail("inactive")

    if not user.is_verified:
        # Google has verified this address, so an account waiting on email verification can be trusted now
        user = await user_manager.user_db.update(user, {"is_verified": True})

    if not user.name:
        name = account_email.split("@")[0]
        try:
            profile = await client.get_profile(token["access_token"])
            name = (profile.get("names") or [{}])[0].get("displayName") or name
        except Exception:
            pass
        user = await user_manager.user_db.update(user, {"name": name})

    access_token = await strategy.write_token(user)

    fragment = urlencode({"token": access_token, "new": "0" if existing else "1", "next": state_data["next"]},
                         quote_via=quote)
    response = RedirectResponse(f"{frontend_url()}/auth/callback#{fragment}", status_code=302)
    response.delete_cookie(CSRF_COOKIE, path="/auth/google")
    return response
