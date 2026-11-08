from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ..deps import CurrentUser, DbSession
from ..models import Transaction
from ..schemas import TransactionPage

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionPage)
def list_transactions(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPage:
    owned = Transaction.user_id == user.id
    total = db.scalar(select(func.count()).select_from(Transaction).where(owned))
    items = db.scalars(
        select(Transaction)
        .where(owned)
        # id breaks ties between same-day rows so pages never overlap or skip a row.
        .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TransactionPage(items=items, total=total, limit=limit, offset=offset)
