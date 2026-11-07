from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ParsedTransaction:
    """One statement row in the app's own format, independent of any bank."""

    posted_date: date
    amount_cents: int  # spending is positive; refunds and credits are negative
    raw_description: str
    is_transfer: bool  # e.g. a payment to the card; excluded from spending totals
    row_hash: str  # stable per row; the ingestion layer combines it with the user ID


class BankAdapter(ABC):
    """Turns one bank's CSV export into ParsedTransaction objects."""

    bank_name: str

    @abstractmethod
    def parse(self, csv_text: str) -> list[ParsedTransaction]:
        """Parse the text of a statement export into normalized transactions."""
