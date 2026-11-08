import csv
from decimal import InvalidOperation
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..adapters.base import ParsedTransaction
from ..adapters.rbc_credit_card import RBCCreditCardAdapter
from ..deps import CurrentUser, DbSession
from ..models import Transaction, Upload
from ..schemas import UploadResult
from .accounts import get_owned_account

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB is far more than a year of card statements

# The adapter raises ValueError for rows it understands but rejects. A file that is not
# an RBC export at all fails in other ways (a missing column, an amount that is not a
# number, a mangled quote), and those are the user's file being wrong too, not a 500.
PARSE_ERRORS = (ValueError, KeyError, TypeError, AttributeError, InvalidOperation, csv.Error)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)


def read_csv_text(file: UploadFile) -> str:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise bad_request(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        # utf-8-sig also accepts the byte-order mark Excel adds when saving a CSV.
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise bad_request("File is not valid UTF-8 text; upload the CSV exported by your bank")


def parse_statement(csv_text: str) -> list[ParsedTransaction]:
    try:
        parsed = RBCCreditCardAdapter().parse(csv_text)
    except KeyError as exc:
        raise bad_request(f"Not an RBC credit card CSV: missing column {exc}")
    except PARSE_ERRORS as exc:
        raise bad_request(f"Could not read the statement: {exc}")
    if not parsed:
        raise bad_request("The file contains no transactions")
    return parsed


def insert_new_transactions(db: Session, rows: list[dict]) -> int:
    """Insert rows, silently skipping any whose (account_id, row_hash) already exists.

    Returns how many were actually inserted.
    """
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(Transaction)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["account_id", "row_hash"])
        .returning(Transaction.id)
    )
    return len(db.execute(statement).all())


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def create_upload(
    db: DbSession,
    user: CurrentUser,
    account_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File(description="CSV statement export")],
) -> UploadResult:
    account = get_owned_account(db, user.id, account_id)
    parsed = parse_statement(read_csv_text(file))

    upload = Upload(
        user_id=user.id,
        account_id=account.id,
        filename=(file.filename or "upload.csv")[:255],
    )
    db.add(upload)
    db.flush()

    inserted = insert_new_transactions(
        db,
        [
            {
                "user_id": user.id,
                "account_id": account.id,
                "upload_id": upload.id,
                "posted_date": row.posted_date,
                "amount_cents": row.amount_cents,
                "raw_description": row.raw_description,
                "is_transfer": row.is_transfer,
                "row_hash": row.row_hash,
            }
            for row in parsed
        ],
    )

    upload.status = "completed"
    upload.row_count = inserted
    db.commit()

    return UploadResult(
        upload_id=upload.id,
        account_id=account.id,
        inserted=inserted,
        skipped_duplicates=len(parsed) - inserted,
        total_rows=len(parsed),
    )
