"""Tests for accounts, statement uploads and the transaction list, against in-memory SQLite."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction, Upload
from app.routers.uploads import MAX_UPLOAD_BYTES

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"
FIXTURE_ROWS = 24


def sign_up(client, email):
    password = "correct-horse"
    client.post("/auth/register", json={"email": email, "password": password})
    token = client.post(
        "/auth/login", data={"username": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_account(client, headers, nickname="RBC Mastercard"):
    response = client.post(
        "/accounts", json={"nickname": nickname, "last4": "4444"}, headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


def upload(client, headers, account_id, content=None, filename="march.csv"):
    content = FIXTURE.read_bytes() if content is None else content
    return client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": (filename, content, "text/csv")},
        headers=headers,
    )


@pytest.fixture()
def alice(client):
    return sign_up(client, "alice@example.com")


@pytest.fixture()
def bob(client):
    return sign_up(client, "bob@example.com")


# --- accounts ---------------------------------------------------------------


def test_create_and_list_accounts(client, alice):
    account_id = create_account(client, alice, "Visa")

    accounts = client.get("/accounts", headers=alice).json()
    assert [(a["id"], a["nickname"], a["last4"], a["currency"]) for a in accounts] == [
        (account_id, "Visa", "4444", "CAD")
    ]


def test_full_card_number_is_rejected(client, alice):
    response = client.post(
        "/accounts",
        json={"nickname": "Visa", "last4": "5555555555554444"},
        headers=alice,
    )
    assert response.status_code == 422


@pytest.mark.parametrize("method, path", [("get", "/accounts"), ("post", "/uploads"),
                                          ("get", "/transactions")])
def test_endpoints_require_auth(client, method, path):
    assert getattr(client, method)(path).status_code == 401


# --- uploads ----------------------------------------------------------------


def test_upload_inserts_every_row(client, alice, engine):
    account_id = create_account(client, alice)
    response = upload(client, alice, account_id)

    assert response.status_code == 201
    body = response.json()
    assert body["account_id"] == account_id
    assert (body["inserted"], body["skipped_duplicates"], body["total_rows"]) == (
        FIXTURE_ROWS, 0, FIXTURE_ROWS
    )

    with Session(engine) as db:
        stored = db.scalar(select(func.count()).select_from(Transaction))
        record = db.get(Upload, body["upload_id"])
    assert stored == FIXTURE_ROWS
    assert (record.filename, record.status, record.row_count) == (
        "march.csv", "completed", FIXTURE_ROWS
    )


def test_reuploading_the_same_file_inserts_nothing(client, alice, engine):
    account_id = create_account(client, alice)
    upload(client, alice, account_id)
    second = upload(client, alice, account_id).json()

    assert (second["inserted"], second["skipped_duplicates"], second["total_rows"]) == (
        0, FIXTURE_ROWS, FIXTURE_ROWS
    )
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == FIXTURE_ROWS


def test_overlapping_file_inserts_only_the_new_rows(client, alice):
    account_id = create_account(client, alice)
    lines = FIXTURE.read_text().splitlines(keepends=True)
    header, rows = lines[0], lines[1:]
    upload(client, alice, account_id, "".join([header, *rows[:10]]).encode())

    body = upload(client, alice, account_id).json()
    assert (body["inserted"], body["skipped_duplicates"]) == (FIXTURE_ROWS - 10, 10)


def test_same_file_into_a_second_account_is_not_a_duplicate(client, alice):
    first = create_account(client, alice, "Card one")
    second = create_account(client, alice, "Card two")
    upload(client, alice, first)

    assert upload(client, alice, second).json()["inserted"] == FIXTURE_ROWS


@pytest.mark.parametrize(
    "content, message",
    [
        (b"\xff\xfe\x00not utf-8", "UTF-8"),
        (b"Date,Amount\n2024-03-05,3.12\n", "missing column"),
        (
            b"Transaction Date,Description 1,CAD$\n03/05/2024,TIM HORTONS,\n",
            "no CAD$ amount",
        ),
        (b"Transaction Date,Description 1,CAD$\nyesterday,TIM HORTONS,-3.12\n", "Could not"),
        (b"Transaction Date,Description 1,CAD$\n03/05/2024,TIM HORTONS,lots\n", "Could not"),
        (b"", "no transactions"),
    ],
)
def test_bad_file_is_rejected_with_400(client, alice, engine, content, message):
    account_id = create_account(client, alice)
    response = upload(client, alice, account_id, content)

    assert response.status_code == 400
    assert message in response.json()["detail"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Upload)) == 0
        assert db.scalar(select(func.count()).select_from(Transaction)) == 0


def test_oversized_file_is_rejected(client, alice):
    account_id = create_account(client, alice)
    response = upload(client, alice, account_id, b"x" * (MAX_UPLOAD_BYTES + 1))

    assert response.status_code == 400
    assert "larger than" in response.json()["detail"]


def test_upload_into_missing_account_is_404(client, alice):
    assert upload(client, alice, 999).status_code == 404


# --- transactions -----------------------------------------------------------


def test_transactions_are_newest_first_and_paginated(client, alice):
    account_id = create_account(client, alice)
    upload(client, alice, account_id)

    first = client.get("/transactions?limit=5", headers=alice).json()
    assert first["total"] == FIXTURE_ROWS
    assert len(first["items"]) == 5
    assert first["items"][0]["posted_date"] == "2024-04-07"
    dates = [t["posted_date"] for t in first["items"]]
    assert dates == sorted(dates, reverse=True)

    seen = []
    for offset in range(0, FIXTURE_ROWS, 5):
        page = client.get(f"/transactions?limit=5&offset={offset}", headers=alice).json()
        seen += [t["id"] for t in page["items"]]
    assert len(seen) == len(set(seen)) == FIXTURE_ROWS


def test_transaction_amounts_are_cents(client, alice):
    account_id = create_account(client, alice)
    upload(client, alice, account_id)

    items = client.get("/transactions?limit=200", headers=alice).json()["items"]
    payment = next(t for t in items if t["is_transfer"])
    assert payment["amount_cents"] == -15000


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_bad_pagination_is_rejected(client, alice, query):
    assert client.get(f"/transactions?{query}", headers=alice).status_code == 422


# --- data isolation ---------------------------------------------------------


def test_users_cannot_see_or_touch_each_others_data(client, alice, bob, engine):
    alice_account = create_account(client, alice, "Alice's card")
    upload(client, alice, alice_account)

    # Bob sees none of Alice's accounts or transactions.
    assert client.get("/accounts", headers=bob).json() == []
    bob_view = client.get("/transactions", headers=bob).json()
    assert (bob_view["total"], bob_view["items"]) == (0, [])

    # Bob cannot upload into Alice's account, and gets the same 404 as a missing one.
    response = upload(client, bob, alice_account)
    assert response.status_code == 404
    assert response.json() == upload(client, bob, 999).json()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Upload)) == 1

    # Bob's own upload is his alone; Alice still sees only her rows.
    bob_account = create_account(client, bob, "Bob's card")
    assert upload(client, bob, bob_account).json()["inserted"] == FIXTURE_ROWS
    assert [a["id"] for a in client.get("/accounts", headers=alice).json()] == [alice_account]
    alice_items = client.get("/transactions?limit=200", headers=alice).json()["items"]
    assert len(alice_items) == FIXTURE_ROWS
    assert {t["account_id"] for t in alice_items} == {alice_account}
