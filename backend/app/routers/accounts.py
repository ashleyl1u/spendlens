from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession
from ..models import Account
from ..schemas import AccountCreate, AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


def get_owned_account(db: DbSession, user_id: int, account_id: int) -> Account:
    """Return the account, or 404 if it does not exist or belongs to someone else.

    Both cases give the same 404 so one user cannot probe for another's account ids.
    """
    account = db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate, db: DbSession, user: CurrentUser) -> Account:
    account = Account(user_id=user.id, **body.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(db: DbSession, user: CurrentUser) -> list[Account]:
    return list(
        db.scalars(select(Account).where(Account.user_id == user.id).order_by(Account.id))
    )
