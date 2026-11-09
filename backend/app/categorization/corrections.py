"""A user's own category corrections, and remembering them for future uploads.

A correction is stored twice: on the transaction itself, and in the user's
merchant_categories cache with source "user". The pipeline reads the cache before the
rules and the provider, and the provider never overwrites a "user" row, so every later
upload of that merchant gets the user's category.
"""

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from ..db import dialect_insert
from ..models import MerchantCategory, Transaction
from .categories import CATEGORIES

USER_SOURCE = "user"
USER_CONFIDENCE = 1.0


def correct_transaction(
    db: Session, transaction: Transaction, category: str, apply_to_merchant: bool = True
) -> int:
    """Recategorize one transaction, remember the merchant, and optionally fix the
    user's other transactions from the same merchant.

    The caller has already checked that the transaction belongs to the user and is not
    a transfer. Nothing is committed here, so the caller can do it all in one database
    transaction. Returns how many other transactions were updated.
    """
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    if transaction.is_transfer:
        raise ValueError("transfers cannot be recategorized")

    _mark_corrected(transaction, category)
    if not transaction.merchant:
        return 0  # nothing to remember, and nothing else is "the same merchant"

    remember_user_category(db, transaction.user_id, transaction.merchant, category)
    if not apply_to_merchant:
        return 0

    result = db.execute(
        update(Transaction)
        .where(
            Transaction.user_id == transaction.user_id,
            Transaction.merchant == transaction.merchant,
            Transaction.id != transaction.id,
            Transaction.is_transfer.is_(False),
            # Rows the user corrected themselves are left alone: either they already
            # say this category, or the user deliberately chose another one.
            or_(Transaction.category_source.is_(None), Transaction.category_source != USER_SOURCE),
        )
        .values(
            category=category,
            category_source=USER_SOURCE,
            confidence=USER_CONFIDENCE,
            needs_review=False,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def remember_user_category(db: Session, user_id: int, merchant: str, category: str) -> None:
    """Upsert the user's choice for a merchant. Unlike LLM answers, a user's choice
    always replaces whatever was cached, including an earlier choice of their own."""
    insert = dialect_insert(db)
    statement = insert(MerchantCategory).values(
        user_id=user_id,
        merchant=merchant,
        category=category,
        source=USER_SOURCE,
        confidence=USER_CONFIDENCE,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "merchant"],
            set_={"category": category, "source": USER_SOURCE, "confidence": USER_CONFIDENCE},
        )
    )


def _mark_corrected(transaction: Transaction, category: str) -> None:
    transaction.category = category
    transaction.category_source = USER_SOURCE
    transaction.confidence = USER_CONFIDENCE
    transaction.needs_review = False
