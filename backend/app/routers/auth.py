from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..deps import CurrentUser, DbSession
from ..models import User
from ..schemas import Token, UserCreate, UserOut
from ..security import (
    create_access_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: DbSession) -> User:
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # The unique constraint on email also covers two sign-ups racing each other.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """OAuth2 password flow: send the email as `username`, as a form body."""
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None:
        verify_dummy_password(form.password)
        valid = False
    else:
        valid = verify_password(form.password, user.password_hash)
    if not valid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
