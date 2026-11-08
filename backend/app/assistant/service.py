"""The bounded tool loop that turns a question into an answer."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from .models import (
    Assistant,
    AssistantOutputError,
    Message,
    ModelTurn,
    Question,
    ToolResults,
    describe_question,
)
from .tools import run_tool

logger = logging.getLogger(__name__)

MAX_ROUND_TRIPS = 4
MAX_CALLS_PER_TURN = 8  # bounds the database work one model reply can ask for

COULD_NOT_ANSWER = (
    "Sorry, I couldn't answer that. Try asking about your spending in a simpler way, "
    'for example "How much did I spend on dining last month?"'
)


@dataclass(frozen=True)
class RecordedCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Answer:
    answer: str
    tool_calls: list[RecordedCall]


def answer_question(
    db: Session, user_id: int, question: str, assistant: Assistant, today: date
) -> Answer:
    """Ask the model, run the tools it requests for user_id, and repeat until it
    answers in text or MAX_ROUND_TRIPS is used up.

    Raises AssistantUnavailable when the model cannot be reached. Unusable model
    output becomes the polite COULD_NOT_ANSWER reply rather than an error.
    """
    history: list[Message] = [Question(question)]
    recorded: list[RecordedCall] = []

    for round_trip in range(1, MAX_ROUND_TRIPS + 1):
        try:
            turn = assistant.respond(history, today)
        except AssistantOutputError:
            return Answer(COULD_NOT_ANSWER, recorded)

        if not turn.calls:
            if turn.text and turn.text.strip():
                logger.info(
                    "Assistant answered a question (%s) in %d round trip(s) using %s",
                    describe_question(question),
                    round_trip,
                    [call.name for call in recorded] or "no tools",
                )
                return Answer(turn.text.strip(), recorded)
            return Answer(COULD_NOT_ANSWER, recorded)

        if round_trip == MAX_ROUND_TRIPS:
            break  # the model still wants tools, but it has had its last turn
        history += [turn, _run_calls(db, user_id, turn, recorded)]

    logger.info(
        "Assistant hit the %d round-trip limit on a question (%s)",
        MAX_ROUND_TRIPS,
        describe_question(question),
    )
    return Answer(COULD_NOT_ANSWER, recorded)


def _run_calls(
    db: Session, user_id: int, turn: ModelTurn, recorded: list[RecordedCall]
) -> ToolResults:
    results = []
    for index, call in enumerate(turn.calls):
        if index >= MAX_CALLS_PER_TURN:
            result = {"error": f"Too many tool calls at once; at most {MAX_CALLS_PER_TURN}."}
        else:
            # user_id comes from the authenticated request, never from the model.
            result = run_tool(db, user_id, call.name, call.arguments)
            recorded.append(
                RecordedCall(
                    call.name, call.arguments if isinstance(call.arguments, dict) else {}
                )
            )
        results.append((call, result))
    return ToolResults(tuple(results))
