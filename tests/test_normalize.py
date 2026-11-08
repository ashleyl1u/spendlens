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
