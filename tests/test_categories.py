"""Tests for GET /categories."""

from app.categorization.categories import CATEGORIES, TRANSFER
from app.schemas import TransactionCorrection


def test_returns_the_fixed_list_in_order(client):
    response = client.get("/categories")

    assert response.status_code == 200
    assert response.json() == list(CATEGORIES)
    assert response.json()[-1] == "Other"


def test_needs_no_login(client):
    assert client.get("/categories", headers={"Authorization": "Bearer nope"}).status_code == 200


def test_transfer_is_not_a_choosable_category(client):
    # Transfers can't be picked in a correction (the PATCH endpoint rejects them).
    assert TRANSFER not in client.get("/categories").json()


def test_every_listed_category_is_accepted_by_corrections(client):
    """The list a client shows is exactly what PATCH /transactions/{id} accepts."""
    for category in client.get("/categories").json():
        assert TransactionCorrection(category=category).category == category
