from pydantic import BaseModel, EmailStr, Field, field_validator
from fastapi_users import schemas
import uuid
from typing import Literal, Optional

from datetime import datetime, timedelta, timezone


class UserRead(schemas.BaseUser[uuid.UUID]):
    name: str
    date_joined: datetime
    currency: str


class UserCreate(schemas.BaseUserCreate):
    name: str = Field(min_length=1, max_length=100)
    currency: Literal["CAD", "USD", "EUR"] = "CAD"

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        # "   " shouldn't count as a name
        return value.strip() if isinstance(value, str) else value


class UserUpdate(schemas.BaseUserUpdate):
    pass


# The database keeps 10 decimal places, so anything smaller would be saved as 0
MIN_AMOUNT = 1e-10
# Numeric(20, 10) has 10 digits before the point; 1e9 keeps a whole quantity plus its decimals inside that
MAX_QUANTITY = 1e9
# a phone whose clock runs a little fast shouldn't have "now" rejected as a future date
FUTURE_SKEW = timedelta(minutes=5)
OLDEST_DATE = datetime(1970, 1, 1)


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _trade_date(value: Optional[datetime]) -> Optional[datetime]:
    """
    Trades are stored as naive UTC. Convert a date with an offset to UTC (like the list filters do), keep a naive one
    as UTC, and refuse dates in the future.
    """
    if value is None:
        return None
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if value > now + FUTURE_SKEW:
        raise ValueError("can't be in the future")
    if value < OLDEST_DATE:
        raise ValueError("must be after 1970")
    return min(value, now)


class CreateTransaction(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    action: Literal["BUY", "SELL"]
    asset_type: Literal["stock", "crypto"]
    # allow_inf_nan=False: NaN / Infinity are rejected with a 422 instead of crashing
    price_of_one: float = Field(ge=MIN_AMOUNT, le=1e9, allow_inf_nan=False)
    quantity: float = Field(ge=MIN_AMOUNT, le=MAX_QUANTITY, allow_inf_nan=False)
    api_id: str = Field(min_length=1, max_length=64)
    # when the trade happened; left out means now. Lets people log older trades
    created_at: Optional[datetime] = None

    @field_validator("symbol", "api_id", mode="before")
    @classmethod
    def strip_text(cls, value):
        return _strip(value)  # "   " shouldn't count as a symbol

    @field_validator("created_at")
    @classmethod
    def check_date(cls, value):
        return _trade_date(value)


class UpdateTransaction(BaseModel):
    symbol: Optional[str] = Field(default=None, min_length=1, max_length=32)
    action: Optional[Literal["BUY", "SELL"]] = None
    asset_type: Optional[Literal["stock", "crypto"]] = None
    price_of_one: Optional[float] = Field(default=None, ge=MIN_AMOUNT, le=1e9, allow_inf_nan=False)
    quantity: Optional[float] = Field(default=None, ge=MIN_AMOUNT, le=MAX_QUANTITY, allow_inf_nan=False)
    api_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    created_at: Optional[datetime] = None

    @field_validator("symbol", "api_id", mode="before")
    @classmethod
    def strip_text(cls, value):
        return _strip(value)  # "   " shouldn't count as a symbol

    @field_validator("created_at")
    @classmethod
    def check_date(cls, value):
        return _trade_date(value)


class UpdateUserInfo(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    currency: Optional[Literal["CAD", "USD", "EUR"]] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class UpdateUserEmail(BaseModel):
    email: EmailStr
