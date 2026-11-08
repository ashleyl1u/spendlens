"""Tests for sign-up, login and the current-user dependency, against in-memory SQLite."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.security import ALGORITHM, create_access_token


def register(client, email="a@example.com", password="correct-horse"):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client, email="a@example.com", password="correct-horse"):
    return client.post("/auth/login", data={"username": email, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_user_without_password(client):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "a@example.com"
    assert set(body) == {"id", "email", "created_at"}


def test_password_is_stored_hashed(client, engine):
    register(client, password="correct-horse")

    with Session(engine) as db:
        user = db.scalars(select(User)).one()
    assert user.password_hash != "correct-horse"
    assert user.password_hash.startswith("$argon2")


def test_email_is_lowercased(client):
    register(client, email="Mixed@Example.COM")

    assert login(client, email="mixed@example.com").status_code == 200
    assert login(client, email="MIXED@example.com").status_code == 200


def test_duplicate_email_is_rejected(client):
    register(client)
    response = register(client, email="A@example.com")

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "correct-horse"},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com"},
    ],
)
def test_invalid_registration_is_rejected(client, payload):
    assert client.post("/auth/register", json=payload).status_code == 422


def test_login_and_fetch_me(client):
    register(client)
    response = login(client)

    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"

    me = client.get("/auth/me", headers=auth_header(token["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


@pytest.mark.parametrize(
    "email, password",
    [("a@example.com", "wrong-password"), ("nobody@example.com", "correct-horse")],
)
def test_bad_login_gets_the_same_401(client, email, password):
    register(client)
    response = login(client, email=email, password=password)

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_me_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_rejects_a_garbage_token(client):
    assert client.get("/auth/me", headers=auth_header("not.a.jwt")).status_code == 401


def test_me_rejects_an_expired_token(client):
    user_id = register(client).json()["id"]
    long_ago = datetime.now(timezone.utc) - timedelta(days=1)
    token = create_access_token(user_id, now=long_ago)

    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401


def test_me_rejects_a_token_signed_with_another_secret(client):
    register(client)
    payload = {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    forged = jwt.encode(payload, "some-other-secret-that-is-also-long", algorithm=ALGORITHM)

    assert client.get("/auth/me", headers=auth_header(forged)).status_code == 401


def test_me_rejects_a_token_for_a_deleted_user(client, engine):
    register(client)
    token = login(client).json()["access_token"]
    with Session(engine) as db:
        db.delete(db.scalars(select(User)).one())
        db.commit()

    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401


def test_short_jwt_secret_is_refused(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(RuntimeError):
        create_access_token(1)
