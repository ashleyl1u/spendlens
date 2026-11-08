"""Checks that running the Alembic migration produces the tables the models describe."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db import Base

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def test_migration_creates_every_model_table(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {
        "alembic_version"
    }
    for name, table in Base.metadata.tables.items():
        migrated_columns = {column["name"] for column in inspector.get_columns(name)}
        assert migrated_columns == {column.name for column in table.columns}, name

    unique_columns = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("transactions")
    }
    assert ("account_id", "row_hash") in unique_columns
    engine.dispose()
