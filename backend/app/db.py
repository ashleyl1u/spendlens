import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Parent class for every table; its metadata is what Alembic compares against."""


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    # We use the psycopg 3 driver, so a plain postgresql:// URL needs the driver name.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_database_url(), pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def dialect_insert(session: Session):
    """The INSERT construct for the session's database, which supports ON CONFLICT.

    Postgres runs the app and SQLite runs the tests; both have ON CONFLICT, but
    SQLAlchemy exposes it per dialect.
    """
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert
