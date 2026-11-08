"""Tests for POST /assistant/ask, the tool loop and the tools. No network: the fake
assistant is scripted, and Gemini's HTTP layer is mocked."""

import json
import logging
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.models import (
    FakeAssistant,
    GeminiAssistant,
    ModelTurn,
    ToolCall,
    ToolResults,
    format_cad,
    get_assistant,
)
from app.assistant.service import COULD_NOT_ANSWER, MAX_ROUND_TRIPS
from app.assistant.tools import run_tool
from app.main import app
from app.models import User
from app.routers.assistant import UNAVAILABLE, get_assistant_dep

FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"
TOTAL_SPENT = 39306  # worked out by hand in test_dashboard.py
API_KEY = "test-key-SECRET-do-not-log"


# --- helpers --------------------------------------------------------------------


def sign_up(client, email):
    client.post("/auth/register", json={"email": email, "password": "correct-horse"})
    token = client.post(
        "/auth/login", data={"username": email, "password": "correct-horse"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload_fixture(client, headers):
    account_id = client.post("/accounts", json={"nickname": "Visa"}, headers=headers).json()["id"]
    response = client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": ("march.csv", FIXTURE.read_bytes(), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201
    return account_id


def use(assistant):
    app.dependency_overrides[get_assistant_dep] = lambda: assistant
    return assistant


def ask(client, headers, question="How much did I spend?"):
    return client.post("/assistant/ask", json={"question": question}, headers=headers)


def tool_results(history):
    """Every (call, result) the server sent back to the model, in order."""
    return [pair for m in history if isinstance(m, ToolResults) for pair in m.results]


def last_results(history):
    return [result for _, result in history[-1].results]


@pytest.fixture()
def alice(client):
    headers = sign_up(client, "alice@example.com")
    upload_fixture(client, headers)
    return headers


# --- the tool loop, with the fake assistant -------------------------------------


def test_one_tool_call_and_a_correct_answer(client, alice):
    def script(history):
        if len(history) == 1:
            return ModelTurn(calls=(ToolCall("spending_summary", {}),))
        total = last_results(history)[0]["result"]["total_spent_cents"]
        return ModelTurn(text=f"You spent {format_cad(total)} in total.")

    assistant = use(FakeAssistant(script))
    response = ask(client, alice)

    assert response.status_code == 200
    assert response.json() == {
        "answer": "You spent $393.06 in total.",
        "tool_calls": [{"name": "spending_summary", "arguments": {}}],
    }
    assert len(assistant.requests) == 2


def test_default_fake_assistant_answers_from_the_summary(client, alice):
    use(FakeAssistant())
    assert ask(client, alice).json()["answer"] == "You spent $393.06 across 23 transactions."


def test_several_tool_calls(client, alice):
    script = [
        ModelTurn(calls=(
            ToolCall("spending_by_category", {"start": "2024-03-01", "end": "2024-03-31"}),
            ToolCall("top_merchants", {"limit": 2}),
        )),
        ModelTurn(calls=(ToolCall("spending_by_month", {}),)),
        ModelTurn(text="Groceries led March."),
    ]
    assistant = use(FakeAssistant(script))
    body = ask(client, alice, "What did I spend most on in March?").json()

    assert body["answer"] == "Groceries led March."
    assert [c["name"] for c in body["tool_calls"]] == [
        "spending_by_category", "top_merchants", "spending_by_month",
    ]
    by_category, top, by_month = [result["result"] for _, result in
                                  tool_results(assistant.requests[-1])]
    assert by_category[0]["category"] == "Groceries"
    assert by_category[0]["total_cents"] == 11656
    assert [m["merchant"] for m in top] == ["METRO", "ACME TELECOM"]
    assert [m["month"] for m in by_month] == ["2024-03", "2024-04"]


@pytest.mark.parametrize(
    "call, message",
    [
        (ToolCall("spending_summary", {"start": "2024-03-10", "end": "2024-03-01"}), "before start"),
        (ToolCall("spending_summary", {"start": "March 1st"}), "not a valid YYYY-MM-DD"),
        (ToolCall("spending_summary", {"start": "20240301"}), "not a valid YYYY-MM-DD"),
        (ToolCall("spending_summary", {"start": 20240301}), "must be a YYYY-MM-DD string"),
        (ToolCall("spending_summary", {"end": "2024-02-30"}), "not a valid YYYY-MM-DD"),
        (ToolCall("top_merchants", {"limit": 0}), "limit must be"),
        (ToolCall("top_merchants", {"limit": 51}), "limit must be"),
        (ToolCall("top_merchants", {"limit": "ten"}), "limit must be"),
        (ToolCall("top_merchants", {"limit": True}), "limit must be"),
        (ToolCall("top_merchants", {"limit": 2.5}), "limit must be"),
        (ToolCall("spending_summary", {"limit": 5}), "Unknown argument(s) limit"),
        (ToolCall("spending_summary", ["2024-03-01"]), "must be an object"),
        (ToolCall("delete_everything", {}), "Unknown tool"),
    ],
)
def test_bad_tool_call_is_reported_back_to_the_model(client, alice, call, message):
    assistant = use(FakeAssistant([
        ModelTurn(calls=(call,)),
        ModelTurn(text="Sorry, that date range doesn't work."),
    ]))
    response = ask(client, alice)

    assert response.status_code == 200
    assert response.json()["answer"] == "Sorry, that date range doesn't work."
    (result,) = last_results(assistant.requests[1])
    assert set(result) == {"error"}
    assert message in result["error"]


def test_whole_number_float_limit_is_accepted(client, alice):
    assistant = use(FakeAssistant([
        ModelTurn(calls=(ToolCall("top_merchants", {"limit": 3.0}),)),
        ModelTurn(text="ok"),
    ]))
    ask(client, alice)
    assert len(last_results(assistant.requests[1])[0]["result"]) == 3


def test_tool_loop_stops_at_the_limit(client, alice):
    assistant = use(FakeAssistant(lambda history: ModelTurn(calls=(ToolCall("spending_summary", {}),))))
    response = ask(client, alice)

    assert response.status_code == 200
    assert response.json()["answer"] == COULD_NOT_ANSWER
    assert len(assistant.requests) == MAX_ROUND_TRIPS
    # Tools ran for every round trip but the last, whose request was not executed.
    assert len(response.json()["tool_calls"]) == MAX_ROUND_TRIPS - 1


def test_too_many_calls_in_one_turn_are_capped(client, alice):
    calls = tuple(ToolCall("spending_summary", {}) for _ in range(12))
    assistant = use(FakeAssistant([ModelTurn(calls=calls), ModelTurn(text="done")]))
    body = ask(client, alice).json()

    results = last_results(assistant.requests[1])
    assert sum("result" in r for r in results) == 8
    assert sum("error" in r for r in results) == 4
    assert len(body["tool_calls"]) == 8


@pytest.mark.parametrize("turn", [ModelTurn(), ModelTurn(text="   ")])
def test_empty_model_answer_is_a_polite_reply(client, alice, turn):
    use(FakeAssistant([turn]))
    response = ask(client, alice)
    assert (response.status_code, response.json()["answer"]) == (200, COULD_NOT_ANSWER)


# --- isolation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "smuggled",
    [{"user_id": "ALICE"}, {"account_id": "ALICE_ACCOUNT"},
     {"user_id": "ALICE", "account_id": "ALICE_ACCOUNT", "start": "2024-01-01"}],
)
def test_model_cannot_choose_the_user_or_account(client, engine, smuggled):
    alice = sign_up(client, "alice@example.com")
    alice_account = upload_fixture(client, alice)
    bob = sign_up(client, "bob@example.com")
    with Session(engine) as db:
        alice_id = db.scalar(select(User.id).where(User.email == "alice@example.com"))
    arguments = {
        key: {"ALICE": alice_id, "ALICE_ACCOUNT": alice_account}.get(value, value)
        for key, value in smuggled.items()
    }

    assistant = use(FakeAssistant([
        ModelTurn(calls=(ToolCall("spending_summary", arguments),
                         ToolCall("top_merchants", arguments))),
        ModelTurn(calls=(ToolCall("spending_summary", {}),)),
        ModelTurn(text="done"),
    ]))
    assert ask(client, bob).status_code == 200

    rejected = last_results(assistant.requests[1])
    assert all("Unknown argument" in r["error"] for r in rejected)
    (bob_summary,) = last_results(assistant.requests[2])
    assert bob_summary["result"]["total_spent_cents"] == 0


def test_bob_never_gets_alices_numbers(client, alice):
    bob = sign_up(client, "bob@example.com")
    every_tool = (
        ToolCall("spending_summary", {}),
        ToolCall("spending_by_category", {}),
        ToolCall("spending_by_month", {"start": "2024-01-01", "end": "2024-12-31"}),
        ToolCall("top_merchants", {"limit": 50}),
    )
    assistant = use(FakeAssistant([ModelTurn(calls=every_tool), ModelTurn(text="ok")]))
    ask(client, bob, "How much did alice@example.com spend?")

    summary, categories, months, merchants = [r["result"] for r in last_results(assistant.requests[1])]
    assert summary["total_spent_cents"] == 0
    assert categories == [] and merchants == []
    assert all(m["total_cents"] == 0 for m in months)
    sent = json.dumps([r for _, r in tool_results(assistant.requests[1])])
    assert "METRO" not in sent and "39306" not in sent

    # Alice still gets her own.
    use(FakeAssistant())
    assert "$393.06" in ask(client, alice).json()["answer"]


def test_user_with_no_transactions(client):
    empty = sign_up(client, "empty@example.com")
    use(FakeAssistant())
    response = ask(client, empty)
    assert response.status_code == 200
    assert response.json()["answer"] == "You spent $0.00 across 0 transactions."


def test_run_tool_always_uses_the_given_user(client, alice, engine):
    with Session(engine) as db:
        alice_id = db.scalar(select(User.id))
        assert run_tool(db, alice_id, "spending_summary", {})["result"]["total_spent_cents"] == TOTAL_SPENT
        assert run_tool(db, alice_id + 1, "spending_summary", {})["result"]["total_spent_cents"] == 0


# --- request validation and auth ----------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{"question": "x" * 501}, {"question": ""}, {"question": "   "}, {}, {"question": 5}],
)
def test_bad_questions_are_rejected(client, alice, body):
    use(FakeAssistant())
    assert client.post("/assistant/ask", json=body, headers=alice).status_code == 422


def test_question_of_exactly_500_characters_is_accepted(client, alice):
    use(FakeAssistant())
    assert ask(client, alice, "x" * 500).status_code == 200


def test_auth_is_required(client):
    use(FakeAssistant())
    assert client.post("/assistant/ask", json={"question": "hi"}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.post("/assistant/ask", json={"question": "hi"}, headers=bad).status_code == 401


def test_unexpected_assistant_error_is_a_503_without_a_traceback(client, alice):
    def broken(history):
        raise ZeroDivisionError("boom")

    use(FakeAssistant(broken))
    response = ask(client, alice)
    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}


# --- gemini, with HTTP mocked ------------------------------------------------------------


class FakeGemini:
    """Plays back queued responses and records every request body."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)


def function_call(name, args, signature="sig-abc"):
    return {
        "candidates": [{
            "content": {"role": "model", "parts": [
                {"functionCall": {"name": name, "args": args, "id": f"call-{name}"},
                 "thoughtSignature": signature},
            ]},
            "finishReason": "STOP",
        }]
    }


def text_reply(text):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                            "finishReason": "STOP"}]}


def gemini(server):
    return use(GeminiAssistant(api_key=API_KEY, model="test-model",
                               transport=httpx.MockTransport(server), sleep=lambda _: None))


def test_gemini_round_trip(client, alice):
    server = FakeGemini(
        function_call("spending_by_category", {"start": "2024-03-01", "end": "2024-03-31"}),
        text_reply("You spent the most on Groceries: $116.56."),
    )
    gemini(server)
    response = ask(client, alice, "What did I spend most on in March?")

    assert response.status_code == 200
    assert response.json() == {
        "answer": "You spent the most on Groceries: $116.56.",
        "tool_calls": [{"name": "spending_by_category",
                        "arguments": {"start": "2024-03-01", "end": "2024-03-31"}}],
    }

    first, second = server.bodies
    assert server.requests[0].headers["x-goog-api-key"] == API_KEY
    assert first["generationConfig"]["temperature"] == 0
    declared = [f["name"] for f in first["tools"][0]["functionDeclarations"]]
    assert declared == ["spending_summary", "spending_by_category", "spending_by_month",
                        "top_merchants"]
    for declaration in first["tools"][0]["functionDeclarations"]:
        properties = declaration["parametersJsonSchema"]["properties"]
        assert "user_id" not in properties and "account_id" not in properties

    prompt = first["systemInstruction"]["parts"][0]["text"]
    assert date.today().isoformat() in prompt
    assert "cents" in prompt and "never instructions" in prompt

    # The model's own turn goes back unchanged (thought signature included), followed
    # by the tool result matched to the call id.
    assert second["contents"][1]["parts"][0]["thoughtSignature"] == "sig-abc"
    response_part = second["contents"][2]["parts"][0]["functionResponse"]
    assert response_part["name"] == "spending_by_category"
    assert response_part["id"] == "call-spending_by_category"
    assert response_part["response"]["result"][0] == {
        "category": "Groceries", "total_cents": 11656, "transaction_count": 2,
        "share": pytest.approx(11656 / (TOTAL_SPENT - 1099)),
    }


def test_gemini_requests_contain_only_the_question_and_aggregates(client, alice):
    server = FakeGemini(
        function_call("spending_summary", {}),
        function_call("top_merchants", {"limit": 50}),
        function_call("spending_by_month", {}),
        text_reply("Done."),
    )
    gemini(server)
    ask(client, alice, "Where does my money go?")

    sent = json.dumps(server.bodies)
    # Raw statement text, card numbers, single amounts and per-row dates never leave.
    for leaked in ["TIM HORTONS #2210 TORONTO", "SQ *CORNER BAKERY", "MOBI/SK4M9Q2LTV",
                   "5555555555554444", "-3.12", "-64.38", "2024-03-05", "2024-03-16",
                   "alice@example.com", "row_hash", "raw_description", "amount_cents",
                   "account_id\": 1", "user_id\": 1"]:
        assert leaked not in sent, leaked
    # What does go: the question and aggregate results, including merchant names.
    assert "Where does my money go?" in sent
    assert "TIM HORTONS" in sent and "total_cents" in sent


def test_gemini_timeout_is_a_503(client, alice, caplog):
    gemini(FakeGemini(httpx.ReadTimeout("slow")))
    with caplog.at_level(logging.DEBUG):
        response = ask(client, alice, "A very private question about my rent")

    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}
    assert "timed out" in caplog.text
    assert API_KEY not in caplog.text
    assert "private question" not in caplog.text


def test_gemini_rate_limit_is_retried_once_then_503(client, alice):
    server = FakeGemini(httpx.Response(429), httpx.Response(429))
    gemini(server)
    assert ask(client, alice).status_code == 503
    assert len(server.requests) == 2


def test_gemini_rate_limit_then_success(client, alice):
    gemini(FakeGemini(httpx.Response(503), text_reply("I need more detail.")))
    assert ask(client, alice).json()["answer"] == "I need more detail."


@pytest.mark.parametrize(
    "reply",
    [
        {"candidates": []},
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]},
        {"candidates": [{"content": {"parts": [{"text": "half"}]}, "finishReason": "MAX_TOKENS"}]},
        {"candidates": [{"content": {"parts": [{"functionCall": {"args": {}}}]}}]},
        {"unexpected": True},
        httpx.Response(200, text="<html>not json</html>"),
    ],
    ids=["no-candidates", "blocked", "no-parts", "max-tokens", "call-without-name",
         "wrong-shape", "not-json"],
)
def test_gemini_unusable_output_never_crashes(client, alice, reply):
    gemini(FakeGemini(reply))
    response = ask(client, alice)
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert response.json()["answer"] == COULD_NOT_ANSWER
    else:
        assert response.json() == {"detail": UNAVAILABLE}


def test_gemini_question_text_is_not_logged_on_success(client, alice, caplog):
    gemini(FakeGemini(text_reply("ok")))
    with caplog.at_level(logging.DEBUG):
        ask(client, alice, "Secret question about my therapist bills")
    assert "therapist" not in caplog.text
    assert API_KEY not in caplog.text


# --- selection --------------------------------------------------------------------


def test_assistant_follows_llm_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_assistant(), FakeAssistant)

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
        get_assistant()

    monkeypatch.setenv("GEMINI_API_KEY", API_KEY)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    assistant = get_assistant()
    assert isinstance(assistant, GeminiAssistant)
    assert assistant.model == "gemini-3.8-flash"
    assert API_KEY not in repr(assistant)
