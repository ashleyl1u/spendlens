"""Tests for provider output validation, FakeProvider and LLM_PROVIDER selection."""

import inspect

import pytest

from app.categorization.providers import (
    INVALID_CONFIDENCE,
    FakeProvider,
    LLMProvider,
    Result,
    get_provider,
)


class ScriptedProvider(LLMProvider):
    """Returns whatever it is told to, standing in for a misbehaving model."""

    name = "scripted"

    def __init__(self, output):
        self.output = output

    def _categorize(self, merchants):
        return self.output


def test_fake_provider_is_deterministic():
    merchants = ["MAPLE STREET BOOKS CO", "GARDEN DUMPLING HO", "ZZZ UNKNOWN"]
    assert FakeProvider().categorize(merchants) == FakeProvider().categorize(merchants)
    assert FakeProvider().categorize(merchants) == [
        Result("Shopping", 0.8),
        Result("Dining", 0.85),
        Result("Other", 0.4),
    ]


def test_fake_provider_records_what_it_was_sent():
    provider = FakeProvider()
    provider.categorize(["A", "B"])
    provider.categorize([])  # nothing to ask, so no call
    assert provider.calls == [["A", "B"]]


def test_category_outside_the_list_becomes_low_confidence_other():
    provider = ScriptedProvider([Result("Pizza", 0.99), Result("dining", 0.9)])
    assert provider.categorize(["A", "B"]) == [Result("Other", INVALID_CONFIDENCE)] * 2


def test_malformed_results_become_low_confidence_other():
    provider = ScriptedProvider([None, {"category": "Dining"}, Result("Dining", "high")])
    assert provider.categorize(["A", "B", "C"]) == [Result("Other", INVALID_CONFIDENCE)] * 3


def test_confidence_is_clamped():
    provider = ScriptedProvider([Result("Dining", 7), Result("Dining", -1)])
    assert provider.categorize(["A", "B"]) == [Result("Dining", 1.0), Result("Dining", 0.0)]


def test_wrong_number_of_results_is_fixed_up():
    short = ScriptedProvider([Result("Dining", 0.9)])
    assert short.categorize(["A", "B"]) == [
        Result("Dining", 0.9),
        Result("Other", INVALID_CONFIDENCE),
    ]
    long = ScriptedProvider([Result("Dining", 0.9)] * 3)
    assert len(long.categorize(["A"])) == 1


def test_providers_only_receive_merchant_names():
    parameters = inspect.signature(LLMProvider.categorize).parameters
    assert list(parameters) == ["self", "merchants"]
    assert parameters["merchants"].annotation == list[str]


def test_llm_provider_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_provider(), FakeProvider)
    monkeypatch.setenv("LLM_PROVIDER", " Fake ")
    assert isinstance(get_provider(), FakeProvider)


def test_unknown_llm_provider_is_refused(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(RuntimeError, match="gemini"):
        get_provider()
