import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal

from .base import BankAdapter, ParsedTransaction

PAYMENT_PREFIX = "PAYMENT - THANK YOU"


class RBCCreditCardAdapter(BankAdapter):
    bank_name = "RBC credit card"

    def parse(self, csv_text: str) -> list[ParsedTransaction]:
        seen: Counter[tuple[str, int, str]] = Counter()
        transactions: list[ParsedTransaction] = []

        # DictReader handles quoted fields, so "Maple Street Books Co., Vancouver"
        # stays one description instead of being split at its comma.
        reader = csv.DictReader(io.StringIO(csv_text))
        for line_number, row in enumerate(reader, start=2):
            amount_text = row["CAD$"].strip()
            if not amount_text:
                raise ValueError(f"Line {line_number}: no CAD$ amount")

            posted_date = datetime.strptime(
                row["Transaction Date"].strip(), "%m/%d/%Y"
            ).date()
            description = row["Description 1"].strip()

            # RBC shows purchases as negative. We store spending as positive cents,
            # so refunds and card payments come out negative. Decimal avoids the
            # rounding errors floats give (5.49 * 100 is not exactly 549).
            amount_cents = int((-Decimal(amount_text) * 100).to_integral_value())

            # Two identical purchases on the same day are different transactions,
            # so the hash includes how many identical rows came before this one.
            key = (posted_date.isoformat(), amount_cents, description)
            occurrence = seen[key]
            seen[key] += 1
            row_hash = hashlib.sha256(
                json.dumps([*key, occurrence]).encode("utf-8")
            ).hexdigest()

            transactions.append(
                ParsedTransaction(
                    posted_date=posted_date,
                    amount_cents=amount_cents,
                    raw_description=description,
                    is_transfer=description.upper().startswith(PAYMENT_PREFIX),
                    row_hash=row_hash,
                )
            )

        return transactions
