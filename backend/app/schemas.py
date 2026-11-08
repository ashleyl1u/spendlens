"""Request and response bodies for the API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountCreate(BaseModel):
    bank: str = Field(default="RBC", min_length=1, max_length=50)
    nickname: str = Field(min_length=1, max_length=100)
    # Only the last four digits; a full card number is never accepted.
    last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    currency: str = Field(default="CAD", pattern=r"^[A-Z]{3}$")


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank: str
    nickname: str
    last4: str | None
    currency: str
    created_at: datetime


class UploadResult(BaseModel):
    upload_id: int
    account_id: int
    inserted: int
    skipped_duplicates: int
    total_rows: int


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    upload_id: int | None
    posted_date: date
    amount_cents: int
    raw_description: str
    merchant: str | None
    category: str | None
    is_transfer: bool
    needs_review: bool


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int
