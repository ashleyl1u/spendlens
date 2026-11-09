"""Turn a raw statement description into a stable merchant name.

"TIM HORTONS #2210 TORONTO" and "Tim Hortons 1187 Mississauga" should both become
"TIM HORTONS", so one cached category covers every branch of a chain.
"""

import re

# Payment processors put their own tag in front of the merchant: Square, Toast, PayPal,
# DoorDash ("DD *DOORDASH WENDYS") and Shopify ("SP *MATCHA DIRECT").
PROCESSOR_PREFIX = re.compile(r"^(?:SQ\s*\*|TST\s*[*-]|PAYPAL\s*\*|DD\s*\*|SP\s*\*|\*)\s*")

# Brands that sell several different services, which belong in different categories:
# "UBER *EATS" is a meal, "UBER* ONE MEMBERSHIP" a subscription, "UBER *TRIP" a ride.
# For these brands the first word after the asterisk names the service and is kept,
# whatever it is, so a service nobody has listed yet still gets its own merchant name
# (and its own cache entry) instead of being merged into the bare brand. Skipped:
# reference codes (any digit), web addresses, and a repeat of the brand
# ("GOOGLE *GOOGLE ONE"). The listed words mean the brand's core service and collapse
# to the bare brand.
MULTI_SERVICE_BRANDS: dict[str, set[str]] = {
    "UBER": {"TRIP", "PENDING"},
    "GOOGLE": set(),
    "AMAZON": set(),
    "AMAZON.CA": set(),
}

PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
# Online services often end with a country code instead ("NETFLIX.COM 866-579-7172 CA").
PROVINCES |= {"CA", "CAN", "US", "USA", "GB", "GBR", "IE", "NL", "SE", "LU"}

# Cities that show up at the end of descriptions. Multi-word names are matched as a
# whole, so "SAN FRANCISCO" is removed but a merchant called "SAN" is not.
CITIES = {
    "BRAMPTON", "BURNABY", "CALGARY", "EDMONTON", "ETOBICOKE", "GATINEAU", "HALIFAX",
    "HAMILTON", "KITCHENER", "LAVAL", "LONDON", "MARKHAM", "MISSISSAUGA", "MONTREAL",
    "NORTH YORK", "NORTH VANCOUVER", "OAKVILLE", "OTTAWA", "QUEBEC", "REGINA",
    "RICHMOND", "RICHMOND HILL", "SASKATOON", "SCARBOROUGH", "SURREY", "TORONTO",
    "VANCOUVER", "VAUGHAN", "VICTORIA", "WATERLOO", "WINNIPEG",
    # Common foreign billing locations for online services.
    "AMSTERDAM", "DUBLIN", "LONDON GB", "LOS GATOS", "LUXEMBOURG", "NEW YORK",
    "SAN FRANCISCO", "SAN JOSE", "SEATTLE", "STOCKHOLM",
}
CITY_TOKENS = sorted((city.split() for city in CITIES), key=len, reverse=True)


def _strip_trailing_city(tokens: list[str]) -> bool:
    """Remove one trailing city or province, keeping at least one token. True if removed."""
    if len(tokens) > 1 and tokens[-1] in PROVINCES:
        tokens.pop()
        return True
    for city in CITY_TOKENS:
        if len(tokens) > len(city) and tokens[-len(city):] == city:
            del tokens[-len(city):]
            return True
    return False


def _strip_trailing_reference(tokens: list[str]) -> bool:
    """Remove one trailing store or reference number such as #2210, 3358 or SK4M9Q2LTV."""
    if len(tokens) > 1 and any(ch.isdigit() for ch in tokens[-1]):
        tokens.pop()
        return True
    return False


def _service_word(brand: str, tail: str) -> str | None:
    """The word after the asterisk that names one of a brand's services, if any."""
    for word in tail.replace("*", " ").split():
        if word == brand or "." in word or any(ch.isdigit() for ch in word):
            continue  # "GOOGLE *GOOGLE ONE", "HELP.UBER.COM", "*1A2B3C4D5"
        return None if word in MULTI_SERVICE_BRANDS[brand] else word
    return None


def normalize_merchant(raw_description: str) -> str:
    text = raw_description.upper().strip()
    text = PROCESSOR_PREFIX.sub("", text)

    # "UBER *TRIP HELP.UBER.COM" and "ACMECLOUD *STORAGE PLA": what follows the
    # asterisk describes the product, not the merchant, except for a few platforms.
    if "*" in text:
        head, tail = (part.strip() for part in text.split("*", 1))
        service = _service_word(head, tail) if head in MULTI_SERVICE_BRANDS else None
        text = f"{head} {service}" if service else head

    # MCDONALD'S and MCDONALDS are the same place; commas and stray dashes are noise.
    text = text.replace("'", "").replace(",", " ")
    tokens = [token for token in text.split() if token.strip("-/.")]

    # Store numbers and cities alternate in any order ("#417 MISSISSAUGA",
    # "1 800 555 0123 OTTAWA"), so keep peeling until neither applies.
    while _strip_trailing_city(tokens) or _strip_trailing_reference(tokens):
        pass

    return " ".join(token.strip(".") or token for token in tokens)
