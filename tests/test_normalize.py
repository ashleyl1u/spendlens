"""Tests for merchant normalization, covering every description in the RBC fixture."""

import csv
from pathlib import Path

import pytest

from app.categorization.normalize import normalize_merchant

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"

EXPECTED = {
    "PRESTO MOBI/SK4M9Q2LTV TORONTO": "PRESTO",
    "PRESTO FARE/SJ7N2W5PQD Toronto": "PRESTO",
    "TIM HORTONS #2210 TORONTO": "TIM HORTONS",
    "SQ *CORNER BAKERY CAFE Toronto": "CORNER BAKERY CAFE",
    "SQ *GARDEN DUMPLING HO Toronto": "GARDEN DUMPLING HO",
    "SPOTIFY P2D4F6H8J0 STOCKHOLM": "SPOTIFY",
    "METRO #417 MISSISSAUGA": "METRO",
    "FRESHCO #8802 MISSISSAUGA": "FRESHCO",
    "Maple Street Books Co., Vancouver": "MAPLE STREET BOOKS CO",
    "TST-Lakeview Pub - Main TORONTO": "LAKEVIEW PUB MAIN",
    "*RFBT-TORONTO YONGE ST TORONTO": "RFBT-TORONTO YONGE ST",
    "ACME TELECOM 1 800 555 0123 OTTAWA": "ACME TELECOM",
    "SHOPPERS DRUG MART #1090 TORONTO": "SHOPPERS DRUG MART",
    "PAYMENT - THANK YOU / PAI EMENT - MERCI": "PAYMENT THANK YOU PAI EMENT MERCI",
    "ca.sample-shop.com OAKVILLE": "CA.SAMPLE-SHOP.COM",
    "MCDONALD'S #11234 TORONTO": "MCDONALDS",
    "McDonalds 11234 TORONTO": "MCDONALDS",
    "ACMECLOUD *STORAGE PLA SAN FRANCISCO": "ACMECLOUD",
    "CHIPOTLE 3358 TORONTO": "CHIPOTLE",
    "UBER *TRIP HELP.UBER.COM": "UBER",
}


def fixture_descriptions():
    with FIXTURE.open(encoding="utf-8") as f:
        return sorted({row["Description 1"] for row in csv.DictReader(f)})


def test_every_fixture_description_has_an_expectation():
    assert set(fixture_descriptions()) == set(EXPECTED)


@pytest.mark.parametrize("raw", fixture_descriptions())
def test_fixture_descriptions(raw):
    assert normalize_merchant(raw) == EXPECTED[raw]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PAYPAL *STEAMGAMES 4029357733", "STEAMGAMES"),
        ("TST* Burger Joint TORONTO ON", "BURGER JOINT"),
        ("Tim Hortons 1187 Mississauga ON", "TIM HORTONS"),
        ("NETFLIX.COM 866-579-7172 CA", "NETFLIX.COM"),
        ("STARBUCKS 04421 NORTH YORK", "STARBUCKS"),
        ("  loblaws   ", "LOBLAWS"),
        # DoorDash and Shopify processor prefixes.
        ("DD *DOORDASH WENDYS TORONTO", "DOORDASH WENDYS"),
        ("SP *MATCHA DIRECT ONLINE", "MATCHA DIRECT ONLINE"),
        ("GOOGLE *YOUTUBE PREMIUM", "GOOGLE YOUTUBE"),
        ("AMAZON PRIME*AB12CD", "AMAZON PRIME"),
        # Words that merely start with SP or DD are not prefixes.
        ("SPORT CHEK #567 TORONTO", "SPORT CHEK"),
        ("DDS DENTAL CARE TORONTO", "DDS DENTAL CARE"),
    ],
)
def test_other_common_shapes(raw, expected):
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize("raw", ["TORONTO", "#1234", "ON"])
def test_never_strips_down_to_nothing(raw):
    assert normalize_merchant(raw) != ""


def test_same_chain_different_branches_match():
    assert normalize_merchant("TIM HORTONS #2210 TORONTO") == normalize_merchant(
        "Tim Hortons #0451 Oakville ON"
    )


# --- brands that sell several services ------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("UBER *TRIP HELP.UBER.COM", "UBER"),
        ("UBER* TRIP TORONTO ON", "UBER"),
        ("UBER *TRIP TORONTO", "UBER"),
        ("UBER *EATS PENDING TORONTO", "UBER EATS"),
        ("UBER *EATS TORONTO", "UBER EATS"),
        ("UBER* EATS HELP.UBER.COM ON", "UBER EATS"),
        ("DD *DOORDASH WENDYS TORONTO", "DOORDASH WENDYS"),
    ],
)
def test_existing_uber_and_doordash_shapes_are_unchanged(raw, expected):
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        # The held-out miss: the service after the star was dropped, leaving "UBER".
        ("UBER* ONE MEMBERSHIP", "UBER ONE"),
        ("UBER *ONE MEMBERSHIP", "UBER ONE"),  # where the star sits does not matter
        # A service nobody listed is still kept, so it is not merged into the brand.
        ("UBER *GIFTCARD", "UBER GIFTCARD"),
        ("GOOGLE *GOOGLE ONE", "GOOGLE ONE"),  # repeated brand name skipped
        ("GOOGLE *CLOUD STORAGE", "GOOGLE CLOUD"),
        ("AMAZON *PRIME VIDEO", "AMAZON PRIME"),
        ("AMAZON.CA*PRIME MEMBER", "AMAZON.CA PRIME"),
    ],
)
def test_a_multi_service_brand_keeps_its_service(raw, expected):
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("AMAZON.CA*1A2B3C4D5 TORONTO", "AMAZON.CA"),  # order reference
        ("AMAZON *1A2B3C", "AMAZON"),
        ("UBER* HELP.UBER.COM", "UBER"),  # web address
        ("UBER *PENDING", "UBER"),  # the core service collapses to the brand
    ],
)
def test_codes_and_addresses_are_not_services(raw, expected):
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("LYFT *RIDE TORONTO", "LYFT"),
        ("ACMECLOUD *STORAGE PLA SAN FRANCISCO", "ACMECLOUD"),
        ("APPLE.COM/BILL ITUNES.COM", "APPLE.COM/BILL ITUNES.COM"),
        ("PAYPAL *UBER", "UBER"),  # PayPal is a processor prefix, not a brand
    ],
)
def test_other_brands_still_drop_the_text_after_the_star(raw, expected):
    assert normalize_merchant(raw) == expected
