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

# What each category means, sent to the LLM so it follows the same conventions as the
# labels in eval/labeled_merchants.csv. Without these, Gemini confidently put Canada
# Post, ServiceOntario and UPS Store under Bills & Utilities or Shopping, and since it was
# sure, the review flag never caught it. Changing a line here changes categorization:
# rerun eval/run_eval.py afterwards.
CATEGORY_DEFINITIONS: dict[str, str] = {
    "Groceries": "supermarkets, grocery stores, butchers and food markets",
    "Dining": "restaurants, cafes, bakeries, bubble tea, fast food and food delivery",
    "Transport": "public transit, ride-hailing, fuel, parking, tolls, car and bike sharing",
    "Shopping": "retail goods in stores or online, including department stores, "
    "marketplaces, beauty supply and liquor stores",
    "Subscriptions": "recurring software, streaming, cloud storage and digital memberships",
    "Bills & Utilities": "phone, internet, electricity, natural gas and insurance",
    "Health": "pharmacies, medical, dental, labs, optometry, gyms and fitness studios",
    "Travel": "flights, hotels, trains, car rental and travel booking sites",
    "Entertainment": "movies, concerts, events, tickets, video games, museums and zoos",
    "Income/Refunds": "cashback, rewards, interest credits and statement credits",
    "Other": "government services and fees, postage and shipping, bank and card fees, "
    "interest charges, donations, personal services such as salons, and anything that "
    "fits nowhere else",
}

OTHER = "Other"
TRANSFER = "Transfer"

# A category below this confidence is shown to the user to confirm.
REVIEW_THRESHOLD = 0.7
