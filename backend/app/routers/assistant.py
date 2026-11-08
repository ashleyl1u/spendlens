import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ..assistant.models import Assistant, AssistantUnavailable, get_assistant
from ..assistant.service import answer_question
from ..deps import CurrentUser, DbSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])

UNAVAILABLE = "The assistant is unavailable right now. Please try again in a minute."


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]


class AskResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCallOut]


def get_assistant_dep() -> Assistant:
    return get_assistant()


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    db: DbSession,
    user: CurrentUser,
    assistant: Annotated[Assistant, Depends(get_assistant_dep)],
) -> AskResponse:
    try:
        result = answer_question(db, user.id, body.question, assistant, date.today())
    except AssistantUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNAVAILABLE)
    except Exception as exc:
        # Anything unexpected from the model layer is still the model's fault, not a
        # server crash: log its type only (no question text, no key) and say so.
        logger.error("Assistant failed unexpectedly (%s)", type(exc).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNAVAILABLE)
    return AskResponse(
        answer=result.answer,
        tool_calls=[ToolCallOut(name=c.name, arguments=c.arguments) for c in result.tool_calls],
    )
