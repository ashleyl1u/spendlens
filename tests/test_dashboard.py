"""Tests for the dashboard endpoints, checked against hand-written fixture data."""

from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Transaction, User
from app.queries import Filters, spending_by_category

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"

# Every row of the fixture, written out by hand: date, merchant, category, cents,
# is_transfer. Categories are what the rules and FakeProvider assign. Spending is
# positive; the refund and the card payment are negative.
ROWS = [
    (date(2024, 3, 4), "PRESTO", "Transport", 2500, False),
    (date(2024, 3, 5), "TIM HORTONS", "Dining", 312, False),
    (date(2024, 3, 5), "TIM HORTONS", "Dining", 312, False),
    (date(2024, 3, 6), "CORNER BAKERY CAFE", "Dining", 975, False),
    (date(2024, 3, 7), "SPOTIFY", "Subscriptions", 1099, False),
    (date(2024, 3, 9), "METRO", "Groceries", 6438, False),
    (date(2024, 3, 9), "MAPLE STREET BOOKS CO", "Shopping", 1850, False),
    (date(2024, 3, 11), "LAKEVIEW PUB MAIN", "Dining", 4200, False),
    (date(2024, 3, 12), "RFBT-TORONTO YONGE ST", "Dining", 740, False),
    (date(2024, 3, 12), "ACME TELECOM", "Bills & Utilities", 5500, False),
    (date(2024, 3, 14), "SHOPPERS DRUG MART", "Health", 1429, False),
    (date(2024, 3, 15), "PAYMENT THANK YOU PAI EMENT MERCI", "Transfer", -15000, True),
    (date(2024, 3, 16), "CA.SAMPLE-SHOP.COM", "Shopping", 4520, False),
    (date(2024, 3, 18), "MCDONALDS", "Dining", 610, False),
    (date(2024, 3, 19), "ACMECLOUD", "Subscriptions", 549, False),
    (date(2024, 3, 20), "CHIPOTLE", "Dining", 1355, False),
    (date(2024, 3, 21), "GARDEN DUMPLING HO", "Dining", 2190, False),
    (date(2024, 3, 22), "PRESTO", "Transport", 330, False),
    (date(2024, 3, 25), "FRESHCO", "Groceries", 5218, False),
    (date(2024, 3, 26), "UBER", "Transport", 1840, False),
    (date(2024, 3, 27), "CA.SAMPLE-SHOP.COM", "Shopping", -4520, False),
    (date(2024, 3, 28), "MCDONALDS", "Dining", 525, False),
    (date(2024, 3, 29), "TIM HORTONS", "Dining", 235, False),
    (date(2024, 4, 7), "SPOTIFY", "Subscriptions", 1099, False),
]
SPENDING = [row for row in ROWS if not row[4]]

# Worked out on paper from the table above, as a check on the table itself.
TOTAL_SPENT = 39306
CATEGORY_TOTALS = {
    "Dining": 11454,
    "Groceries": 6438 + 5218,
    "Bills & Utilities": 5500,
    "Transport": 2500 + 330 + 1840,
    "Subscriptions": 1099 + 549 + 1099,
    "Shopping": 1850 + 4520 - 4520,
    "Health": 1429,
}
ENDPOINTS = ["/dashboard/summary", "/dashboard/by-category", "/dashboard/by-month",
             "/dashboard/top-merchants"]


def test_hand_written_table_is_consistent():
    assert len(ROWS) == 24
    assert sum(cents for *_, cents, _ in SPENDING) == TOTAL_SPENT
    assert sum(CATEGORY_TOTALS.values()) == TOTAL_SPENT


# --- helpers ------------------------------------------------------------------


def sign_up(client, email):
    client.post("/auth/register", json={"email": email, "password": "correct-horse"})
    token = client.post(
        "/auth/login", data={"username": email, "password": "correct-horse"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def add_account(client, headers, nickname="RBC Mastercard"):
    return client.post("/accounts", json={"nickname": nickname}, headers=headers).json()["id"]


def upload(client, headers, account_id, content=None):
    response = client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": ("statement.csv", content or FIXTURE.read_bytes(), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def get(client, headers, path, **params):
    response = client.get(path, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def alice(client):
    return sign_up(client, "alice@example.com")


@pytest.fixture()
def alice_account(client, alice):
    """Alice's card, with the whole fixture statement uploaded into it."""
    account_id = add_account(client, alice)
    upload(client, alice, account_id)
    return account_id


def in_range(start, end):
    return [row for row in SPENDING if start <= row[0] <= end]


# --- summary --------------------------------------------------------------------


def test_summary_matches_the_fixture(client, alice, alice_account):
    assert get(client, alice, "/dashboard/summary") == {
        "total_spent_cents": TOTAL_SPENT,
        "transaction_count": 23,  # 24 rows minus the card payment
        "needs_review_count": 1,  # FakeProvider is unsure about RFBT (0.6)
        "first_date": "2024-03-04",
        "last_date": "2024-04-07",
    }


def test_transfers_are_excluded(client, alice, alice_account):
    summary = get(client, alice, "/dashboard/summary")
    with_payment = sum(cents for *_, cents, _ in ROWS)
    assert summary["total_spent_cents"] == TOTAL_SPENT != with_payment

    categories = {c["category"] for c in get(client, alice, "/dashboard/by-category")}
    assert "Transfer" not in categories
    merchants = {m["merchant"] for m in get(client, alice, "/dashboard/top-merchants", limit=50)}
    assert not any("PAYMENT" in m for m in merchants)


# --- by category ------------------------------------------------------------------


def test_by_category_matches_the_fixture(client, alice, alice_account):
    result = get(client, alice, "/dashboard/by-category")

    assert {c["category"]: c["total_cents"] for c in result} == CATEGORY_TOTALS
    totals = [c["total_cents"] for c in result]
    assert totals == sorted(totals, reverse=True)
    assert result[0] == {
        "category": "Groceries",
        "total_cents": 11656,
        "transaction_count": 2,
        "share": pytest.approx(11656 / TOTAL_SPENT),
    }
    assert sum(c["share"] for c in result) == pytest.approx(1.0)


def test_refunds_reduce_their_category(client, alice, alice_account):
    shopping = next(
        c for c in get(client, alice, "/dashboard/by-category") if c["category"] == "Shopping"
    )
    # Books 1850, plus a 4520 purchase and its 4520 refund.
    assert shopping["total_cents"] == 1850
    assert shopping["transaction_count"] == 3


def test_shares_are_zero_when_refunds_outweigh_spending(client, engine):
    headers = sign_up(client, "carol@example.com")
    account_id = add_account(client, headers)
    statement = (
        "Account Type,Account Number,Transaction Date,Cheque Number,Description 1,"
        "Description 2,CAD$,USD$\n"
        "MasterCard,1,3/1/2024,,METRO #417 MISSISSAUGA,,-10.00,\n"
        "MasterCard,1,3/2/2024,,METRO #417 MISSISSAUGA,,25.00,\n"
    )
    upload(client, headers, account_id, statement.encode())

    result = get(client, headers, "/dashboard/by-category")
    assert result == [
        {"category": "Groceries", "total_cents": -1500, "transaction_count": 2, "share": 0.0}
    ]
    assert get(client, headers, "/dashboard/summary")["total_spent_cents"] == -1500


def test_uncategorized_rows_are_grouped(client, alice, alice_account, engine):
    with Session(engine) as db:
        db.execute(update(Transaction).where(Transaction.merchant == "METRO").values(category=None))
        db.commit()

    result = {c["category"]: c["total_cents"] for c in get(client, alice, "/dashboard/by-category")}
    assert result["Uncategorized"] == 6438
    assert result["Groceries"] == 5218


# --- by month ---------------------------------------------------------------------


def test_by_month_matches_the_fixture(client, alice, alice_account):
    march = [row for row in SPENDING if row[0].month == 3]
    assert get(client, alice, "/dashboard/by-month") == [
        {"month": "2024-03", "total_cents": sum(r[3] for r in march), "transaction_count": 22},
        {"month": "2024-04", "total_cents": 1099, "transaction_count": 1},
    ]


def test_empty_months_in_the_range_are_zero(client, alice, alice_account):
    result = get(client, alice, "/dashboard/by-month", start="2023-11-15", end="2024-06-01")

    assert [m["month"] for m in result] == [
        "2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"
    ]
    assert {m["month"]: m["total_cents"] for m in result if m["total_cents"]} == {
        "2024-03": TOTAL_SPENT - 1099,
        "2024-04": 1099,
    }
    assert all(m["transaction_count"] == 0 for m in result if not m["total_cents"])


def test_gaps_between_transactions_are_zero_filled(client):
    headers = sign_up(client, "dave@example.com")
    account_id = add_account(client, headers)
    statement = (
        "Account Type,Account Number,Transaction Date,Cheque Number,Description 1,"
        "Description 2,CAD$,USD$\n"
        "MasterCard,1,11/20/2023,,METRO #417 MISSISSAUGA,,-10.00,\n"
        "MasterCard,1,2/3/2024,,METRO #417 MISSISSAUGA,,-20.00,\n"
    )
    upload(client, headers, account_id, statement.encode())

    assert get(client, headers, "/dashboard/by-month") == [
        {"month": "2023-11", "total_cents": 1000, "transaction_count": 1},
        {"month": "2023-12", "total_cents": 0, "transaction_count": 0},
        {"month": "2024-01", "total_cents": 0, "transaction_count": 0},
        {"month": "2024-02", "total_cents": 2000, "transaction_count": 1},
    ]


# --- top merchants ----------------------------------------------------------------


def test_top_merchants_match_the_fixture(client, alice, alice_account):
    by_merchant = defaultdict(lambda: [0, 0])
    for _, merchant, _, cents, _ in SPENDING:
        by_merchant[merchant][0] += cents
        by_merchant[merchant][1] += 1

    result = get(client, alice, "/dashboard/top-merchants", limit=5)
    assert result == [
        {"merchant": "METRO", "total_cents": 6438, "transaction_count": 1},
        {"merchant": "ACME TELECOM", "total_cents": 5500, "transaction_count": 1},
        {"merchant": "FRESHCO", "total_cents": 5218, "transaction_count": 1},
        {"merchant": "LAKEVIEW PUB MAIN", "total_cents": 4200, "transaction_count": 1},
        {"merchant": "PRESTO", "total_cents": 2830, "transaction_count": 2},
    ]

    everything = get(client, alice, "/dashboard/top-merchants", limit=50)
    assert {m["merchant"]: [m["total_cents"], m["transaction_count"]] for m in everything} == (
        dict(by_merchant)
    )
    default = get(client, alice, "/dashboard/top-merchants")
    assert len(default) == 10
    assert default[-1] == {"merchant": "SHOPPERS DRUG MART", "total_cents": 1429,
                           "transaction_count": 1}


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_top_merchants_limit_is_bounded(client, alice, alice_account, limit):
    response = client.get(f"/dashboard/top-merchants?limit={limit}", headers=alice)
    assert response.status_code == 422


# --- filters ----------------------------------------------------------------------


def test_date_range_is_inclusive(client, alice, alice_account):
    start, end = date(2024, 3, 12), date(2024, 3, 20)
    expected = in_range(start, end)

    summary = get(client, alice, "/dashboard/summary", start=str(start), end=str(end))
    # 740 + 5500 + 1429 + 4520 + 610 + 549 + 1355; the payment on 3/15 is left out.
    assert summary["total_spent_cents"] == sum(r[3] for r in expected) == 14703
    assert summary["transaction_count"] == len(expected) == 7
    assert (summary["first_date"], summary["last_date"]) == ("2024-03-12", "2024-03-20")

    only_start = get(client, alice, "/dashboard/summary", start="2024-04-01")
    assert (only_start["total_spent_cents"], only_start["transaction_count"]) == (1099, 1)
    only_end = get(client, alice, "/dashboard/summary", end="2024-03-04")
    assert (only_end["total_spent_cents"], only_end["transaction_count"]) == (2500, 1)


def test_end_before_start_is_rejected(client, alice, alice_account):
    for path in ENDPOINTS:
        response = client.get(path, params={"start": "2024-03-10", "end": "2024-03-01"},
                              headers=alice)
        assert response.status_code == 422, path


def test_bad_date_is_rejected(client, alice, alice_account):
    response = client.get("/dashboard/summary?start=March", headers=alice)
    assert response.status_code == 422


def test_account_filter(client, alice, alice_account):
    second = add_account(client, alice, "Second card")
    statement = (
        "Account Type,Account Number,Transaction Date,Cheque Number,Description 1,"
        "Description 2,CAD$,USD$\n"
        "MasterCard,1,3/3/2024,,FRESHCO #8802 MISSISSAUGA,,-12.34,\n"
    )
    upload(client, alice, second, statement.encode())

    everything = get(client, alice, "/dashboard/summary")
    first_only = get(client, alice, "/dashboard/summary", account_id=alice_account)
    second_only = get(client, alice, "/dashboard/summary", account_id=second)

    assert everything["total_spent_cents"] == TOTAL_SPENT + 1234
    assert first_only["total_spent_cents"] == TOTAL_SPENT
    assert (second_only["total_spent_cents"], second_only["transaction_count"]) == (1234, 1)
    assert get(client, alice, "/dashboard/by-category", account_id=second) == [
        {"category": "Groceries", "total_cents": 1234, "transaction_count": 1, "share": 1.0}
    ]


def test_unknown_account_is_404(client, alice, alice_account):
    for path in ENDPOINTS:
        assert client.get(path, params={"account_id": 999}, headers=alice).status_code == 404


# --- empty user, isolation, auth ----------------------------------------------------


def test_user_with_no_transactions_gets_zeros(client):
    headers = sign_up(client, "empty@example.com")

    assert get(client, headers, "/dashboard/summary") == {
        "total_spent_cents": 0,
        "transaction_count": 0,
        "needs_review_count": 0,
        "first_date": None,
        "last_date": None,
    }
    assert get(client, headers, "/dashboard/by-category") == []
    assert get(client, headers, "/dashboard/by-month") == []
    assert get(client, headers, "/dashboard/top-merchants") == []
    # With a range, the months still appear, as zeros.
    assert get(client, headers, "/dashboard/by-month", start="2024-01-01", end="2024-02-29") == [
        {"month": "2024-01", "total_cents": 0, "transaction_count": 0},
        {"month": "2024-02", "total_cents": 0, "transaction_count": 0},
    ]


def test_users_never_see_each_others_numbers(client, alice, alice_account):
    bob = sign_up(client, "bob@example.com")

    # Before Bob has data, he sees nothing of Alice's.
    assert get(client, bob, "/dashboard/summary")["total_spent_cents"] == 0
    assert get(client, bob, "/dashboard/by-category") == []
    assert get(client, bob, "/dashboard/by-month") == []
    assert get(client, bob, "/dashboard/top-merchants") == []

    # Naming Alice's account gets the same 404 as an account that does not exist.
    for path in ENDPOINTS:
        response = client.get(path, params={"account_id": alice_account}, headers=bob)
        assert response.status_code == 404, path

    # Once Bob uploads a small statement, he sees only his own numbers, and Alice's
    # are unchanged.
    bob_account = add_account(client, bob)
    statement = (
        "Account Type,Account Number,Transaction Date,Cheque Number,Description 1,"
        "Description 2,CAD$,USD$\n"
        "MasterCard,1,3/9/2024,,METRO #417 MISSISSAUGA,,-1.00,\n"
    )
    upload(client, bob, bob_account, statement.encode())

    assert get(client, bob, "/dashboard/summary")["total_spent_cents"] == 100
    assert get(client, bob, "/dashboard/top-merchants") == [
        {"merchant": "METRO", "total_cents": 100, "transaction_count": 1}
    ]
    assert get(client, alice, "/dashboard/summary")["total_spent_cents"] == TOTAL_SPENT


def test_queries_ignore_another_users_account_even_without_the_router(
    client, alice, alice_account, engine
):
    """The query functions filter by user themselves, so a caller that skips the
    ownership check (a future assistant tool, say) still cannot read other users."""
    sign_up(client, "bob@example.com")
    with Session(engine) as db:
        bob_id = db.scalar(select(User.id).where(User.email == "bob@example.com"))
        assert spending_by_category(db, bob_id, Filters(account_id=alice_account)) == []


def test_filters_reject_end_before_start():
    with pytest.raises(ValueError):
        Filters(start=date(2024, 3, 2), end=date(2024, 3, 1))


@pytest.mark.parametrize("path", ENDPOINTS)
def test_auth_is_required(client, path):
    assert client.get(path).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.get(path, headers=bad).status_code == 401
