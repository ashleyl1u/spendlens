"""Tests for GeminiProvider with the HTTP layer mocked. Nothing here touches the network."""

import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.categorization.categories import CATEGORIES
from app.categorization.providers import (
    FAILED,
    FALLBACK,
    GeminiProvider,
    Result,
    get_provider,
)
from app.deps import get_llm_provider
from app.main import app
from app.models import MerchantCategory, Transaction

API_KEY = "test-key-SECRET-do-not-log"
MERCHANTS = ["MAPLE STREET BOOKS CO", "GARDEN DUMPLING HO", "ACMECLOUD"]
FIXTURE = Path(__file__).parent / "fixtures" / "rbc_credit_card_sample.csv"


def gemini_reply(results, finish_reason="STOP"):
    """A generateContent response whose text is the given results as JSON."""
    text = results if isinstance(results, str) else json.dumps({"results": results})
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish_reason}
        ]
    }


class FakeGemini:
    """Plays back queued responses and records every request it receives."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)


def make_provider(server, sleeps=None):
    return GeminiProvider(
        api_key=API_KEY,
        model="test-model",
        transport=httpx.MockTransport(server),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


GOOD = [
    {"category": "Shopping", "confidence": 0.9},
    {"category": "Dining", "confidence": 0.85},
    {"category": "Subscriptions", "confidence": 0.6},
]


# --- successful calls -------------------------------------------------------


def test_good_response():
    server = FakeGemini(gemini_reply(GOOD))
    results = make_provider(server).categorize(MERCHANTS)

    assert results == [
        Result("Shopping", 0.9),
        Result("Dining", 0.85),
        Result("Subscriptions", 0.6),
    ]
    assert all(r.cacheable for r in results)
    assert len(server.requests) == 1


def test_request_shape():
    server = FakeGemini(gemini_reply(GOOD))
    make_provider(server).categorize(MERCHANTS)
    request = server.requests[0]

    assert request.method == "POST"
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"
    )
    # The key goes in a header, never in the URL where it could end up in logs.
    assert request.headers["x-goog-api-key"] == API_KEY
    assert API_KEY not in str(request.url)

    config = json.loads(request.content)["generationConfig"]
    assert config["temperature"] == 0
    assert config["responseMimeType"] == "application/json"
    results_schema = config["responseJsonSchema"]["properties"]["results"]
    assert results_schema["items"]["properties"]["category"]["enum"] == list(CATEGORIES)


def test_prompt_defines_every_category():
    from app.categorization.categories import CATEGORY_DEFINITIONS

    assert list(CATEGORY_DEFINITIONS) == list(CATEGORIES)
    assert all(meaning.strip() for meaning in CATEGORY_DEFINITIONS.values())

    server = FakeGemini(gemini_reply(GOOD))
    make_provider(server).categorize(MERCHANTS)
    prompt = json.loads(server.requests[0].content)["systemInstruction"]["parts"][0]["text"]
    for name, meaning in CATEGORY_DEFINITIONS.items():
        assert f"- {name}: {meaning}." in prompt
    # The conventions the eval found Gemini getting wrong without definitions.
    assert "postage" in CATEGORY_DEFINITIONS["Other"]
    assert "government" in CATEGORY_DEFINITIONS["Other"]
    assert "liquor" in CATEGORY_DEFINITIONS["Shopping"]
    # Vague names must come back with low confidence, so they get flagged for review.
    assert "does not say what the business sells" in prompt
    assert "below 0.5" in prompt


def test_prompt_is_static_and_holds_no_user_data():
    """Definitions live in the system instruction, which is the same for every request;
    the only per-request content is still the merchant list and the categories."""
    first, second = FakeGemini(gemini_reply(GOOD)), FakeGemini(gemini_reply(GOOD))
    make_provider(first).categorize(MERCHANTS)
    make_provider(second).categorize(["A", "B", "C"])
    bodies = [json.loads(s.requests[0].content) for s in (first, second)]
    assert bodies[0]["systemInstruction"] == bodies[1]["systemInstruction"]
    assert not any(m in json.dumps(bodies[0]["systemInstruction"]) for m in MERCHANTS)


@pytest.mark.parametrize("size", [1, 45, 50, 200])
def test_schema_has_no_item_count_constraint(size):
    """Gemini answers 400 'Request contains an invalid argument' when minItems/maxItems
    reach the mid-40s, which failed every full batch of 50. The count is checked in
    code instead, so the schema must not carry it at any batch size."""
    merchants = [f"MERCHANT {i}" for i in range(size)]
    body = GeminiProvider(api_key=API_KEY).request_body(merchants)
    results_schema = body["generationConfig"]["responseJsonSchema"]["properties"]["results"]
    assert "minItems" not in results_schema and "maxItems" not in results_schema
    assert "minItems" not in json.dumps(body) and "maxItems" not in json.dumps(body)


def test_a_full_batch_with_a_short_reply_is_still_rejected():
    reply = [{"category": "Dining", "confidence": 0.9}] * 49
    merchants = [f"MERCHANT {i}" for i in range(50)]
    results = make_provider(FakeGemini(gemini_reply(reply))).categorize(merchants)
    assert results == [FAILED] * 50


def test_request_contains_only_merchant_names_and_categories(client, provider, engine):
    """Upload a real statement through the pipeline and inspect what would go to Gemini."""
    server = FakeGemini(gemini_reply([{"category": "Other", "confidence": 0.3}] * 5))
    gemini = make_provider(server)

    app.dependency_overrides[get_llm_provider] = lambda: gemini
    client.post("/auth/register", json={"email": "a@example.com", "password": "correct-horse"})
    token = client.post(
        "/auth/login", data={"username": "a@example.com", "password": "correct-horse"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_id = client.post(
        "/accounts", json={"nickname": "Visa", "last4": "4444"}, headers=headers
    ).json()["id"]
    response = client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": ("march.csv", FIXTURE.read_bytes(), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201

    assert len(server.requests) == 1
    body = json.loads(server.requests[0].content)
    # The only user content is a JSON object with exactly these two keys.
    (content,) = body["contents"]
    (part,) = content["parts"]
    payload = json.loads(part["text"])
    assert set(payload) == {"categories", "merchants"}
    assert payload["categories"] == list(CATEGORIES)
    assert payload["merchants"] == [
        "ACMECLOUD",
        "CA.SAMPLE-SHOP.COM",
        "GARDEN DUMPLING HO",
        "MAPLE STREET BOOKS CO",
        "RFBT-TORONTO YONGE ST",
    ]

    # Nothing from the statement beyond those names appears anywhere in the request.
    raw = server.requests[0].content.decode()
    for leaked in ["5555555555554444", "4444", "2024", "3/9/2024", "-18.5", "1850", "18.5",
                   "Visa", "a@example.com", "OTTAWA", "MISSISSAUGA", "Vancouver", "MasterCard",
                   "PAYMENT", "#2210", "TIM HORTONS"]:
        assert leaked not in raw, leaked


# --- untrusted output -------------------------------------------------------


def test_invalid_category_becomes_other():
    reply = [
        {"category": "Pizza", "confidence": 0.99},
        {"category": "Dining", "confidence": 0.85},
        {"category": "Subscriptions", "confidence": "very"},
    ]
    results = make_provider(FakeGemini(gemini_reply(reply))).categorize(MERCHANTS)

    assert results == [FALLBACK, Result("Dining", 0.85), FALLBACK]
    assert [r.cacheable for r in results] == [False, True, False]


@pytest.mark.parametrize(
    "reply",
    [
        gemini_reply("this is not json"),
        gemini_reply('{"results": [{"category": "Dining"'),  # cut off mid-object
        gemini_reply('{"answers": []}'),
        gemini_reply('{"results": "Dining"}'),
        gemini_reply('["Dining", "Dining", "Dining"]'),
        gemini_reply(GOOD, finish_reason="MAX_TOKENS"),
        {"candidates": []},
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]},
    ],
    ids=["not-json", "truncated", "wrong-key", "not-a-list", "bare-list", "max-tokens",
         "no-candidates", "blocked", "no-parts"],
)
def test_malformed_output_falls_back(reply):
    results = make_provider(FakeGemini(reply)).categorize(MERCHANTS)
    assert results == [FAILED] * len(MERCHANTS)


@pytest.mark.parametrize("count", [2, 4])
def test_wrong_number_of_items_falls_back(count):
    reply = [{"category": "Dining", "confidence": 0.9}] * count
    results = make_provider(FakeGemini(gemini_reply(reply))).categorize(MERCHANTS)
    assert results == [FAILED] * len(MERCHANTS)


# --- failures and retries ---------------------------------------------------


def test_timeout_falls_back_without_retrying(caplog):
    server = FakeGemini(httpx.ReadTimeout("slow"))
    with caplog.at_level(logging.WARNING):
        results = make_provider(server).categorize(MERCHANTS)

    assert results == [FAILED] * len(MERCHANTS)
    assert len(server.requests) == 1
    assert "timed out" in caplog.text


def test_connection_error_falls_back():
    server = FakeGemini(httpx.ConnectError("no network"))
    assert make_provider(server).categorize(MERCHANTS) == [FAILED] * len(MERCHANTS)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_rate_limit_and_server_errors_are_retried_once(status):
    sleeps = []
    server = FakeGemini(httpx.Response(status), gemini_reply(GOOD))
    results = make_provider(server, sleeps).categorize(MERCHANTS)

    assert results[0] == Result("Shopping", 0.9)
    assert len(server.requests) == 2
    assert sleeps == [GeminiProvider.RETRY_BACKOFF_SECONDS]


def test_retry_after_header_is_respected_but_capped():
    sleeps = []
    server = FakeGemini(
        httpx.Response(429, headers={"Retry-After": "3"}), gemini_reply(GOOD),
    )
    make_provider(server, sleeps).categorize(MERCHANTS)
    assert sleeps == [3.0]

    sleeps.clear()
    server = FakeGemini(
        httpx.Response(429, headers={"Retry-After": "3600"}), gemini_reply(GOOD),
    )
    make_provider(server, sleeps).categorize(MERCHANTS)
    assert sleeps == [GeminiProvider.MAX_RETRY_AFTER_SECONDS]


def test_gives_up_after_one_retry():
    server = FakeGemini(httpx.Response(429), httpx.Response(429))
    results = make_provider(server).categorize(MERCHANTS)

    assert results == [FAILED] * len(MERCHANTS)
    assert len(server.requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(status):
    server = FakeGemini(httpx.Response(status, json={"error": {"message": "nope"}}))
    results = make_provider(server).categorize(MERCHANTS)

    assert results == [FAILED] * len(MERCHANTS)
    assert len(server.requests) == 1


def test_googles_error_message_is_logged(caplog):
    server = FakeGemini(httpx.Response(
        400, json={"error": {"code": 400, "message": "Request contains an invalid argument.",
                             "status": "INVALID_ARGUMENT"}},
    ))
    with caplog.at_level(logging.WARNING):
        results = make_provider(server).categorize(MERCHANTS)

    assert results == [FAILED] * len(MERCHANTS)
    assert "HTTP 400: Request contains an invalid argument." in caplog.text
    # The request body (merchant names) is never logged.
    assert not any(merchant in caplog.text for merchant in MERCHANTS)


def test_retried_errors_also_carry_googles_message(caplog):
    busy = httpx.Response(503, json={"error": {"message": "The model is overloaded."}})
    server = FakeGemini(busy, busy)
    with caplog.at_level(logging.WARNING):
        make_provider(server).categorize(MERCHANTS)
    assert "HTTP 503: The model is overloaded." in caplog.text


@pytest.mark.parametrize(
    "response, expected",
    [
        (httpx.Response(400, json={"error": {"message": "x" * 500}}), "HTTP 400: " + "x" * 199 + "…"),
        (httpx.Response(400, json={"error": {"message": "two\n  lines"}}), "HTTP 400: two lines"),
        (httpx.Response(400, text="<html>Bad Request</html>"), "HTTP 400)"),
        (httpx.Response(400, json={"error": "flat string"}), "HTTP 400)"),
        (httpx.Response(400, json={"error": {"message": 42}}), "HTTP 400)"),
    ],
    ids=["truncated", "whitespace", "not-json", "no-message-field", "message-not-text"],
)
def test_error_message_is_short_and_safe(caplog, response, expected):
    with caplog.at_level(logging.WARNING):
        make_provider(FakeGemini(response)).categorize(MERCHANTS)
    assert expected in caplog.text


def test_api_key_is_never_logged(caplog):
    server = FakeGemini(
        httpx.Response(403, json={"error": {"message": f"API key {API_KEY} not valid"}}),
    )
    provider = make_provider(server)
    with caplog.at_level(logging.DEBUG):
        provider.categorize(MERCHANTS)

    assert "Gemini categorization failed" in caplog.text
    assert "HTTP 403: API key [redacted] not valid" in caplog.text
    assert API_KEY not in caplog.text
    assert API_KEY not in repr(provider)


# --- failures through the upload --------------------------------------------


def test_failed_batch_still_uploads_and_is_not_cached(client, engine):

    server = FakeGemini(httpx.ReadTimeout("slow"))
    app.dependency_overrides[get_llm_provider] = lambda: make_provider(server)
    client.post("/auth/register", json={"email": "a@example.com", "password": "correct-horse"})
    token = client.post(
        "/auth/login", data={"username": "a@example.com", "password": "correct-horse"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_id = client.post("/accounts", json={"nickname": "Visa"}, headers=headers).json()["id"]

    response = client.post(
        "/uploads",
        data={"account_id": str(account_id)},
        files={"file": ("march.csv", FIXTURE.read_bytes(), "text/csv")},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["inserted"] == 24
    with Session(engine) as db:
        flagged = db.scalars(
            select(Transaction).where(Transaction.category_source == "llm")
        ).all()
        assert len(flagged) == 6
        assert all(t.category == "Other" and t.needs_review for t in flagged)
        assert db.scalar(select(func.count()).select_from(MerchantCategory)) == 0


# --- configuration ----------------------------------------------------------


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
        get_provider()

    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
        get_provider()


def test_app_refuses_to_start_without_a_key(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        with TestClient(app):
            pass


def test_gemini_is_selected_with_default_and_custom_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", API_KEY)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    provider = get_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.model == GeminiProvider.DEFAULT_MODEL == "gemini-3.5-flash-lite"

    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    assert get_provider().model == "gemini-3.8-flash"
