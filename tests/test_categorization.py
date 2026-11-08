"""End-to-end tests for the categorization pipeline, through POST /uploads."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categorization.categories import CATEGORIES, TRANSFER
from app.categorization.pipeline import _remember, categorize_transactions
from app.categorization.providers import FakeProvider, Result
from app.models import MerchantCategory, Transaction, User

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"
FIXTURE_ROWS = 24
# Merchants in the fixture that no rule covers, so they go to the provider.
UNRULED = [
    "ACMECLOUD",
    "CA.SAMPLE-SHOP.COM",
    "GARDEN DUMPLING HO",
    "MAPLE STREET BOOKS CO",
    "RFBT-TORONTO YONGE ST",
]
UNRULED_ROWS = 6  # CA.SAMPLE-SHOP.COM appears twice (a purchase and its refund)
TRANSFER_ROWS = 1


def sign_up(client, email):
    client.post("/auth/register", json={"email": email, "password": "correct-horse"})
    token = client.post(
        "/auth/login", data={"username": email, "password": "correct-horse"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_account(client, headers, nickname="RBC Mastercard"):
    return client.post("/accounts", json={"nickname": nickname}, headers=headers).json()["id"]


def upload(client, headers, account_id):
    response = client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": ("march.csv", FIXTURE.read_bytes(), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def transactions(client, headers):
    return client.get("/transactions?limit=200", headers=headers).json()["items"]


def by_merchant(items):
    return {t["merchant"]: t for t in items}


def test_fixture_is_fully_categorized(client, provider):
    alice = sign_up(client, "alice@example.com")
    result = upload(client, alice, create_account(client, alice))

    assert result["categorized_by"] == {
        "rule": FIXTURE_ROWS - UNRULED_ROWS,
        "cache": 0,
        "llm": UNRULED_ROWS,
    }
    # One batched call, each unknown merchant sent once.
    assert provider.calls == [UNRULED]

    items = transactions(client, alice)
    assert len(items) == FIXTURE_ROWS
    for t in items:
        assert t["merchant"]
        assert t["category"] in (*CATEGORIES, TRANSFER)
        assert t["category_source"] in ("rule", "llm")
        assert 0 <= t["confidence"] <= 1
        assert t["needs_review"] == (t["confidence"] < 0.7)

    merchants = by_merchant(items)
    assert merchants["TIM HORTONS"]["category"] == "Dining"
    assert merchants["TIM HORTONS"]["category_source"] == "rule"
    assert merchants["PRESTO"]["category"] == "Transport"
    assert merchants["MAPLE STREET BOOKS CO"]["category"] == "Shopping"
    assert merchants["MAPLE STREET BOOKS CO"]["category_source"] == "llm"
    # The fake provider is unsure about this one, so it is flagged for review.
    assert merchants["RFBT-TORONTO YONGE ST"]["needs_review"] is True


def test_transfers_are_excluded(client, provider):
    alice = sign_up(client, "alice@example.com")
    upload(client, alice, create_account(client, alice))

    transfers = [t for t in transactions(client, alice) if t["is_transfer"]]
    assert len(transfers) == TRANSFER_ROWS
    payment = transfers[0]
    assert (payment["category"], payment["category_source"]) == (TRANSFER, "rule")
    assert payment["needs_review"] is False
    # The payment is never sent to the provider.
    sent = [merchant for call in provider.calls for merchant in call]
    assert not any("PAYMENT" in merchant for merchant in sent)


def test_second_upload_uses_the_cache_not_the_provider(client, provider):
    alice = sign_up(client, "alice@example.com")
    upload(client, alice, create_account(client, alice, "Card one"))
    assert len(provider.calls) == 1

    # The same statement into a second card: every row is new, every merchant is known.
    result = upload(client, alice, create_account(client, alice, "Card two"))

    assert len(provider.calls) == 1
    assert result["inserted"] == FIXTURE_ROWS
    assert result["categorized_by"] == {
        "rule": FIXTURE_ROWS - UNRULED_ROWS,
        "cache": UNRULED_ROWS,
        "llm": 0,
    }


def test_reupload_of_the_same_file_does_not_recategorize(client, provider, engine):
    alice = sign_up(client, "alice@example.com")
    account = create_account(client, alice)
    upload(client, alice, account)
    with Session(engine) as db:
        row = db.scalars(select(Transaction).where(Transaction.merchant == "METRO")).one()
        row.category, row.category_source = "Shopping", "user"
        db.commit()

    result = upload(client, alice, account)

    assert result["categorized_by"] == {"rule": 0, "cache": 0, "llm": 0}
    assert len(provider.calls) == 1
    metro = by_merchant(transactions(client, alice))["METRO"]
    assert (metro["category"], metro["category_source"]) == ("Shopping", "user")


def test_one_users_cache_never_affects_another(client, provider, engine):
    alice = sign_up(client, "alice@example.com")
    bob = sign_up(client, "bob@example.com")
    upload(client, alice, create_account(client, alice))

    # Alice corrects a merchant; that correction is hers alone.
    with Session(engine) as db:
        entry = db.scalars(
            select(MerchantCategory).where(MerchantCategory.merchant == "MAPLE STREET BOOKS CO")
        ).one()
        entry.category, entry.source, entry.confidence = "Entertainment", "user", 1.0
        db.commit()

    result = upload(client, bob, create_account(client, bob))

    # Bob's merchants were sent to the provider again rather than read from Alice's cache.
    assert result["categorized_by"]["cache"] == 0
    assert result["categorized_by"]["llm"] == UNRULED_ROWS
    assert provider.calls == [UNRULED, UNRULED]
    assert by_merchant(transactions(client, bob))["MAPLE STREET BOOKS CO"]["category"] == "Shopping"

    with Session(engine) as db:
        caches = {
            (email, entry.merchant): entry.category
            for entry, email in db.execute(
                select(MerchantCategory, User.email).join(User, User.id == MerchantCategory.user_id)
            )
        }
    assert caches[("alice@example.com", "MAPLE STREET BOOKS CO")] == "Entertainment"
    assert caches[("bob@example.com", "MAPLE STREET BOOKS CO")] == "Shopping"
    assert len(caches) == 2 * len(UNRULED)


def test_user_correction_in_the_cache_wins_over_rules(client, engine):
    alice = sign_up(client, "alice@example.com")
    with Session(engine) as db:
        user_id = db.scalars(select(User.id)).one()
        db.add(MerchantCategory(user_id=user_id, merchant="METRO", category="Shopping",
                                source="user", confidence=1.0))
        db.commit()

    result = upload(client, alice, create_account(client, alice))

    assert result["categorized_by"]["cache"] == 1
    metro = by_merchant(transactions(client, alice))["METRO"]
    assert (metro["category"], metro["category_source"]) == ("Shopping", "cache")


def test_provider_answers_never_overwrite_a_user_correction(engine):
    with Session(engine) as db:
        user = User(email="a@example.com", password_hash="x")
        db.add(user)
        db.flush()
        db.add(MerchantCategory(user_id=user.id, merchant="ACMECLOUD", category="Health",
                                source="user", confidence=1.0))
        db.flush()

        _remember(db, user.id, {"ACMECLOUD": Result("Subscriptions", 0.75)})
        db.expire_all()

        entry = db.scalars(select(MerchantCategory)).one()
        assert (entry.category, entry.source) == ("Health", "user")


def test_unknown_merchants_are_sent_in_batches(engine, monkeypatch):
    monkeypatch.setattr("app.categorization.pipeline.BATCH_SIZE", 2)
    provider = FakeProvider()
    with Session(engine) as db:
        user = User(email="a@example.com", password_hash="x")
        db.add(user)
        db.flush()
        rows = [
            Transaction(raw_description=f"SHOP NUMBER {name} TORONTO", is_transfer=False)
            for name in ("ALPHA", "BRAVO", "CHARLIE", "ALPHA", "DELTA", "ECHO")
        ]
        # Only categorize_transactions is under test, so the rows need not be saved.
        counts = categorize_transactions(db, user.id, rows, provider)

    assert counts == {"rule": 0, "cache": 0, "llm": 6}
    assert [len(call) for call in provider.calls] == [2, 2, 1]
    sent = [merchant for call in provider.calls for merchant in call]
    assert len(sent) == len(set(sent)) == 5
