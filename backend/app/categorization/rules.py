"""Keyword rules for merchants whose category is obvious, so they never reach the LLM."""

import re

RULE_CONFIDENCE = 0.95

# Checked in order and the first match wins, so put specific keywords before general
# ones ("UBER EATS" before "UBER"). Keywords match whole words of the merchant name.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Dining", ("UBER EATS", "DOORDASH", "SKIP THE DISHES", "SKIPTHEDISHES", "TACO BELL")),
    ("Transport", (
        "PRESTO", "UBER", "LYFT", "TTC", "GO TRANSIT", "UP EXPRESS", "COMPASS",
        "SHELL", "ESSO", "PETRO-CANADA", "PETRO CANADA", "PIONEER", "IMPARK",
        "GREEN P", "PARKING",
    )),
    ("Groceries", (
        "LOBLAWS", "NO FRILLS", "FRESHCO", "METRO", "SOBEYS", "FOOD BASICS",
        "WHOLE FOODS", "REAL CANADIAN SUPERSTORE", "FARM BOY", "T&T", "WALMART SUPERCENTRE",
        "COSTCO", "LONGOS", "GROCERY", "SUPERMARKET",
    )),
    ("Dining", (
        "TIM HORTONS", "STARBUCKS", "MCDONALDS", "CHIPOTLE", "SUBWAY", "A&W",
        "WENDYS", "BURGER KING", "PIZZA", "SUSHI", "CAFE", "COFFEE", "BAKERY",
        "RESTAURANT", "PUB", "BAR", "GRILL", "BISTRO", "DINER",
    )),
    ("Subscriptions", (
        "SPOTIFY", "NETFLIX", "DISNEY PLUS", "DISNEYPLUS", "CRAVE", "APPLE.COM/BILL",
        "YOUTUBE PREMIUM", "PATREON",
    )),
    ("Bills & Utilities", (
        "TELECOM", "ROGERS", "BELL", "TELUS", "FIDO", "KOODO", "VIRGIN PLUS", "FREEDOM MOBILE",
        "HYDRO", "ENBRIDGE", "TORONTO HYDRO", "INSURANCE", "INTERNET",
    )),
    ("Health", (
        "SHOPPERS DRUG MART", "REXALL", "PHARMACY", "PHARMA", "DENTAL", "CLINIC",
        "PHYSIO", "OPTOMETR",
    )),
    ("Travel", ("AIR CANADA", "WESTJET", "PORTER", "VIA RAIL", "AIRBNB", "HOTEL", "EXPEDIA")),
    ("Entertainment", ("CINEPLEX", "TICKETMASTER", "STEAM", "PLAYSTATION", "NINTENDO")),
    ("Shopping", ("AMAZON", "BEST BUY", "WINNERS", "IKEA", "CANADIAN TIRE", "UNIQLO", "INDIGO")),
    ("Income/Refunds", ("CASHBACK", "CASH BACK", "INTEREST CREDIT", "REWARDS")),
]

_COMPILED = [
    (category, re.compile(r"(?<![A-Z0-9])(?:" + "|".join(map(re.escape, words)) + r")(?![A-Z0-9])"))
    for category, words in RULES
]


def match_rule(merchant: str) -> str | None:
    """Return the category for a normalized merchant name, or None if no rule applies."""
    for category, pattern in _COMPILED:
        if pattern.search(merchant):
            return category
    return None
