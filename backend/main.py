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
from backend.db.database import create_db_and_tables
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


@asynccontextmanager
async def lifespan(app: FastAPI):
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


# added before CORS so it sits inside it, and its 500 responses still get CORS headers
app.add_middleware(CatchUnhandledErrors)
app.add_middleware(SecurityHeaders)

app.add_middleware(
    CORSMiddleware,
    # FRONTEND_URL can list several origins separated by commas (e.g. with and without www)
    allow_origins=[origin.strip().rstrip("/") for origin in frontend_url.split(",") if origin.strip()]
                  + NATIVE_APP_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(user_router)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True,
                app_dir=str(PROJECT_ROOT), reload_dirs=[str(PROJECT_ROOT / "backend")])
