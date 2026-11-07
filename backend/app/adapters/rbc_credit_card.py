from .base import BankAdapter, ParsedTransaction


class RBCCreditCardAdapter(BankAdapter):
    bank_name = "RBC credit card"

    def parse(self, csv_text: str) -> list[ParsedTransaction]:
        raise NotImplementedError(
            "Write this until tests/test_rbc_adapter.py passes."
        )
