from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Account(Base):
    """One card or bank account a user uploads statements for."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    bank: Mapped[str] = mapped_column(String(50))
    nickname: Mapped[str] = mapped_column(String(100))
    # Only the last four digits are ever stored, never the full account number.
    last4: Mapped[str | None] = mapped_column(String(4))
    currency: Mapped[str] = mapped_column(
        String(3), default="CAD", server_default="CAD"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Upload(Base):
    """One uploaded statement file and the status of processing it."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        # The same statement row can only be stored once per account, which is what
        # makes re-uploading a file safe. It is per account, not per user, so two
        # different cards with identical purchases do not collide.
        UniqueConstraint("account_id", "row_hash", name="uq_transactions_account_row_hash"),
        Index("ix_transactions_user_posted_date", "user_id", "posted_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL")
    )
    posted_date: Mapped[date] = mapped_column(Date)
    # Integer cents: spending is positive, refunds and credits are negative.
    amount_cents: Mapped[int] = mapped_column(Integer)
    raw_description: Mapped[str] = mapped_column(String(500))
    merchant: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50))
    category_source: Mapped[str | None] = mapped_column(String(20))  # rule, cache, llm, user
    confidence: Mapped[float | None] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    is_transfer: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    row_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MerchantCategory(Base):
    """A user's remembered category for one normalized merchant name.

    Filled from LLM answers so the same merchant is never sent twice, and later from
    the user's own corrections. Rule matches are not stored: rules are cheap to rerun,
    and storing them would hide later improvements to the rules.
    """

    __tablename__ = "merchant_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "merchant", name="uq_merchant_categories_user_merchant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    merchant: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(20))  # llm, user
    confidence: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
