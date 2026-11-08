"""Shared fixtures: an in-memory SQLite database and an API client wired to it."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, make_engine
from app.categorization.providers import FakeProvider
from app.deps import get_db, get_llm_provider
from app.main import app

SECRET = "test-secret-that-is-long-enough-for-hs256"


@pytest.fixture()
def engine():
    # Set TEST_DATABASE_URL to an empty, throwaway Postgres database to run the API tests
    # against Postgres instead of SQLite. Its tables are dropped after every test.
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        engine = make_engine(test_url.replace("postgresql://", "postgresql+psycopg://", 1))
    else:
        # StaticPool keeps one connection, so every request sees the same in-memory database.
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(engine)
    yield engine
    if test_url:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def provider():
    """The provider every request in a test shares, so tests can count its calls."""
    return FakeProvider()


@pytest.fixture()
def client(engine, provider, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    # The app checks LLM_PROVIDER at startup; tests never use a real provider.
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    def override_get_db():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: provider
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
