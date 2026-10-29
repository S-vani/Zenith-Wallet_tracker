"""Request and response models: users, trades (new and edited) and account settings, with their limits."""
from pydantic import BaseModel, Field, field_validator
from fastapi_users import schemas
import uuid
from typing import Literal, Optional, get_args

from datetime import datetime, timedelta, timezone


class UserRead(schemas.BaseUser[uuid.UUID]):
    """The account as the API returns it."""
    name: str
    date_joined: datetime
    currency: str


class UserCreate(schemas.BaseUserCreate):
    """A sign up: email, password, name and display currency."""
    name: str = Field(min_length=1, max_length=100)
    currency: Literal["CAD", "USD", "EUR"] = "CAD"

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return _strip(value)  # "   " shouldn't count as a name


# The database keeps 10 decimal places, so anything smaller would be saved as 0
MIN_AMOUNT = 1e-10
# the largest price per share / coin a trade can have (CSV import uses the same cap)
MAX_PRICE = 1e9
# Numeric(20, 10) has 10 digits before the point; 1e9 keeps a whole quantity plus its decimals inside that
MAX_QUANTITY = 1e9
# a phone whose clock runs a little fast shouldn't have "now" rejected as a future date
FUTURE_SKEW = timedelta(minutes=5)
OLDEST_DATE = datetime(1970, 1, 1)


def _strip(value):
    """Text without surrounding spaces (so "   " counts as empty); anything else as it is."""
    return value.strip() if isinstance(value, str) else value


# The (Canadian) account a trade was made in. The one list of allowed values: the transaction schemas, the
# /transactions filter, CSV import and the tax report all use it. None/NULL = not set (older trades, people who
# don't track accounts); tax maths treats that like NON_REGISTERED, but it's stored as "not set", not guessed.
AccountType = Literal["TFSA", "RRSP", "FHSA", "RESP", "NON_REGISTERED"]
ACCOUNT_TYPES: tuple[str, ...] = get_args(AccountType)
# the /transactions filter value that matches trades with no account set
ACCOUNT_UNSET = "UNSET"
AccountFilter = Literal[AccountType, Literal["UNSET"]]


# CoinGecko ids look like "bitcoin" or "usd-coin" (same rule as the analyst's coin_id); it goes into their url paths
COIN_ID_PATTERN = r"^[a-z0-9-]+$"


def _coin_id(value):
    """An empty coin id means "not known" (e.g. a stock, or an older client), not an invalid one."""
    value = _strip(value)
    return value.lower() if isinstance(value, str) and value else None


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


class _TradeChecks(BaseModel):
    """
    The checks a new trade and an edit share: symbols without surrounding spaces, an empty coin id read as "not
    known", and the trade date as naive UTC that isn't in the future (check_fields=False: the fields themselves are
    declared on each schema, with the edit's all optional).
    """

    @field_validator("symbol", "api_id", mode="before", check_fields=False)
    @classmethod
    def strip_text(cls, value):
        return _strip(value)  # "   " shouldn't count as a symbol

    @field_validator("coin_id", mode="before", check_fields=False)
    @classmethod
    def clean_coin_id(cls, value):
        return _coin_id(value)

    @field_validator("created_at", check_fields=False)
    @classmethod
    def check_date(cls, value):
        return _trade_date(value)


class CreateTransaction(_TradeChecks):
    """A trade typed in by hand (POST /transactions); the price is in the user's currency."""
    symbol: str = Field(min_length=1, max_length=32)
    action: Literal["BUY", "SELL"]
    asset_type: Literal["stock", "crypto"]
    # allow_inf_nan=False: NaN / Infinity are rejected with a 422 instead of crashing
    price_of_one: float = Field(ge=MIN_AMOUNT, le=MAX_PRICE, allow_inf_nan=False)
    quantity: float = Field(ge=MIN_AMOUNT, le=MAX_QUANTITY, allow_inf_nan=False)
    api_id: str = Field(min_length=1, max_length=64)
    # crypto: the CoinGecko id from search, so a ticker shared by several coins prices the one that was picked
    coin_id: Optional[str] = Field(default=None, max_length=80, pattern=COIN_ID_PATTERN)
    # when the trade happened; left out means now. Lets people log older trades
    created_at: Optional[datetime] = None
    # TFSA, RRSP, ... or null = not set (older app versions don't send it)
    account_type: Optional[AccountType] = None



class UpdateTransaction(_TradeChecks):
    """An edit of a trade (PUT /transactions/{id}): only the fields sent are changed."""
    symbol: Optional[str] = Field(default=None, min_length=1, max_length=32)
    action: Optional[Literal["BUY", "SELL"]] = None
    asset_type: Optional[Literal["stock", "crypto"]] = None
    price_of_one: Optional[float] = Field(default=None, ge=MIN_AMOUNT, le=MAX_PRICE, allow_inf_nan=False)
    quantity: Optional[float] = Field(default=None, ge=MIN_AMOUNT, le=MAX_QUANTITY, allow_inf_nan=False)
    api_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    coin_id: Optional[str] = Field(default=None, max_length=80, pattern=COIN_ID_PATTERN)
    created_at: Optional[datetime] = None
    # left out = unchanged, null = clear it (see the PUT route)
    account_type: Optional[AccountType] = None



class UpdateUserInfo(BaseModel):
    """The account's name and display currency (PUT /user/information): only the fields sent are changed."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    currency: Optional[Literal["CAD", "USD", "EUR"]] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return _strip(value)
