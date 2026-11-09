"""Shared plumbing for calling the Gemini API: settings, timeout, one retry.

Used by both the merchant categorizer and the question assistant. The API key is sent
in a header and never appears in URLs, logs or reprs.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TIMEOUT_SECONDS = 20.0
RETRY_BACKOFF_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 10.0  # never stall a request longer than this on a 429


MAX_ERROR_MESSAGE_CHARS = 200


class GeminiAPIError(Exception):
    """Gemini answered with an HTTP error. `message` is Google's own explanation (the
    "message" field of its error JSON), truncated and with the API key removed."""

    def __init__(self, status: int, message: str = "", retry_after: float | None = None):
        super().__init__(f"HTTP {status}" + (f": {message}" if message else ""))
        self.status = status
        self.message = message
        self.retry_after = retry_after


class GeminiError(GeminiAPIError):
    """A Gemini call that failed in a way worth one retry (429 or 5xx)."""


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL


def settings_from_env() -> GeminiSettings:
    """Read GEMINI_API_KEY and GEMINI_MODEL, failing clearly if the key is missing."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set; add it to .env "
            "or set LLM_PROVIDER=fake"
        )
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    return GeminiSettings(api_key=api_key, model=model)


class GeminiClient:
    """POSTs to generateContent with a timeout and one retry on 429 or 5xx.

    Raises GeminiError (429 or 5xx, still failing after the retry), GeminiAPIError
    (other HTTP errors, not retried), httpx.HTTPError (timeouts, connection errors) or
    ValueError (a body that is not JSON).
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self._api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport  # tests pass httpx.MockTransport
        self._sleep = sleep

    def __repr__(self) -> str:  # keep the key out of tracebacks and debug output
        return f"GeminiClient(model={self.model!r})"

    def generate(self, body: dict) -> dict:
        try:
            return self._post(body)
        except GeminiError as exc:
            delay = exc.retry_after or RETRY_BACKOFF_SECONDS
            self._sleep(min(delay, MAX_RETRY_AFTER_SECONDS))
            return self._post(body)

    def _post(self, body: dict) -> dict:
        url = f"{BASE_URL}/models/{self.model}:generateContent"
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            response = client.post(url, json=body, headers={"x-goog-api-key": self._api_key})
        status = response.status_code
        if status == 429 or status >= 500:
            raise GeminiError(status, self._error_message(response), _retry_after(response))
        if status >= 400:
            raise GeminiAPIError(status, self._error_message(response))
        return response.json()

    def _error_message(self, response: httpx.Response) -> str:
        """Google's error message, safe to log: only the "message" field (never the
        request body), with the API key redacted, truncated."""
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            return ""
        if not isinstance(message, str):
            return ""
        message = " ".join(message.replace(self._api_key, "[redacted]").split())
        if len(message) > MAX_ERROR_MESSAGE_CHARS:
            message = message[: MAX_ERROR_MESSAGE_CHARS - 1] + "…"
        return message


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def describe_error(exc: Exception) -> str:
    """A short, key-free description of a failure, safe to log."""
    if isinstance(exc, GeminiAPIError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "timed out"
    return str(exc)[:200]
