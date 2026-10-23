import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr

from dotenv import load_dotenv
from fastapi_users import BaseUserManager, UUIDIDMixin, exceptions, models
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from sqlalchemy import Boolean, Column, String, DateTime, ForeignKey, Integer, Numeric, false, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from starlette.requests import Request

from backend.db_models.common_passwords import COMMON_PASSWORDS

load_dotenv()


class Base(DeclarativeBase):
    pass


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """
    Links a user to an outside login provider (Google), so they can sign in with it
    """
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    name = Column(String, nullable=False, default="")  # Google sign ups start blank and get their Google name
    date_joined = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    currency = Column(String, nullable=False, default="CAD")
    # Written into every login token; bumping it signs out every device (see VersionedJWTStrategy).
    # Columns added after the first release are also listed in ADDED_COLUMNS (backend/db/database.py).
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    # False when the owner doesn't know a password: accounts made with Google, or whose password was replaced
    # when Google was linked. They're told to use "Forgot password" to set one.
    has_password = Column(Boolean, nullable=False, default=True, server_default=true())
    # True once an email has been confirmed (by link or Google). Accounts that never got there are deleted after
    # 7 days; a later email change makes is_verified False again but leaves this alone.
    ever_verified = Column(Boolean, nullable=False, default=False, server_default=false())

    transactions = relationship("Transaction", back_populates="user")
    oauth_accounts = relationship("OAuthAccount", lazy="joined")


def _ratelimit():
    # imported on first use: backend.ratelimit pulls in FastAPI, which this models module doesn't otherwise need
    from backend import ratelimit
    return ratelimit


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = os.getenv("SECRET")
    verification_token_secret = os.getenv("SECRET")

    async def validate_password(self, password: str, user) -> None:
        # the signup form asks for 8+ characters, enforce it here too so the api can't be used to skip it
        if len(password) < 8:
            raise exceptions.InvalidPasswordException(reason="Password must be at least 8 characters.")
        if len(password) > 128:
            raise exceptions.InvalidPasswordException(reason="Password must be 128 characters or fewer.")
        if not password.strip():
            raise exceptions.InvalidPasswordException(reason="Password can't be only spaces.")
        if len(set(password)) == 1:
            raise exceptions.InvalidPasswordException(reason="Password can't be one character repeated.")
        if password.lower() in COMMON_PASSWORDS:  # the first ones anyone would guess
            raise exceptions.InvalidPasswordException(
                reason="That password is too common and easy to guess. Please choose another.")
        if user is not None and getattr(user, "email", None) and password.lower() == str(user.email).lower():
            raise exceptions.InvalidPasswordException(reason="Password can't be your email address.")

    async def authenticate(self, credentials):
        # counts wrong passwords per email, so the login route can lock that account out for a while (ratelimit.py)
        user = await self._authenticate(credentials)
        if user is None:
            _ratelimit().record_login_failure(credentials.username)
        else:
            _ratelimit().clear_login_failures(credentials.username)
        return user

    # Password hashing is deliberately slow (tens of ms of CPU). fastapi-users runs it on the event loop, which
    # would stall every other request during a burst of logins, so the hot paths (login, re-entering the password,
    # changing it) run it in a worker thread instead. Signup and reset (rate limited, rare) keep the library's code.
    async def hash_password(self, password: str) -> str:
        return await asyncio.to_thread(self.password_helper.hash, password)

    async def _authenticate(self, credentials):
        """BaseUserManager.authenticate with the hashing moved off the event loop."""
        try:
            user = await self.get_by_email(credentials.username)
        except exceptions.UserNotExists:
            await self.hash_password(credentials.password)  # same work as a real check, so timing reveals nothing
            return None
        verified, updated_hash = await asyncio.to_thread(
            self.password_helper.verify_and_update, credentials.password, user.hashed_password)
        if not verified:
            return None
        if updated_hash is not None:  # upgrade to a stronger hash, as the library does
            await self.user_db.update(user, {"hashed_password": updated_hash})
        return user

    async def check_password(self, user: User, password: str) -> bool:
        verified, _ = await asyncio.to_thread(self.password_helper.verify_and_update, password or "",
                                              user.hashed_password)
        return verified

    async def sign_out_everywhere(self, user: User, **changes) -> User:
        """Bump token_version, so every token issued so far stops working, together with any other changes."""
        # an SQL expression, so two requests at once can't both write the same new number
        return await self.user_db.update(user, {"token_version": User.token_version + 1, **changes})

    async def on_after_register(self,
                                user: User,
                                request: Request | None = None):
        if user.is_verified:  # Google accounts arrive already verified, there's nothing to confirm
            return
        await self.request_verify(user, request)

    async def on_after_request_verify(self, user, token, request=None):
        await send_link_email(user, "verify", token, subject="Verify your Zenith email",
                              intro="Click the link below to verify your Zenith account:")

    async def on_after_verify(self, user, request=None):
        if not user.ever_verified:
            await self.user_db.update(user, {"ever_verified": True})

    async def on_after_forgot_password(self, user, token, request=None):
        await send_link_email(user, "reset-password", token, subject="Reset your Zenith password",
                              intro="Click the link below to choose a new Zenith password. It works for one hour. "
                                    "If you didn't ask for this, you can ignore this email.")

    async def on_after_reset_password(self, user, request=None):
        # Whoever knew the old password may still be signed in somewhere; this ends those sessions.
        # The owner knows a password now, even if the account started with Google.
        await self.sign_out_everywhere(user, has_password=True)


@dataclass(frozen=True)
class EmailAccount:
    host: str
    port: int
    user: str  # empty = the server doesn't need a login
    password: str
    sender: str  # the From header, e.g. "Zenith <noreply@zenithwalletracker.ca>"


def _email_account() -> EmailAccount | None:
    """
    Where emails are sent from, or None when nothing is configured (local development: links are logged instead).
    SMTP_HOST (+ SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM) works with any provider, so moving off a personal
    Gmail needs no code change; without it the older GMAIL_USER / GMAIL_PASS settings send through Gmail as before.
    """
    host = (os.getenv("SMTP_HOST") or "").strip()
    if host:
        try:
            port = int(os.getenv("SMTP_PORT") or 587)
        except ValueError:
            logging.getLogger("uvicorn.error").error("SMTP_PORT isn't a number, using 587")
            port = 587
        user = (os.getenv("SMTP_USER") or "").strip()
        sender = (os.getenv("EMAIL_FROM") or "").strip() or user
        if not sender:
            logging.getLogger("uvicorn.error").error("SMTP_HOST is set but EMAIL_FROM is empty, no email is sent")
            return None
        return EmailAccount(host, port, user, os.getenv("SMTP_PASS") or "", sender)

    gmail_user, gmail_pass = os.getenv("GMAIL_USER"), os.getenv("GMAIL_PASS")
    if not gmail_user or not gmail_pass:
        return None
    return EmailAccount("smtp.gmail.com", 587, gmail_user, gmail_pass, gmail_user)


# A failed send is tried again after these many seconds (a provider hiccup shouldn't lose a verification email)
EMAIL_RETRY_DELAYS = (3, 10)

# Emails go out in the background so a request never waits on the mail server. That also makes
# /auth/forgot-password answer as fast for an address with an account as for one without, so its timing doesn't
# reveal who has signed up.
_pending_emails: set = set()


def _send_in_background(account: EmailAccount, to_address: str, subject: str, body: str) -> None:
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = account.sender
    message["To"] = to_address
    message["Date"] = formatdate(usegmt=True)
    envelope_from = parseaddr(account.sender)[1] or account.sender  # the bare address of "Name <address>"
    # other providers than Gmail don't always add these, and mail without them looks like spam
    message["Message-ID"] = make_msgid(domain=envelope_from.rpartition("@")[2] or None)

    def send():
        # smtplib is blocking, so it runs in a worker thread to keep the event loop free.
        # Port 465 speaks TLS from the start; anything else (587) upgrades with STARTTLS.
        if account.port == 465:
            server = smtplib.SMTP_SSL(account.host, account.port, timeout=30)
        else:
            server = smtplib.SMTP(account.host, account.port, timeout=30)
        with server:
            if account.port != 465:
                server.starttls()
            if account.user:
                server.login(account.user, account.password)
            server.sendmail(envelope_from, to_address, message.as_string())

    async def run():
        for attempt in range(len(EMAIL_RETRY_DELAYS) + 1):
            try:
                await asyncio.to_thread(send)
                return
            except Exception as exc:
                # no traceback: SMTP errors can quote the recipient's address, which doesn't belong in the logs
                logging.getLogger("uvicorn.error").warning(
                    "Couldn't send the \"%s\" email (attempt %d of %d): %s %s", subject, attempt + 1,
                    len(EMAIL_RETRY_DELAYS) + 1, type(exc).__name__, getattr(exc, "smtp_code", ""))
            if attempt < len(EMAIL_RETRY_DELAYS):
                await asyncio.sleep(EMAIL_RETRY_DELAYS[attempt])
        logging.getLogger("uvicorn.error").error("Gave up sending the \"%s\" email", subject)

    task = asyncio.get_running_loop().create_task(run())
    _pending_emails.add(task)  # keep a reference until it's done, or the task could be garbage collected
    task.add_done_callback(_pending_emails.discard)


async def send_link_email(user, page: str, token: str, subject: str, intro: str) -> None:
    """Email the user a link to a frontend page (/verify, /reset-password) that carries a one-time token."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")[0].strip().rstrip("/")
    link = f"{frontend_url}/{page}?token={token}"
    user_email = str(user.email)

    account = _email_account()
    if account is None:
        # no email account configured (local development): log the link instead of sending an email
        label = "Verification" if page == "verify" else "Password reset"
        logging.getLogger("uvicorn.error").warning("%s link for %s: %s", label, user_email, link)
        return

    _send_in_background(account, user_email, subject, f"{intro}\n\n{link}\n")


async def send_notice_email(to_address: str, subject: str, body: str) -> None:
    """A security notice without a link, e.g. to the old address after the email was changed."""
    account = _email_account()
    if account is None:
        logging.getLogger("uvicorn.error").warning("Security notice for %s: %s", to_address, subject)
        return
    _send_in_background(account, to_address, subject, body)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    action = Column(String, nullable=False)  # Either BUY or SELL
    profit = Column(Numeric(20, 10), default=0)
    asset_type = Column(String, nullable=False)  # type of purchase (stock, crypto, currency, etc.)
    symbol = Column(String, nullable=False)  # symbol or purchase (BTC, SMP500, AAPL, USD, etc.)
    api_id = Column(String, nullable=False)
    price_of_one = Column(Numeric(20, 10), nullable=False)  # in CAD, used for maths across currencies
    quantity = Column(Numeric(20, 10), nullable=False)
    # The price exactly as typed and the currency it was typed in, so a USD buy at $100 still shows $100 after
    # USD/CAD moves (converting the CAD price back would drift). Empty on trades logged before these existed.
    price_entered = Column(Numeric(20, 10), nullable=True)
    currency_entered = Column(String, nullable=True)
    # Crypto only: the CoinGecko id picked in search (e.g. "bitcoin"). Different coins can share a ticker, so this
    # asks CoinGecko for exactly that coin instead of the most popular one with the symbol. Empty on older trades.
    coin_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="transactions")
