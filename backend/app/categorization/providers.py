"""Categorizers for merchants no rule or cache entry covers.

A provider only ever receives normalized merchant names. Amounts, dates, descriptions
and account details never leave the app, which is enforced by the list[str] signature.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .categories import CATEGORIES, OTHER

INVALID_CONFIDENCE = 0.1  # given to anything the provider got wrong, so it is reviewed


@dataclass(frozen=True)
class Result:
    category: str
    confidence: float


class LLMProvider(ABC):
    name: str

    def categorize(self, merchants: list[str]) -> list[Result]:
        """Return one validated Result per merchant, in the same order."""
        if not merchants:
            return []
        raw = self._categorize(list(merchants))
        results = [_validate(result) for result in raw[: len(merchants)]]
        # A provider that returns too few answers must not leave rows uncategorized.
        results += [Result(OTHER, INVALID_CONFIDENCE)] * (len(merchants) - len(results))
        return results

    @abstractmethod
    def _categorize(self, merchants: list[str]) -> list[Result]:
        """Ask the model. The output is untrusted and is validated by categorize()."""


def _validate(result: object) -> Result:
    category = getattr(result, "category", None)
    confidence = getattr(result, "confidence", None)
    if category not in CATEGORIES or not isinstance(confidence, (int, float)):
        return Result(OTHER, INVALID_CONFIDENCE)
    return Result(category, min(max(float(confidence), 0.0), 1.0))


class FakeProvider(LLMProvider):
    """Deterministic stand-in for an LLM: no network, same answer every time.

    It knows a few merchant keywords and calls everything else Other with low
    confidence. Tests can pass `answers` to choose exact results, and read `calls`
    to see what was sent.
    """

    name = "fake"

    HINTS: dict[str, Result] = {
        "BOOK": Result("Shopping", 0.8),
        "SHOP": Result("Shopping", 0.75),
        "DUMPLING": Result("Dining", 0.85),
        "NOODLE": Result("Dining", 0.85),
        "RFBT": Result("Dining", 0.6),
        "CLOUD": Result("Subscriptions", 0.75),
    }

    def __init__(self, answers: dict[str, Result] | None = None):
        self.answers = answers or {}
        self.calls: list[list[str]] = []

    def _categorize(self, merchants: list[str]) -> list[Result]:
        self.calls.append(merchants)
        return [self._answer(merchant) for merchant in merchants]

    def _answer(self, merchant: str) -> Result:
        if merchant in self.answers:
            return self.answers[merchant]
        for keyword, result in self.HINTS.items():
            if keyword in merchant:
                return result
        return Result(OTHER, 0.4)


def get_provider() -> LLMProvider:
    """Build the provider named by LLM_PROVIDER (default "fake")."""
    name = os.environ.get("LLM_PROVIDER", "fake").strip().lower()
    if name == "fake":
        return FakeProvider()
    raise RuntimeError(f"Unknown LLM_PROVIDER {name!r}; only 'fake' is available so far")
