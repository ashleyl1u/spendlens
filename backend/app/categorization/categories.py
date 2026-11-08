"""The fixed set of spending categories. Nothing outside this list is ever stored,
except TRANSFER, which marks card payments and is kept out of spending totals."""

CATEGORIES: tuple[str, ...] = (
    "Groceries",
    "Dining",
    "Transport",
    "Shopping",
    "Subscriptions",
    "Bills & Utilities",
    "Health",
    "Travel",
    "Entertainment",
    "Income/Refunds",
    "Other",
)

OTHER = "Other"
TRANSFER = "Transfer"

# A category below this confidence is shown to the user to confirm.
REVIEW_THRESHOLD = 0.7
