"""Read-only spending queries over one user's transactions.

Plain functions taking (db, user_id, filters) and returning dataclasses, with no HTTP
in them, so the dashboard routes and a future assistant can call the same code.

Rules shared by every query:
- Money is integer cents. Spending is positive and refunds are negative, so a refund
  reduces whichever total it falls under.
- Transfers (card payments) are never spending and are always left out.
- Only user_id's rows are read, even if filters name another user's account.
- Everything runs on both Postgres and SQLite: no dialect-specific date functions.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .models import Transaction

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class Filters:
    """Which transactions to include. Dates are inclusive; None means unbounded."""

    start: date | None = None
    end: date | None = None
    account_id: int | None = None

    def __post_init__(self):
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must be on or after start")


@dataclass(frozen=True)
class Summary:
    total_spent_cents: int
    transaction_count: int
    needs_review_count: int
    first_date: date | None
    last_date: date | None


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    total_cents: int
    transaction_count: int
    share: float  # fraction of the overall total; 0.0 when the overall total is <= 0


@dataclass(frozen=True)
class MonthTotal:
    month: str  # "YYYY-MM"
    total_cents: int
    transaction_count: int


@dataclass(frozen=True)
class MerchantTotal:
    merchant: str
    total_cents: int
    transaction_count: int


def _conditions(user_id: int, filters: Filters) -> list[ColumnElement[bool]]:
    conditions = [Transaction.user_id == user_id, Transaction.is_transfer.is_(False)]
    if filters.start:
        conditions.append(Transaction.posted_date >= filters.start)
    if filters.end:
        conditions.append(Transaction.posted_date <= filters.end)
    if filters.account_id is not None:
        conditions.append(Transaction.account_id == filters.account_id)
    return conditions


_TOTAL = func.coalesce(func.sum(Transaction.amount_cents), 0)
_COUNT = func.count(Transaction.id)


def spending_summary(db: Session, user_id: int, filters: Filters = Filters()) -> Summary:
    total, count, review, first, last = db.execute(
        select(
            _TOTAL,
            _COUNT,
            func.coalesce(func.sum(case((Transaction.needs_review.is_(True), 1), else_=0)), 0),
            func.min(Transaction.posted_date),
            func.max(Transaction.posted_date),
        ).where(*_conditions(user_id, filters))
    ).one()
    return Summary(
        total_spent_cents=int(total),
        transaction_count=int(count),
        needs_review_count=int(review),
        first_date=first,
        last_date=last,
    )


def spending_by_category(
    db: Session, user_id: int, filters: Filters = Filters()
) -> list[CategoryTotal]:
    category = func.coalesce(Transaction.category, UNCATEGORIZED)
    rows = db.execute(
        select(category, _TOTAL, _COUNT)
        .where(*_conditions(user_id, filters))
        .group_by(category)
    ).all()
    overall = sum(int(total) for _, total, _ in rows)
    totals = [
        CategoryTotal(
            category=name,
            total_cents=int(total),
            transaction_count=int(count),
            # With refunds exceeding spending the overall total can be zero or negative,
            # and a share of that means nothing.
            share=int(total) / overall if overall > 0 else 0.0,
        )
        for name, total, count in rows
    ]
    return sorted(totals, key=lambda t: (-t.total_cents, t.category))


def spending_by_month(
    db: Session, user_id: int, filters: Filters = Filters()
) -> list[MonthTotal]:
    """One entry per month from the start of the range (or the first transaction) to
    the end of the range (or the last transaction), with empty months as zero."""
    year = extract("year", Transaction.posted_date)
    month = extract("month", Transaction.posted_date)
    rows = db.execute(
        select(year, month, _TOTAL, _COUNT)
        .where(*_conditions(user_id, filters))
        .group_by(year, month)
    ).all()
    # Postgres returns EXTRACT as a decimal, SQLite as an int.
    found = {(int(y), int(m)): (int(total), int(count)) for y, m, total, count in rows}

    first = (filters.start.year, filters.start.month) if filters.start else min(found, default=None)
    last = (filters.end.year, filters.end.month) if filters.end else max(found, default=None)
    if first is None or last is None:
        return []

    months = []
    y, m = first
    while (y, m) <= last:
        total, count = found.get((y, m), (0, 0))
        months.append(MonthTotal(month=f"{y:04d}-{m:02d}", total_cents=total, transaction_count=count))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def top_merchants(
    db: Session, user_id: int, filters: Filters = Filters(), limit: int = 10
) -> list[MerchantTotal]:
    # Rows from before categorization have no merchant; fall back to the raw text.
    merchant = func.coalesce(Transaction.merchant, Transaction.raw_description)
    total = _TOTAL.label("total")
    rows = db.execute(
        select(merchant, total, _COUNT)
        .where(*_conditions(user_id, filters))
        .group_by(merchant)
        .order_by(total.desc(), merchant)
        .limit(limit)
    ).all()
    return [
        MerchantTotal(merchant=name, total_cents=int(total), transaction_count=int(count))
        for name, total, count in rows
    ]
