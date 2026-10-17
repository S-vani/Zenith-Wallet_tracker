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
from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from starlette.requests import Request

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

    transactions = relationship("Transaction", back_populates="user")
    oauth_accounts = relationship("OAuthAccount", lazy="joined")


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
        if user is not None and getattr(user, "email", None) and password.lower() == str(user.email).lower():
            raise exceptions.InvalidPasswordException(reason="Password can't be your email address.")

    async def on_after_register(self,
                                user: User,
                                request: Request | None = None):
        if user.is_verified:  # Google accounts arrive already verified, there's nothing to confirm
            return
        await self.request_verify(user, request)

    async def on_after_request_verify(self, user, token, request=None):
        await send_link_email(user, "verify", token, subject="Verify your Zenith email",
                              intro="Click the link below to verify your Zenith account:")

    async def on_after_forgot_password(self, user, token, request=None):
        await send_link_email(user, "reset-password", token, subject="Reset your Zenith password",
                              intro="Click the link below to choose a new Zenith password. It works for one hour. "
                                    "If you didn't ask for this, you can ignore this email.")


async def send_link_email(user, page: str, token: str, subject: str, intro: str) -> None:
    """Email the user a link to a frontend page (/verify, /reset-password) that carries a one-time token."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")[0].strip().rstrip("/")
    link = f"{frontend_url}/{page}?token={token}"

    sender = os.getenv("GMAIL_USER")
    app_pass = os.getenv("GMAIL_PASS")
    user_email = str(user.email)

    if not sender or not app_pass:
        # no email account configured (local development): log the link instead of sending an email
        label = "Verification" if page == "verify" else "Password reset"
        logging.getLogger("uvicorn.error").warning("%s link for %s: %s", label, user_email, link)
        return

    message = MIMEText(f"{intro}\n\n{link}\n")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = user_email

    def send():
        # smtplib is blocking, so it runs in a worker thread to keep the event loop free
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(str(sender), str(app_pass))
            server.sendmail(str(sender), user_email, message.as_string())

    await asyncio.to_thread(send)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    action = Column(String, nullable=False)  # Either BUY or SELL
    profit = Column(Numeric(20, 10), default=0)
    asset_type = Column(String, nullable=False)  # type of purchase (stock, crypto, currency, etc.)
    symbol = Column(String, nullable=False)  # symbol or purchase (BTC, SMP500, AAPL, USD, etc.)
    api_id = Column(String, nullable=False)
    price_of_one = Column(Numeric(20, 10), nullable=False)
    quantity = Column(Numeric(20, 10), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="transactions")
