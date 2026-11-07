"""Tests for the RBC credit card adapter, written before the adapter itself.

Run from the repo root with: pytest
"""

from datetime import date
from pathlib import Path

import pytest

from app.adapters.rbc_credit_card import RBCCreditCardAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"


@pytest.fixture(scope="module")
def parsed():
    return RBCCreditCardAdapter().parse(FIXTURE.read_text(encoding="utf-8"))


def by_description(rows, description):
    return [r for r in rows if r.raw_description == description]


def test_parses_every_row(parsed):
    assert len(parsed) == 24


def test_dates_become_real_dates(parsed):
    assert parsed[0].posted_date == date(2024, 3, 4)
    assert parsed[-1].posted_date == date(2024, 4, 7)


def test_purchases_are_positive_cents(parsed):
    rows = by_description(parsed, "TIM HORTONS #2210 TORONTO")
    assert [r.amount_cents for r in rows] == [312, 312, 235]


def test_amounts_have_no_float_rounding_errors(parsed):
    cents = {r.amount_cents for r in parsed}
    assert {549, 1099, 4520} <= cents


def test_refund_is_negative_cents(parsed):
    rows = by_description(parsed, "ca.sample-shop.com OAKVILLE")
    assert sorted(r.amount_cents for r in rows) == [-4520, 4520]


def test_payment_is_flagged_as_transfer(parsed):
    payments = by_description(parsed, "PAYMENT - THANK YOU / PAI EMENT - MERCI")
    assert len(payments) == 1
    assert payments[0].is_transfer is True
    assert payments[0].amount_cents == -15000
    assert sum(r.is_transfer for r in parsed) == 1


def test_same_day_identical_purchases_get_different_hashes(parsed):
    first, second = by_description(parsed, "TIM HORTONS #2210 TORONTO")[:2]
    assert (first.posted_date, first.amount_cents) == (
        second.posted_date,
        second.amount_cents,
    )
    assert first.row_hash != second.row_hash


def test_hashes_are_stable_across_parses(parsed):
    again = RBCCreditCardAdapter().parse(FIXTURE.read_text(encoding="utf-8"))
    assert [r.row_hash for r in parsed] == [r.row_hash for r in again]


def test_every_hash_in_the_file_is_unique(parsed):
    hashes = [r.row_hash for r in parsed]
    assert len(set(hashes)) == len(hashes)


def test_quoted_description_keeps_its_comma(parsed):
    assert by_description(parsed, "Maple Street Books Co., Vancouver")
