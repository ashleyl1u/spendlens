"""Tests for the keyword rules and the fixed category list."""

import pytest

from app.categorization.categories import CATEGORIES
from app.categorization.normalize import normalize_merchant
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
        # Found by the evaluation harness on 2026-11-08.
        ("UBER EATS", "Dining"),
        ("DOORDASH WENDYS", "Dining"),
        ("CANADIAN TIRE GAS BAR", "Transport"),
        ("CANADIAN TIRE", "Shopping"),
        ("AMAZON PRIME", "Subscriptions"),
        ("GOOGLE YOUTUBE", "Subscriptions"),
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


# --- brands that sell several services ------------------------------------------


@pytest.mark.parametrize(
    "description, category",
    [
        # The held-out miss, end to end: description -> merchant -> rule.
        ("UBER* ONE MEMBERSHIP", "Subscriptions"),
        ("UBER *ONE MEMBERSHIP", "Subscriptions"),
        ("UBER ONE MEMBERSHIP", "Subscriptions"),
        ("UBER *EATS TORONTO", "Dining"),
        ("UBER *TRIP HELP.UBER.COM", "Transport"),
        ("PAYPAL *UBER", "Transport"),
        ("AMAZON *PRIME VIDEO", "Subscriptions"),
        ("AMAZON PRIME*AB12CD", "Subscriptions"),
        ("AMAZON MUSIC*X1", "Subscriptions"),
        ("AMAZON WEB SERVICES", "Subscriptions"),
        ("AWS EMEA", "Subscriptions"),
        ("AMAZON.CA*1A2B3C4D5 TORONTO", "Shopping"),
        ("GOOGLE *GOOGLE ONE", "Subscriptions"),
        ("GOOGLE *CLOUD STORAGE", "Subscriptions"),
        ("GOOGLE *YOUTUBE PREMIUM", "Subscriptions"),
    ],
)
def test_brand_services_beat_the_general_brand_rule(description, category):
    assert match_rule(normalize_merchant(description)) == category


def test_brand_service_rules_come_before_the_brand_rules():
    """First match wins, so each service keyword must be checked before its brand's
    general keyword; otherwise "UBER ONE" would match "UBER" and become Transport."""
    order = [word for _, words in RULES for word in words]
    for service, brand in [("UBER ONE", "UBER"), ("UBER EATS", "UBER"),
                           ("AMAZON PRIME", "AMAZON"), ("AMAZON MUSIC", "AMAZON"),
                           ("AMAZON WEB SERVICES", "AMAZON")]:
        assert order.index(service) < order.index(brand), service


@pytest.mark.parametrize("merchant", ["GOOGLE", "GOOGLE GIFTCARD", "APPLE STORE EATON CENTRE"])
def test_bare_google_and_apple_have_no_rule(merchant):
    # Neither has a catch-all rule, so an unlisted service goes to the provider
    # rather than being forced into one category.
    assert match_rule(merchant) is None
