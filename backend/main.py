import uvicorn
import os
import sys
from pathlib import Path

# The code imports "backend.xxx", so the project root has to be importable even when this file is run directly
# (e.g. "python main.py" from inside the backend folder or the PyCharm run button)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import contextlib

from fastapi import Depends, FastAPI
from backend.schemas.assets import UserCreate, UserRead, UserUpdate
from backend.db.database import create_db_and_tables, engine
from backend.services.asset_services import has_cached_rates
from sqlalchemy import text
from contextlib import asynccontextmanager
from backend.authentication.authentication import auth_backend, fastapi_users
from backend.authentication.cleanup import sweep_unverified_forever
from backend.ratelimit import auth_rate_limit
from backend.routes.assets import router as user_router
from backend.routes.oauth import router as oauth_router
from backend.routes.analyst import router as analyst_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging


MIN_SECRET_LENGTH = 32


def check_secret() -> None:
    """
    SECRET signs every login token and every verify / reset-password link; a missing or short one would let anyone
    forge them. Refusing to start is better than running like that.
    """
    secret = os.getenv("SECRET") or ""
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"SECRET is {'missing' if not secret else 'too short'}: set it in .env to a random value of at least "
            f"{MIN_SECRET_LENGTH} characters, e.g. the output of: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_secret()
    await create_db_and_tables()
    # deletes accounts that never verified their email within 7 days (right away, then every few hours)
    sweeper = asyncio.create_task(sweep_unverified_forever())
    yield
    sweeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sweeper


def api_docs_enabled() -> bool:
    # The interactive docs list every endpoint for anyone who looks; only serve them when asked to (local dev)
    return os.getenv("ENABLE_API_DOCS", "").strip().lower() in ("1", "true", "yes")


_docs = api_docs_enabled()
app = FastAPI(lifespan=lifespan,
              docs_url="/docs" if _docs else None,
              redoc_url="/redoc" if _docs else None,
              openapi_url="/openapi.json" if _docs else None)


frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

# The iOS app (Capacitor) serves its pages from this origin, so it needs CORS too. It's added here rather than in
# FRONTEND_URL because the first FRONTEND_URL entry is also used for links in emails and the Google redirect.
NATIVE_APP_ORIGINS = ["capacitor://localhost"]


class CatchUnhandledErrors(BaseHTTPMiddleware):
    """
    Turn unexpected crashes into a normal JSON 500. Without this the error response skips the CORS middleware,
    so the browser hides it and the frontend can only report "can't reach the server".
    """

    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logging.getLogger("uvicorn.error").exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    """
    Same 422 shape as FastAPI's default, but without echoing the submitted values back: those can't always be turned
    into JSON (e.g. NaN), which used to turn a simple validation error into a 500.
    """
    errors = [
        {"type": e.get("type"), "loc": e.get("loc"), "msg": e.get("msg"),
         "ctx": {k: str(v) if not isinstance(v, (int, float, str, bool)) else v for k, v in (e.get("ctx") or {}).items()}}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),  # browsers must not guess a JSON response is HTML or a script
    (b"x-frame-options", b"DENY"),  # nothing here is meant to be shown inside a frame on another site
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"referrer-policy", b"no-referrer"),
]


class SecurityHeaders:
    """Adds SECURITY_HEADERS to every response (plain ASGI, so it doesn't buffer anything)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    header for header in SECURITY_HEADERS if header[0] not in present
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


APP_VERSION_HEADER = "x-zenith-app-version"
UPDATE_REQUIRED = {"detail": "This version of Zenith is out of date. Please update it from the App Store.",
                   "code": "UPDATE_REQUIRED"}


def parse_version(value: str) -> tuple[int, ...] | None:
    """ "1.2.3" -> (1, 2, 3); None for anything that isn't dot-separated numbers."""
    parts = (value or "").strip().split(".")
    if not all(part.isdigit() and part.isascii() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_outdated(version: str, minimum: str) -> bool:
    """Compared number by number, missing parts count as 0 (so 1.2 == 1.2.0). An unreadable version is outdated."""
    have = parse_version(version)
    if have is None:
        return True
    need = parse_version(minimum) or ()
    length = max(len(have), len(need))
    return have + (0,) * (length - len(have)) < need + (0,) * (length - len(need))


class RequireAppVersion:
    """
    Forced update for the iOS app: it sends X-Zenith-App-Version on every request, and when that's below
    MIN_IOS_APP_VERSION (unset = off) the answer is a 426 the app turns into an "update from the App Store" screen.
    Requests without the header (the website) are never affected, and neither are CORS preflights.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] != "OPTIONS":
            minimum = (os.getenv("MIN_IOS_APP_VERSION") or "").strip()  # read each time: can change without a deploy
            if minimum:
                version = next((value.decode("latin-1") for name, value in scope["headers"]
                                if name == APP_VERSION_HEADER.encode()), None)
                if version is not None:
                    if parse_version(minimum) is None:
                        logging.getLogger("uvicorn.error").error("MIN_IOS_APP_VERSION %r isn't a version, ignored",
                                                                 minimum)
                    elif is_outdated(version, minimum):
                        return await JSONResponse(status_code=426, content=UPDATE_REQUIRED)(scope, receive, send)
        await self.app(scope, receive, send)


# added before CORS so they sit inside it: their 500 / 426 responses still get CORS headers
app.add_middleware(CatchUnhandledErrors)
app.add_middleware(RequireAppVersion)
app.add_middleware(SecurityHeaders)

app.add_middleware(
    CORSMiddleware,
    # FRONTEND_URL can list several origins separated by commas (e.g. with and without www)
    allow_origins=[origin.strip().rstrip("/") for origin in frontend_url.split(",") if origin.strip()]
                  + NATIVE_APP_ORIGINS,
    # sign-in uses a bearer token, never cookies, so browsers needn't send cookies cross-origin (Google sign-in's
    # CSRF cookie only travels on full-page redirects, which CORS doesn't cover)
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],  # includes the app's X-Zenith-Client and X-Zenith-App-Version (preflights echo them back)
)


@app.get("/health", include_in_schema=False)
async def health():
    """
    For uptime checks: can the database answer, and are exchange rates in memory. No auth and nothing sensitive;
    503 when the database check fails.
    """
    try:
        async with asyncio.timeout(5):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logging.getLogger("uvicorn.error").error("Health check: database unavailable (%s)", type(exc).__name__)
        db_ok = False
    body = {"status": "ok" if db_ok else "error", "db": db_ok, "fx_cached": has_cached_rates()}
    return JSONResponse(status_code=200 if db_ok else 503, content=body)

# Every fastapi-users route goes through auth_rate_limit (backend/ratelimit.py): per-IP limits, a lockout after
# repeated wrong passwords, and a cooldown between emails to the same address. Over the limit = 429 with a message.
rate_limited = [Depends(auth_rate_limit)]
app.include_router(fastapi_users.get_auth_router(auth_backend, requires_verification=True),prefix="/auth/jwt",
                   tags=["auth"], dependencies=rate_limited)
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"],
                   dependencies=rate_limited)
app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"], dependencies=rate_limited)
# POST /auth/forgot-password (always 202, so it never reveals whether an email has an account) and
# POST /auth/reset-password with the emailed one-hour token
app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"], dependencies=rate_limited)
app.include_router(oauth_router)
app.include_router(analyst_router)
from backend.routes.allocation import router as allocation_router  # noqa: E402 - GET /portfolio/allocation
app.include_router(allocation_router)
from backend.routes.reports import router as reports_router  # noqa: E402 - Canadian capital gains report
app.include_router(reports_router)
# CSV import/export; before user_router, whose GET /transactions/{trans_id} would otherwise catch /transactions/export
from backend.routes.imports import router as imports_router  # noqa: E402
app.include_router(imports_router)
app.include_router(user_router)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True,
                app_dir=str(PROJECT_ROOT), reload_dirs=[str(PROJECT_ROOT / "backend")])
