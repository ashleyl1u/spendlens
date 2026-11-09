"""Tests for category corrections (PATCH /transactions/{id}) and the review filters."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categorization import corrections
from app.categorization.pipeline import _remember
from app.categorization.providers import Result
from app.models import Account, MerchantCategory, Transaction, User

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"
HEADER = ("Account Type,Account Number,Transaction Date,Cheque Number,Description 1,"
          "Description 2,CAD$,USD$\n")


# --- helpers --------------------------------------------------------------------


def sign_up(client, email):
    client.post("/auth/register", json={"email": email, "password": "correct-horse"})
    token = client.post(
        "/auth/login", data={"username": email, "password": "correct-horse"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload(client, headers, content=None, account_id=None):
    if account_id is None:
        account_id = client.post(
            "/accounts", json={"nickname": "Visa"}, headers=headers
        ).json()["id"]
    response = client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": ("statement.csv", content or FIXTURE.read_bytes(), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return account_id


def statement(*rows):
    """A small RBC statement: rows of (M/D/YYYY, description, CAD$)."""
    lines = [f"MasterCard,1,{d},,{desc},,{amount}," for d, desc, amount in rows]
    return (HEADER + "\n".join(lines) + "\n").encode()


def transactions(client, headers, **params):
    response = client.get("/transactions", params={"limit": 200, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def rows_for(client, headers, merchant):
    return [t for t in transactions(client, headers)["items"] if t["merchant"] == merchant]


def correct(client, headers, transaction_id, category, **body):
    return client.patch(
        f"/transactions/{transaction_id}", json={"category": category, **body}, headers=headers
    )


def cache(engine, email):
    with Session(engine) as db:
        return {
            row.merchant: (row.category, row.source, row.confidence)
            for row in db.scalars(
                select(MerchantCategory).join(User, User.id == MerchantCategory.user_id)
                .where(User.email == email)
            )
        }


@pytest.fixture()
def alice(client):
    headers = sign_up(client, "alice@example.com")
    upload(client, headers)
    return headers


# --- correcting one transaction -----------------------------------------------------


def test_correction_updates_the_row_and_the_cache(client, alice, engine):
    (books,) = rows_for(client, alice, "MAPLE STREET BOOKS CO")
    assert (books["category"], books["category_source"]) == ("Shopping", "llm")

    response = correct(client, alice, books["id"], "Entertainment")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == books["id"]
    assert (body["category"], body["category_source"], body["confidence"],
            body["needs_review"]) == ("Entertainment", "user", 1.0, False)
    assert body["also_updated"] == 0  # the only row from this merchant
    assert body["raw_description"] == books["raw_description"]

    (stored,) = rows_for(client, alice, "MAPLE STREET BOOKS CO")
    assert (stored["category"], stored["category_source"]) == ("Entertainment", "user")
    # The provider's earlier answer in the cache is replaced by the user's choice.
    assert cache(engine, "alice@example.com")["MAPLE STREET BOOKS CO"] == (
        "Entertainment", "user", 1.0
    )


def test_correction_clears_needs_review(client, alice):
    (rfbt,) = transactions(client, alice, needs_review=True)["items"]
    assert rfbt["merchant"] == "RFBT-TORONTO YONGE ST"

    correct(client, alice, rfbt["id"], "Dining")
    assert transactions(client, alice, needs_review=True)["total"] == 0


def test_correcting_again_replaces_the_earlier_correction(client, alice, engine):
    (books,) = rows_for(client, alice, "MAPLE STREET BOOKS CO")
    correct(client, alice, books["id"], "Entertainment")
    correct(client, alice, books["id"], "Other")

    assert rows_for(client, alice, "MAPLE STREET BOOKS CO")[0]["category"] == "Other"
    assert cache(engine, "alice@example.com")["MAPLE STREET BOOKS CO"][:2] == ("Other", "user")


def test_correction_without_a_merchant_skips_the_cache(client, alice, engine):
    with Session(engine) as db:
        row = db.scalars(select(Transaction).where(Transaction.merchant == "CHIPOTLE")).one()
        row.merchant = None
        db.commit()
        row_id = row.id
    before = cache(engine, "alice@example.com")

    response = correct(client, alice, row_id, "Groceries")

    assert response.status_code == 200
    assert response.json()["also_updated"] == 0
    assert cache(engine, "alice@example.com") == before


# --- apply_to_merchant ------------------------------------------------------------------


def test_apply_to_merchant_true_updates_the_other_rows(client, alice):
    tims = rows_for(client, alice, "TIM HORTONS")
    assert len(tims) == 3

    response = correct(client, alice, tims[0]["id"], "Groceries")  # default is true

    assert response.json()["also_updated"] == 2
    assert {(t["category"], t["category_source"], t["confidence"], t["needs_review"])
            for t in rows_for(client, alice, "TIM HORTONS")} == {("Groceries", "user", 1.0, False)}


def test_apply_to_merchant_false_updates_only_that_row(client, alice, engine):
    tims = rows_for(client, alice, "TIM HORTONS")

    response = correct(client, alice, tims[0]["id"], "Groceries", apply_to_merchant=False)

    assert response.json()["also_updated"] == 0
    categories = {t["id"]: t["category"] for t in rows_for(client, alice, "TIM HORTONS")}
    assert categories[tims[0]["id"]] == "Groceries"
    assert [c for i, c in categories.items() if i != tims[0]["id"]] == ["Dining", "Dining"]
    # The merchant is still remembered for future uploads.
    assert cache(engine, "alice@example.com")["TIM HORTONS"][:2] == ("Groceries", "user")


def test_rows_the_user_already_corrected_are_left_alone(client, alice):
    first, second, third = rows_for(client, alice, "TIM HORTONS")
    correct(client, alice, first["id"], "Entertainment", apply_to_merchant=False)

    response = correct(client, alice, second["id"], "Groceries")

    # Only the third row changes; the first keeps the user's own earlier choice.
    assert response.json()["also_updated"] == 1
    categories = {t["id"]: t["category"] for t in rows_for(client, alice, "TIM HORTONS")}
    assert categories == {first["id"]: "Entertainment", second["id"]: "Groceries",
                          third["id"]: "Groceries"}


def test_other_merchants_are_untouched(client, alice):
    before = {t["id"]: t["category"] for t in transactions(client, alice)["items"]
              if t["merchant"] != "TIM HORTONS"}
    correct(client, alice, rows_for(client, alice, "TIM HORTONS")[0]["id"], "Groceries")
    after = {t["id"]: t["category"] for t in transactions(client, alice)["items"]
             if t["merchant"] != "TIM HORTONS"}
    assert after == before


def test_apply_to_merchant_never_touches_transfers(engine):
    """Same-merchant transfers cannot come from the RBC adapter, so build one directly."""
    with Session(engine) as db:
        user = User(email="a@example.com", password_hash="x")
        db.add(user)
        db.flush()
        account = Account(user_id=user.id, bank="RBC", nickname="Visa")
        db.add(account)
        db.flush()

        def row(i, transfer):
            return Transaction(user_id=user.id, account_id=account.id, posted_date=date(2024, 3, 1),
                               amount_cents=100, raw_description="X", merchant="ACME",
                               category="Transfer" if transfer else "Other",
                               is_transfer=transfer, row_hash=f"h{i}")

        target, other, transfer = row(1, False), row(2, False), row(3, True)
        db.add_all([target, other, transfer])
        db.flush()

        assert corrections.correct_transaction(db, target, "Shopping") == 1
        db.commit()
        db.refresh(transfer)
        db.refresh(other)
        assert other.category == "Shopping"
        assert transfer.category == "Transfer"


# --- future uploads ----------------------------------------------------------------


def test_later_uploads_use_the_correction_not_rules_or_provider(client, alice, provider):
    metro = rows_for(client, alice, "METRO")[0]  # a rule merchant (Groceries)
    rfbt = rows_for(client, alice, "RFBT-TORONTO YONGE ST")[0]  # a provider merchant
    correct(client, alice, metro["id"], "Shopping")
    correct(client, alice, rfbt["id"], "Entertainment")
    calls_before = len(provider.calls)

    # New rows from both merchants, in a second account so they are not duplicates.
    upload(client, alice, statement(
        ("5/2/2024", "METRO #417 MISSISSAUGA", "-12.00"),
        ("5/3/2024", "*RFBT-TORONTO YONGE ST TORONTO", "-6.50"),
    ))

    assert len(provider.calls) == calls_before  # nothing was sent to the provider
    new = {t["merchant"]: t for t in transactions(client, alice)["items"]
           if t["posted_date"].startswith("2024-05")}
    assert (new["METRO"]["category"], new["METRO"]["category_source"]) == ("Shopping", "cache")
    assert new["RFBT-TORONTO YONGE ST"]["category"] == "Entertainment"
    assert new["RFBT-TORONTO YONGE ST"]["needs_review"] is False


def test_provider_answers_never_overwrite_a_correction(client, alice, engine):
    books = rows_for(client, alice, "MAPLE STREET BOOKS CO")[0]
    correct(client, alice, books["id"], "Entertainment")

    with Session(engine) as db:
        alice_id = db.scalar(select(User.id).where(User.email == "alice@example.com"))
        _remember(db, alice_id, {"MAPLE STREET BOOKS CO": Result("Shopping", 0.99)})
        db.commit()

    assert cache(engine, "alice@example.com")["MAPLE STREET BOOKS CO"][:2] == (
        "Entertainment", "user"
    )


# --- isolation ----------------------------------------------------------------------


def test_user_b_cannot_read_or_change_user_as_transactions(client, alice, engine):
    bob = sign_up(client, "bob@example.com")
    alices_row = rows_for(client, alice, "METRO")[0]

    assert transactions(client, bob)["total"] == 0
    response = correct(client, bob, alices_row["id"], "Shopping")
    assert response.status_code == 404
    assert response.json() == correct(client, bob, 999_999, "Shopping").json()

    # Alice's row and cache are unchanged, and Bob has no cache entries.
    assert rows_for(client, alice, "METRO")[0]["category"] == "Groceries"
    assert "METRO" not in cache(engine, "alice@example.com")  # rule results aren't cached
    assert cache(engine, "bob@example.com") == {}


def test_a_correction_by_a_does_not_change_b(client, alice, engine, provider):
    bob = sign_up(client, "bob@example.com")
    upload(client, bob)
    correct(client, alice, rows_for(client, alice, "METRO")[0]["id"], "Shopping")
    correct(client, alice, rows_for(client, alice, "MAPLE STREET BOOKS CO")[0]["id"], "Other")

    assert {t["category"] for t in rows_for(client, bob, "METRO")} == {"Groceries"}
    assert rows_for(client, bob, "MAPLE STREET BOOKS CO")[0]["category"] == "Shopping"
    assert cache(engine, "bob@example.com")["MAPLE STREET BOOKS CO"][1] == "llm"

    # Bob's next upload of the merchant still uses the rule, not Alice's correction.
    upload(client, bob, statement(("5/2/2024", "METRO #417 MISSISSAUGA", "-12.00")))
    new = [t for t in rows_for(client, bob, "METRO") if t["posted_date"] == "2024-05-02"]
    assert (new[0]["category"], new[0]["category_source"]) == ("Groceries", "rule")


# --- validation ------------------------------------------------------------------------


@pytest.mark.parametrize("category", ["Pizza", "dining", "Transfer", "", None, 3])
def test_invalid_category_is_a_422(client, alice, category):
    row = rows_for(client, alice, "METRO")[0]
    assert correct(client, alice, row["id"], category).status_code == 422
    assert rows_for(client, alice, "METRO")[0]["category"] == "Groceries"


def test_missing_body_fields_are_a_422(client, alice):
    row = rows_for(client, alice, "METRO")[0]
    response = client.patch(f"/transactions/{row['id']}", json={}, headers=alice)
    assert response.status_code == 422


def test_transfer_is_a_400(client, alice, engine):
    (payment,) = [t for t in transactions(client, alice)["items"] if t["is_transfer"]]
    before = cache(engine, "alice@example.com")

    response = correct(client, alice, payment["id"], "Other")

    assert response.status_code == 400
    assert "can't be recategorized" in response.json()["detail"]
    after = [t for t in transactions(client, alice)["items"] if t["is_transfer"]][0]
    assert (after["category"], after["category_source"]) == ("Transfer", "rule")
    assert cache(engine, "alice@example.com") == before


def test_auth_is_required(client, alice):
    row = rows_for(client, alice, "METRO")[0]
    assert client.patch(f"/transactions/{row['id']}", json={"category": "Other"}).status_code == 401


def test_a_failure_part_way_changes_nothing(client, alice, engine, monkeypatch):
    """The row, the cache and the other rows are written in one database transaction."""
    tims = rows_for(client, alice, "TIM HORTONS")
    before_cache = cache(engine, "alice@example.com")

    def broken(db, user_id, merchant, category):
        raise RuntimeError("cache write failed")

    monkeypatch.setattr(corrections, "remember_user_category", broken)
    with pytest.raises(RuntimeError):
        correct(client, alice, tims[0]["id"], "Groceries")

    assert {t["category"] for t in rows_for(client, alice, "TIM HORTONS")} == {"Dining"}
    assert cache(engine, "alice@example.com") == before_cache


# --- list filters -----------------------------------------------------------------------


def test_needs_review_filter(client, alice):
    flagged = transactions(client, alice, needs_review=True)
    assert flagged["total"] == 1
    assert flagged["items"][0]["merchant"] == "RFBT-TORONTO YONGE ST"
    assert transactions(client, alice, needs_review=False)["total"] == 23
    assert transactions(client, alice)["total"] == 24


def test_category_filter_and_pagination(client, alice):
    dining = transactions(client, alice, category="Dining")
    # Tim Hortons x3, Corner Bakery, Lakeview Pub, RFBT, McDonald's x2, Chipotle, Garden Dumpling
    assert dining["total"] == 10
    assert {t["category"] for t in dining["items"]} == {"Dining"}

    page = transactions(client, alice, category="Dining", limit=3, offset=9)
    assert (page["total"], len(page["items"])) == (10, 1)

    combined = transactions(client, alice, category="Dining", needs_review=True)
    assert [t["merchant"] for t in combined["items"]] == ["RFBT-TORONTO YONGE ST"]


@pytest.mark.parametrize("category", ["Pizza", "dining", "Transfer"])
def test_invalid_category_filter_is_a_422(client, alice, category):
    response = client.get("/transactions", params={"category": category}, headers=alice)
    assert response.status_code == 422


def test_filters_stay_scoped_to_the_user(client, alice):
    bob = sign_up(client, "bob@example.com")
    assert transactions(client, bob, category="Dining")["total"] == 0
    assert transactions(client, bob, needs_review=True)["total"] == 0


# --- dashboard ------------------------------------------------------------------------


def test_dashboard_reflects_corrections(client, alice):
    def by_category():
        response = client.get("/dashboard/by-category", headers=alice)
        return {c["category"]: (c["total_cents"], c["transaction_count"]) for c in response.json()}

    before = by_category()
    assert before["Shopping"] == (1850, 3)  # books 1850, plus a 4520 purchase and its refund
    assert "Entertainment" not in before

    correct(client, alice, rows_for(client, alice, "MAPLE STREET BOOKS CO")[0]["id"],
            "Entertainment")

    after = by_category()
    assert after["Entertainment"] == (1850, 1)
    assert after["Shopping"] == (0, 2)
    # Moving money between categories leaves the overall total unchanged.
    assert sum(t for t, _ in after.values()) == sum(t for t, _ in before.values())

