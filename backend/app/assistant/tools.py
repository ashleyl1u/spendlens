"""The tools the assistant's model may call: thin wrappers over app.queries.

The model only ever chooses start, end and (for top_merchants) limit. The user id is
always the authenticated user's, supplied by the server, and there is no way to name
an account, so a tool call can never read another user's data. Every argument is
validated here; a bad call returns {"error": ...} for the model to read, never raises.
"""

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from .. import queries

MAX_LIMIT = 50

_DATE = {"type": "string", "description": "ISO date, YYYY-MM-DD. Inclusive. Omit for no bound."}
_RANGE = {"start": _DATE, "end": _DATE}

AMOUNTS_NOTE = "All amounts are integer cents in CAD; refunds are negative. Transfers are excluded."


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, dict]


TOOLS: list[ToolSpec] = [
    ToolSpec(
        "spending_summary",
        "Total spent, number of transactions, how many need review, and the first and "
        f"last transaction dates in a date range. {AMOUNTS_NOTE}",
        _RANGE,
    ),
    ToolSpec(
        "spending_by_category",
        "Spending per category, largest first, with each category's share of the total. "
        + AMOUNTS_NOTE,
        _RANGE,
    ),
    ToolSpec(
        "spending_by_month",
        "Spending per calendar month (YYYY-MM), oldest first, with empty months as zero. "
        + AMOUNTS_NOTE,
        _RANGE,
    ),
    ToolSpec(
        "top_merchants",
        "The merchants with the most spending, largest first. " + AMOUNTS_NOTE,
        {
            **_RANGE,
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_LIMIT,
                "description": f"How many merchants to return, 1 to {MAX_LIMIT}. Default 10.",
            },
        },
    ),
]
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


class ToolArgumentError(ValueError):
    pass


def run_tool(db: Session, user_id: int, name: str, arguments: Any) -> dict:
    """Run one tool call for user_id and return a JSON-ready result or error."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"error": f"Unknown tool {name!r}. Available: {', '.join(TOOLS_BY_NAME)}."}
    try:
        filters, limit = _parse_arguments(tool, arguments)
    except ToolArgumentError as exc:
        return {"error": str(exc)}

    if name == "spending_summary":
        result = queries.spending_summary(db, user_id, filters)
    elif name == "spending_by_category":
        result = queries.spending_by_category(db, user_id, filters)
    elif name == "spending_by_month":
        result = queries.spending_by_month(db, user_id, filters)
    else:
        result = queries.top_merchants(db, user_id, filters, limit)
    return {"result": _to_json(result)}


def _parse_arguments(tool: ToolSpec, arguments: Any) -> tuple[queries.Filters, int]:
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolArgumentError("Arguments must be an object.")
    unknown = sorted(set(arguments) - set(tool.parameters))
    if unknown:
        raise ToolArgumentError(
            f"Unknown argument(s) {', '.join(unknown)}. "
            f"{tool.name} accepts only: {', '.join(tool.parameters)}."
        )

    start = _parse_date(arguments.get("start"), "start")
    end = _parse_date(arguments.get("end"), "end")
    if start and end and end < start:
        raise ToolArgumentError(f"end ({end}) is before start ({start}).")

    limit = arguments.get("limit", 10)
    # JSON numbers can arrive as 5.0; accept those, but never True/False or 5.5.
    if isinstance(limit, float) and limit.is_integer():
        limit = int(limit)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ToolArgumentError(f"limit must be a whole number from 1 to {MAX_LIMIT}.")

    # account_id is deliberately never set: the model cannot choose an account.
    return queries.Filters(start=start, end=end), limit


def _parse_date(value: Any, name: str) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ToolArgumentError(f"{name} must be a YYYY-MM-DD string.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ToolArgumentError(f"{name} {value!r} is not a valid YYYY-MM-DD date.")
    if len(value) != 10:  # fromisoformat also takes 20240301 and week dates
        raise ToolArgumentError(f"{name} {value!r} is not a valid YYYY-MM-DD date.")
    return parsed


def _to_json(value: Any) -> Any:
    if is_dataclass(value):
        return _to_json(asdict(value))
    if isinstance(value, dict):
        return {key: _to_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value
