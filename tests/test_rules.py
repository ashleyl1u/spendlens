"""Tests for the keyword rules and the fixed category list."""

import pytest

from app.categorization.categories import CATEGORIES
from app.categorization.rules import RULES, match_rule


@pytest.mark.parametrize(
    "merchant, category",
    [
        ("PRESTO", "Transport"),
        ("UBER", "Transport"),
        ("UBER EATS", "Dining"),
        ("TIM HORTONS", "Dining"),
        ("MCDONALDS", "Dining"),
        ("CORNER BAKERY CAFE", "Dining"),
        ("LAKEVIEW PUB MAIN", "Dining"),
        ("TACO BELL", "Dining"),
        ("METRO", "Groceries"),
        ("FRESHCO", "Groceries"),
        ("SPOTIFY", "Subscriptions"),
        ("ACME TELECOM", "Bills & Utilities"),
        ("BELL CANADA", "Bills & Utilities"),
        ("SHOPPERS DRUG MART", "Health"),
        ("AIR CANADA", "Travel"),
        ("CINEPLEX", "Entertainment"),
        ("AMAZON.CA", "Shopping"),
    ],
)
def test_known_merchants(merchant, category):
    assert match_rule(merchant) == category


@pytest.mark.parametrize(
    "merchant",
    ["MAPLE STREET BOOKS CO", "GARDEN DUMPLING HO", "ACMECLOUD", "CA.SAMPLE-SHOP.COM", ""],
)
def test_unknown_merchants_fall_through(merchant):
    assert match_rule(merchant) is None


@pytest.mark.parametrize("merchant", ["BARBER SHOP", "PUBLIC MOBILE", "METROPOLIS BOOKS"])
def test_keywords_match_whole_words_only(merchant):
    # "BAR" must not match BARBER, "PUB" not PUBLIC, "METRO" not METROPOLIS.
    assert match_rule(merchant) is None


def test_rules_only_use_known_categories():
    assert {category for category, _ in RULES} <= set(CATEGORIES)


def test_category_list_is_fixed():
    assert CATEGORIES == (
        "Groceries", "Dining", "Transport", "Shopping", "Subscriptions",
        "Bills & Utilities", "Health", "Travel", "Entertainment", "Income/Refunds", "Other",
    )
