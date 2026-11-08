"""Read-only spending dashboards. The numbers come from app.queries."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import queries
from ..deps import CurrentUser, DbSession
from .accounts import get_owned_account

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_filters(
    db: DbSession,
    user: CurrentUser,
    start: Annotated[date | None, Query(description="First day to include (YYYY-MM-DD)")] = None,
    end: Annotated[date | None, Query(description="Last day to include (YYYY-MM-DD)")] = None,
    account_id: Annotated[int | None, Query(description="Only this account")] = None,
) -> queries.Filters:
    if start and end and end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end must be on or after start")
    if account_id is not None:
        get_owned_account(db, user.id, account_id)  # 404 unless it is the user's
    return queries.Filters(start=start, end=end, account_id=account_id)


Filters = Annotated[queries.Filters, Depends(get_filters)]


@router.get("/summary", response_model=queries.Summary)
def summary(db: DbSession, user: CurrentUser, filters: Filters) -> queries.Summary:
    return queries.spending_summary(db, user.id, filters)


@router.get("/by-category", response_model=list[queries.CategoryTotal])
def by_category(db: DbSession, user: CurrentUser, filters: Filters) -> list[queries.CategoryTotal]:
    return queries.spending_by_category(db, user.id, filters)


@router.get("/by-month", response_model=list[queries.MonthTotal])
def by_month(db: DbSession, user: CurrentUser, filters: Filters) -> list[queries.MonthTotal]:
    return queries.spending_by_month(db, user.id, filters)


@router.get("/top-merchants", response_model=list[queries.MerchantTotal])
def top_merchants(
    db: DbSession,
    user: CurrentUser,
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[queries.MerchantTotal]:
    return queries.top_merchants(db, user.id, filters, limit)
