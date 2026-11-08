"""Password hashing and JWT access tokens."""

import os
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

ALGORITHM = "HS256"
DEFAULT_TOKEN_MINUTES = 60
# HS256 keys shorter than this are easy to brute-force, so refuse to start with one.
MIN_SECRET_LENGTH = 32

_password_hash = PasswordHash.recommended()  # Argon2id


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


# Hashed once so a login for an unknown email still spends the time of a real check,
# which keeps response timing from revealing which emails have accounts.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def verify_dummy_password(password: str) -> None:
    _password_hash.verify(password, _DUMMY_HASH)


def get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set")
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    return secret


def get_token_lifetime() -> timedelta:
    minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", DEFAULT_TOKEN_MINUTES))
    return timedelta(minutes=minutes)


def create_access_token(user_id: int, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + get_token_lifetime(),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id inside a valid token, or None if it is invalid or expired."""
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError):
        return None
