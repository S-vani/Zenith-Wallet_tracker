"""
Push notifications to the iPhone app through Apple's APNs (HTTP/2 + a token signed with the team's APNs key).

Off until configured in .env: APNS_KEY_ID, APNS_TEAM_ID and the key itself (APNS_KEY_FILE = path to the .p8, or
APNS_KEY = its contents with \\n for the line breaks). APNS_TOPIC is the app id (default ca.zenithwalletracker.app);
APNS_SANDBOX=1 sends to Apple's development servers (builds run from Xcode; TestFlight and the App Store use the
normal ones). Without them every notification still lands in the in-app inbox; only the phone buzz is missing.
Never log a device token or a notification's text.
"""
import logging
import os
import time

import httpx
import jwt

log = logging.getLogger("uvicorn.error")

TOKEN_TTL_SECONDS = 50 * 60  # Apple accepts a signed token for an hour; renew a little before
_signed: dict = {"token": None, "at": 0.0}
_client: httpx.AsyncClient | None = None


def _setting(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _key() -> str:
    path = _setting("APNS_KEY_FILE")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            log.error("APNS_KEY_FILE can't be read")
            return ""
    return _setting("APNS_KEY").replace("\\n", "\n")


def push_enabled() -> bool:
    """Whether APNs is configured (key id, team id and the key)."""
    return bool(_setting("APNS_KEY_ID") and _setting("APNS_TEAM_ID") and _key())


def _auth_token() -> str:
    """The signed provider token (ES256), reused for TOKEN_TTL_SECONDS."""
    now = time.time()
    if _signed["token"] and now - _signed["at"] < TOKEN_TTL_SECONDS:
        return _signed["token"]
    token = jwt.encode({"iss": _setting("APNS_TEAM_ID"), "iat": int(now)}, _key(), algorithm="ES256",
                       headers={"kid": _setting("APNS_KEY_ID")})
    _signed.update(token=token, at=now)
    return token


def _host() -> str:
    sandbox = _setting("APNS_SANDBOX").lower() in ("1", "true", "yes")
    return "https://api.sandbox.push.apple.com" if sandbox else "https://api.push.apple.com"


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(http2=True, timeout=10)
    return _client


async def send_push(token: str, title: str, body: str, link: str | None = None) -> str:
    """
    Sends one notification. Returns "sent", "gone" (Apple says the token is no longer valid: forget it), "failed" or
    "off" (not configured).
    """
    if not push_enabled():
        return "off"
    payload = {"aps": {"alert": {"title": title[:120], "body": body[:600]}, "sound": "default"}}
    if link:
        payload["link"] = link  # the app opens this screen when the notification is tapped (native/push.js)
    try:
        res = await _http().post(
            f"{_host()}/3/device/{token}",
            json=payload,
            headers={
                "authorization": f"bearer {_auth_token()}",
                "apns-topic": _setting("APNS_TOPIC", "ca.zenithwalletracker.app"),
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
        )
    except Exception as exc:
        log.warning("Push not sent: %s", type(exc).__name__)
        return "failed"
    if res.status_code == 200:
        return "sent"
    reason = ""
    try:
        reason = res.json().get("reason", "")
    except Exception:
        pass
    if res.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
        return "gone"
    log.warning("Push refused: %s %s", res.status_code, reason)
    return "failed"
