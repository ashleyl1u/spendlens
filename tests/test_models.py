"""Tests for the database models, run against an in-memory SQLite database."""

from datetime import date

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Transaction, Upload, User


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        # SQLite ignores foreign keys unless this is switched on for each connection.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def make_user(db, email="a@example.com"):
    user = User(email=email, password_hash="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def make_account(db, user, nickname="Visa"):
    account = Account(user_id=user.id, bank="RBC", nickname=nickname)
    db.add(account)
    db.flush()
    return account


def make_transaction(account, row_hash="h1", **overrides):
    values = dict(
        user_id=account.user_id,
        account_id=account.id,
        posted_date=date(2024, 3, 5),
        amount_cents=312,
        raw_description="TIM HORTONS #2210 TORONTO",
        row_hash=row_hash,
    )
    values.update(overrides)
    return Transaction(**values)


def test_same_row_hash_in_one_account_is_rejected(session):
    account = make_account(session, make_user(session))
    session.add(make_transaction(account, "h1"))
    session.flush()

    session.add(make_transaction(account, "h1"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_row_hash_in_different_accounts_is_allowed(session):
    user = make_user(session)
    first = make_account(session, user, "Visa")
    second = make_account(session, user, "Mastercard")

    session.add_all([make_transaction(first, "h1"), make_transaction(second, "h1")])
    session.flush()  # raises if the constraint were too strict


def test_amount_is_stored_as_integer_cents(session):
    account = make_account(session, make_user(session))
    session.add(make_transaction(account, amount_cents=549))
    session.commit()
    session.expire_all()

    stored = session.scalars(select(Transaction)).one()
    assert stored.amount_cents == 549
    assert isinstance(stored.amount_cents, int)


def test_flags_default_to_false(session):
    account = make_account(session, make_user(session))
    transaction = make_transaction(account)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    assert transaction.needs_review is False
    assert transaction.is_transfer is False


def test_email_must_be_unique(session):
    make_user(session, "a@example.com")
    with pytest.raises(IntegrityError):
        make_user(session, "a@example.com")


def test_deleting_a_user_deletes_their_data(session):
    user = make_user(session)
    account = make_account(session, user)
    session.add(make_transaction(account))
    session.add(Upload(user_id=user.id, account_id=account.id, filename="march.csv"))
    session.commit()

    session.delete(user)
    session.commit()

    for model in (Account, Upload, Transaction):
        assert session.scalar(select(func.count()).select_from(model)) == 0
