"""Request bodies for the Account page's security actions (they all re-check the current password)."""
from pydantic import BaseModel, EmailStr, Field


class ChangeEmail(BaseModel):
    email: EmailStr
    current_password: str = Field(min_length=1, max_length=256)


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)  # the real rules live in UserManager.validate_password


class ConfirmPassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
