import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv
from fastapi_users import BaseUserManager, UUIDIDMixin, exceptions, models
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from starlette.requests import Request

load_dotenv()


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    name = Column(String, nullable=False)
    date_joined = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    currency = Column(String, nullable=False, default="CAD")

    transactions = relationship("Transaction", back_populates="user")


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = os.getenv("SECRET")
    verification_token_secret = os.getenv("SECRET")

    async def validate_password(self, password: str, user) -> None:
        # the signup form asks for 8+ characters, enforce it here too so the api can't be used to skip it
        if len(password) < 8:
            raise exceptions.InvalidPasswordException(reason="Password must be at least 8 characters.")

    async def on_after_register(self,
                                user: User,
                                request: Request | None = None):
        await self.request_verify(user, request)

    async def on_after_request_verify(self, user, token, request=None):
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        verify_url = f"{frontend_url}/verify?token={token}"

        sender = os.getenv("GMAIL_USER")
        app_pass = os.getenv("GMAIL_PASS")

        user_email = str(user.email)

        if not sender or not app_pass:
            # no email account configured (local development): log the link instead of sending an email
            logging.getLogger("uvicorn.error").warning("Verification link for %s: %s", user_email, verify_url)
            return

        email_body = f"""
        Click on the link below to verify your account:
        
        {verify_url}
        """
        message = MIMEText(email_body)

        message["Subject"] = "Email Verification"
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
