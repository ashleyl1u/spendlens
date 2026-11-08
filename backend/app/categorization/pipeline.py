"""normalize -> per-user cache -> rules -> LLM provider, for a batch of transactions."""

from collections import Counter
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import dialect_insert
from ..models import MerchantCategory, Transaction
from .categories import OTHER, REVIEW_THRESHOLD, TRANSFER
from .normalize import normalize_merchant
from .providers import LLMProvider, Result
from .rules import RULE_CONFIDENCE, match_rule

BATCH_SIZE = 50  # merchants per provider call
SOURCES = ("rule", "cache", "llm")
MERCHANT_MAX_LENGTH = 200  # matches the merchant columns


def categorize_transactions(
    db: Session,
    user_id: int,
    transactions: Sequence[Transaction],
    provider: LLMProvider,
) -> dict[str, int]:
    """Fill in merchant, category, category_source, confidence and needs_review.

    Every transaction must belong to user_id. Changes are flushed but not committed.
    Returns how many transactions each source categorized, e.g. {"rule": 12, ...}.
    """
    for transaction in transactions:
        transaction.merchant = normalize_merchant(transaction.raw_description)[
            :MERCHANT_MAX_LENGTH
        ]

    merchants = {t.merchant for t in transactions if not t.is_transfer and t.merchant}
    decided = _from_cache(db, user_id, merchants)
    for merchant in merchants - decided.keys():
        category = match_rule(merchant)
        if category:
            decided[merchant] = ("rule", Result(category, RULE_CONFIDENCE))

    remaining = sorted(merchants - decided.keys())
    llm_results = _ask_provider(provider, remaining)
    _remember(db, user_id, llm_results)
    decided.update({m: ("llm", result) for m, result in llm_results.items()})

    counts = Counter({source: 0 for source in SOURCES})
    for transaction in transactions:
        if transaction.is_transfer:
            source, result = "rule", Result(TRANSFER, 1.0)
        elif not transaction.merchant:
            source, result = "rule", Result(OTHER, 0.0)
        else:
            source, result = decided[transaction.merchant]
        transaction.category = result.category
        transaction.category_source = source
        transaction.confidence = result.confidence
        transaction.needs_review = result.confidence < REVIEW_THRESHOLD
        counts[source] += 1

    db.flush()
    return dict(counts)


def _from_cache(
    db: Session, user_id: int, merchants: set[str]
) -> dict[str, tuple[str, Result]]:
    if not merchants:
        return {}
    rows = db.scalars(
        select(MerchantCategory).where(
            MerchantCategory.user_id == user_id,
            MerchantCategory.merchant.in_(merchants),
        )
    )
    return {row.merchant: ("cache", Result(row.category, row.confidence)) for row in rows}


def _ask_provider(provider: LLMProvider, merchants: list[str]) -> dict[str, Result]:
    results: dict[str, Result] = {}
    for start in range(0, len(merchants), BATCH_SIZE):
        batch = merchants[start : start + BATCH_SIZE]
        results.update(zip(batch, provider.categorize(batch)))
    return results


def _remember(db: Session, user_id: int, results: dict[str, Result]) -> None:
    """Store LLM answers in the user's cache. A user's own correction is never overwritten."""
    if not results:
        return
    insert = dialect_insert(db)
    statement = insert(MerchantCategory).values(
        [
            {
                "user_id": user_id,
                "merchant": merchant,
                "category": result.category,
                "source": "llm",
                "confidence": result.confidence,
            }
            for merchant, result in results.items()
        ]
    )
    statement = statement.on_conflict_do_update(
        index_elements=["user_id", "merchant"],
        set_={
            "category": statement.excluded.category,
            "source": statement.excluded.source,
            "confidence": statement.excluded.confidence,
        },
        where=MerchantCategory.source != "user",
    )
    db.execute(statement)
