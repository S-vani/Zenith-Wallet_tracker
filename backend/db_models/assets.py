import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
import smtplib
from email.mime.text import MIMEText

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
        user = await super().authenticate(credentials)
        if user is None:
            _ratelimit().record_login_failure(credentials.username)
        else:
            _ratelimit().clear_login_failures(credentials.username)
        return user

    def check_password(self, user: User, password: str) -> bool:
        verified, _ = self.password_helper.verify_and_update(password or "", user.hashed_password)
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


def _email_account():
    return os.getenv("GMAIL_USER"), os.getenv("GMAIL_PASS")


# Emails go out in the background so a request never waits on Gmail. That also makes /auth/forgot-password answer
# as fast for an address with an account as for one without, so its timing doesn't reveal who has signed up.
_pending_emails: set = set()


def _send_in_background(to_address: str, subject: str, body: str) -> None:
    sender, app_pass = _email_account()
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_address

    def send():
        # smtplib is blocking, so it runs in a worker thread to keep the event loop free
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(str(sender), str(app_pass))
            server.sendmail(str(sender), to_address, message.as_string())

    async def run():
        try:
            await asyncio.to_thread(send)
        except Exception:
            logging.getLogger("uvicorn.error").exception("Couldn't send the \"%s\" email", subject)

    task = asyncio.get_running_loop().create_task(run())
    _pending_emails.add(task)  # keep a reference until it's done, or the task could be garbage collected
    task.add_done_callback(_pending_emails.discard)


async def send_link_email(user, page: str, token: str, subject: str, intro: str) -> None:
    """Email the user a link to a frontend page (/verify, /reset-password) that carries a one-time token."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")[0].strip().rstrip("/")
    link = f"{frontend_url}/{page}?token={token}"
    user_email = str(user.email)

    sender, app_pass = _email_account()
    if not sender or not app_pass:
        # no email account configured (local development): log the link instead of sending an email
        label = "Verification" if page == "verify" else "Password reset"
        logging.getLogger("uvicorn.error").warning("%s link for %s: %s", label, user_email, link)
        return

    _send_in_background(user_email, subject, f"{intro}\n\n{link}\n")


async def send_notice_email(to_address: str, subject: str, body: str) -> None:
    """A security notice without a link, e.g. to the old address after the email was changed."""
    sender, app_pass = _email_account()
    if not sender or not app_pass:
        logging.getLogger("uvicorn.error").warning("Security notice for %s: %s", to_address, subject)
        return
    _send_in_background(to_address, subject, body)


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
