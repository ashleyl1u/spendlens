"""Turn a raw statement description into a stable merchant name.

"TIM HORTONS #2210 TORONTO" and "Tim Hortons 1187 Mississauga" should both become
"TIM HORTONS", so one cached category covers every branch of a chain.
"""

import re

# Payment processors put their own tag in front of the merchant: Square, Toast, PayPal.
PROCESSOR_PREFIX = re.compile(r"^(?:SQ\s*\*|TST\s*[*-]|PAYPAL\s*\*|\*)\s*")

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


def normalize_merchant(raw_description: str) -> str:
    text = raw_description.upper().strip()
    text = PROCESSOR_PREFIX.sub("", text)

    # "UBER *TRIP HELP.UBER.COM" and "ACMECLOUD *STORAGE PLA": what follows the
    # asterisk describes the product, not the merchant.
    text = text.split("*", 1)[0] if "*" in text else text

    # MCDONALD'S and MCDONALDS are the same place; commas and stray dashes are noise.
    text = text.replace("'", "").replace(",", " ")
    tokens = [token for token in text.split() if token.strip("-/.")]

    # Store numbers and cities alternate in any order ("#417 MISSISSAUGA",
    # "1 800 555 0123 OTTAWA"), so keep peeling until neither applies.
    while _strip_trailing_city(tokens) or _strip_trailing_reference(tokens):
        pass

    return " ".join(token.strip(".") or token for token in tokens)
