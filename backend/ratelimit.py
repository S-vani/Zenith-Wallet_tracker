"""
Small in-memory rate limiter for the sign-in, sign-up and email endpoints.

Without it the auth endpoints could be used to email-bomb someone (and get the Gmail account that sends our emails
suspended) or to try thousands of passwords. The backend runs as a single process, so counting in memory is enough;
a restart simply forgets the counters. nginx can add a coarser per-IP limit in front (docs/nginx-hardening.md).

Limits are sliding windows: "at most N events per W seconds" for a key such as "login-ip:1.2.3.4".
"""
import math
import time
from collections import deque

from fastapi import HTTPException, Request

# (max events, window in seconds)
LOGIN_PER_IP = (20, 5 * 60)  # password attempts from one address, right or wrong
LOGIN_FAILURES_PER_EMAIL = (5, 15 * 60)  # wrong passwords for one account before it's locked for a while
REGISTER_PER_IP = (10, 60 * 60)
EMAILS_PER_IP = (10, 60 * 60)  # forgot-password + resend-verification requests from one address
EMAIL_COOLDOWN = (1, 60)  # one email per address per minute...
EMAILS_PER_ADDRESS = (5, 60 * 60)  # ...and a handful per hour
TOKEN_SUBMITS_PER_IP = (20, 15 * 60)  # reset-password and verify (the tokens are signed, this just stops floods)
REAUTH_FAILURES_PER_USER = (5, 15 * 60)  # wrong "current password" on the Account page

# Only nginx on the same machine is trusted to say who the real client is
TRUSTED_PROXIES = {"127.0.0.1", "::1"}

MAX_KEYS = 100_000  # memory guard: past this, the oldest keys are dropped


class SlidingWindowLimiter:
    """Counts events per key in a sliding time window, in memory (one server process)."""
    def __init__(self, clock=time.monotonic):
        """`clock` is swappable for tests."""
        self.clock = clock
        self._events: dict[str, deque] = {}
        self._calls = 0

    def retry_after(self, key: str, limit: int, window: float) -> float:
        """Seconds until one more event is allowed for this key (0 = allowed now). Doesn't record anything."""
        events = self._events.get(key)
        if not events:
            return 0.0
        now = self.clock()
        while events and events[0] <= now - window:
            events.popleft()
        if len(events) < limit:
            return 0.0
        return max(events[-limit] + window - now, 0.0) or 0.001

    def add(self, key: str) -> None:
        self._sweep()
        self._events.setdefault(key, deque()).append(self.clock())

    def hit(self, key: str, limit: int, window: float) -> float:
        """Record an event if it's allowed; returns 0 when it was, or the seconds to wait when it wasn't."""
        wait = self.retry_after(key, limit, window)
        if wait == 0:
            self.add(key)
        return wait

    def clear(self, key: str) -> None:
        self._events.pop(key, None)

    def reset(self) -> None:
        self._events.clear()

    def _sweep(self) -> None:
        """Every so often drops keys with no recent events, so memory can't grow without end."""
        # every so often drop keys that have gone quiet, so the dict can't grow forever
        self._calls += 1
        if self._calls % 1000 and len(self._events) < MAX_KEYS:
            return
        horizon = self.clock() - 60 * 60  # the longest window in use
        for key in [k for k, events in self._events.items() if not events or events[-1] <= horizon]:
            del self._events[key]
        while len(self._events) >= MAX_KEYS:
            self._events.pop(next(iter(self._events)))


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    """
    The caller's IP. Behind nginx every request comes from 127.0.0.1, so then (and only then) the address nginx
    passes on is used. X-Real-IP is set by nginx itself; in X-Forwarded-For only the last entry was added by nginx,
    anything before it was sent by the client and could be made up.
    """
    direct = request.client.host if request.client else "unknown"
    if direct not in TRUSTED_PROXIES:
        return direct
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    return forwarded[-1] if forwarded else direct


def wait_text(seconds: float) -> str:
    """"a minute" / "5 minutes": how long to wait, for error messages."""
    if seconds < 60:
        return "a minute"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} minutes" if minutes > 1 else "a minute"


def too_many(seconds: float, message: str | None = None) -> HTTPException:
    detail = message or f"Too many attempts. Please wait {wait_text(seconds)} and try again."
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(max(1, math.ceil(seconds)))})


def enforce(key: str, rule: tuple[int, float], message: str | None = None) -> None:
    """Records one event for `key` under `rule` (count, seconds) and raises 429 once it's over the limit."""
    wait = limiter.hit(key, *rule)
    if wait:
        raise too_many(wait, message)


def normalize_email(value) -> str:
    return str(value or "").strip().lower()[:320]


# --- login lockout --------------------------------------------------------------------------------------------------
def login_locked_for(email: str) -> float:
    return limiter.retry_after(f"login-fail:{normalize_email(email)}", *LOGIN_FAILURES_PER_EMAIL)


def record_login_failure(email: str) -> None:
    limiter.add(f"login-fail:{normalize_email(email)}")


def clear_login_failures(email: str) -> None:
    limiter.clear(f"login-fail:{normalize_email(email)}")


# --- re-entering the current password (change password / email, delete account) ---------------------------------
def check_reauth_allowed(user_id) -> None:
    wait = limiter.retry_after(f"reauth-fail:{user_id}", *REAUTH_FAILURES_PER_USER)
    if wait:
        raise too_many(wait, f"Too many wrong passwords. Please wait {wait_text(wait)} and try again.")


def record_reauth_failure(user_id) -> None:
    limiter.add(f"reauth-fail:{user_id}")


def check_email_cooldown(email: str) -> None:
    """One verification / reset email per address per minute, and a few per hour, whoever asks for it."""
    address = normalize_email(email)
    if not address:
        return
    wait = max(limiter.retry_after(f"email-to:{address}", *EMAIL_COOLDOWN),
               limiter.retry_after(f"email-hour:{address}", *EMAILS_PER_ADDRESS))
    if wait:
        raise too_many(wait, f"We just sent an email to that address. Please wait {wait_text(wait)} before asking "
                             f"for another one.")
    limiter.add(f"email-to:{address}")
    limiter.add(f"email-hour:{address}")


async def _body_email(request: Request, field: str) -> str:
    """The email in a request body (JSON, or the login form), lowercased, for per-account limits."""
    try:
        if field == "username":  # the login form is form-encoded (OAuth2 password flow)
            form = await request.form()
            return normalize_email(form.get("username"))
        body = await request.json()
        return normalize_email(body.get(field)) if isinstance(body, dict) else ""
    except Exception:
        return ""  # malformed bodies get their 422 from FastAPI as usual


async def auth_rate_limit(request: Request) -> None:
    """
    Dependency for the fastapi-users routers. FastAPI has already read the body by the time this runs, and
    Starlette caches it, so reading it again here is free and leaves it intact for the route.
    The checks only use what was sent, never whether the account exists, so a 429 doesn't reveal that either.
    """
    route = request.scope.get("route")
    name = getattr(route, "name", "") or ""
    ip = client_ip(request)

    if name.endswith(".login"):
        enforce(f"login-ip:{ip}", LOGIN_PER_IP)
        email = await _body_email(request, "username")
        wait = login_locked_for(email) if email else 0
        if wait:
            raise too_many(wait, f"Too many failed sign-in attempts for this account. Please wait {wait_text(wait)} "
                                 f"or use Forgot password.")
    elif name == "register:register":
        enforce(f"register-ip:{ip}", REGISTER_PER_IP)
    elif name in ("reset:forgot_password", "verify:request-token"):
        enforce(f"emails-ip:{ip}", EMAILS_PER_IP)
        check_email_cooldown(await _body_email(request, "email"))
    elif name in ("reset:reset_password", "verify:verify"):
        enforce(f"token-ip:{ip}", TOKEN_SUBMITS_PER_IP)
