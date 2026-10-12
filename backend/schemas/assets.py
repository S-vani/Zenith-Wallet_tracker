from pydantic import BaseModel, EmailStr, Field, field_validator
from fastapi_users import schemas
import uuid
from typing import Literal, Optional

from datetime import datetime


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


class CreateTransaction(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL"]
    asset_type: Literal["stock", "crypto"]
    price_of_one: float = Field(gt=0, le=1e9)
    quantity: float = Field(gt=0, le=1e12)
    api_id: str


class UpdateTransaction(BaseModel):
    symbol: Optional[str] = None
    action: Optional[Literal["BUY", "SELL"]] = None
    asset_type: Optional[Literal["stock", "crypto"]] = None
    price_of_one: Optional[float] = Field(default=None, gt=0, le=1e9)
    quantity: Optional[float] = Field(default=None, gt=0, le=1e12)
    api_id: Optional[str] = None


class UpdateUserInfo(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    currency: Optional[Literal["CAD", "USD", "EUR"]] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class UpdateUserEmail(BaseModel):
    email: EmailStr
