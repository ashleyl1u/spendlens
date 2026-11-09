from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from ..categorization.categories import CATEGORIES
from ..categorization.corrections import correct_transaction
from ..deps import CurrentUser, DbSession
from ..models import Transaction
from ..schemas import CorrectedTransaction, TransactionCorrection, TransactionOut, TransactionPage

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionPage)
def list_transactions(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    needs_review: Annotated[
        bool | None, Query(description="Only rows that do (true) or don't (false) need review")
    ] = None,
    category: Annotated[str | None, Query(description="Only rows in this category")] = None,
) -> TransactionPage:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"category must be one of: {', '.join(CATEGORIES)}",
        )
    conditions = [Transaction.user_id == user.id]
    if needs_review is not None:
        conditions.append(Transaction.needs_review.is_(needs_review))
    if category is not None:
        conditions.append(Transaction.category == category)

    total = db.scalar(select(func.count()).select_from(Transaction).where(*conditions))
    items = db.scalars(
        select(Transaction)
        .where(*conditions)
        # id breaks ties between same-day rows so pages never overlap or skip a row.
        .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TransactionPage(items=items, total=total, limit=limit, offset=offset)


@router.patch("/{transaction_id}", response_model=CorrectedTransaction)
def correct(
    transaction_id: int, body: TransactionCorrection, db: DbSession, user: CurrentUser
) -> CorrectedTransaction:
    """Set a transaction's category, remember it for the merchant, and (by default)
    apply it to the user's other transactions from the same merchant."""
    transaction = db.get(Transaction, transaction_id)
    # Same 404 whether it doesn't exist or belongs to someone else, so ids can't be probed.
    if transaction is None or transaction.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    if transaction.is_transfer:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Transfers such as card payments are not spending and can't be recategorized",
        )

    # The row, the cache and the other rows change together or not at all: nothing is
    # committed until everything has succeeded, and the session rolls back otherwise.
    also_updated = correct_transaction(db, transaction, body.category, body.apply_to_merchant)
    db.commit()
    db.refresh(transaction)
    return CorrectedTransaction(
        **TransactionOut.model_validate(transaction).model_dump(), also_updated=also_updated
    )
