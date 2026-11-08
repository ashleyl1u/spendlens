"""Tests for provider output validation, FakeProvider and LLM_PROVIDER selection."""

import inspect

import pytest

from app.categorization.providers import (
    FALLBACK,
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


def test_fallback_is_low_confidence_other():
    assert (FALLBACK.category, FALLBACK.confidence) == ("Other", INVALID_CONFIDENCE)


def test_category_outside_the_list_becomes_low_confidence_other():
    provider = ScriptedProvider([Result("Pizza", 0.99), Result("dining", 0.9)])
    assert provider.categorize(["A", "B"]) == [FALLBACK] * 2


def test_malformed_results_become_low_confidence_other():
    provider = ScriptedProvider([None, {"category": "Dining"}, Result("Dining", "high")])
    assert provider.categorize(["A", "B", "C"]) == [FALLBACK] * 3


def test_confidence_is_clamped():
    provider = ScriptedProvider([Result("Dining", 7), Result("Dining", -1)])
    assert provider.categorize(["A", "B"]) == [Result("Dining", 1.0), Result("Dining", 0.0)]


def test_wrong_number_of_results_marks_the_whole_batch_for_review():
    # With a missing or extra answer we cannot tell which answer is whose.
    short = ScriptedProvider([Result("Dining", 0.9)])
    assert short.categorize(["A", "B"]) == [FALLBACK, FALLBACK]
    long = ScriptedProvider([Result("Dining", 0.9)] * 3)
    assert long.categorize(["A"]) == [FALLBACK]
    assert ScriptedProvider("not a list").categorize(["A"]) == [FALLBACK]


def test_fallbacks_are_not_cacheable_but_real_answers_are():
    provider = ScriptedProvider([Result("Pizza", 0.9), Result("Dining", 0.9)])
    invalid, valid = provider.categorize(["A", "B"])
    assert invalid.cacheable is False
    assert valid.cacheable is True


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
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="openai"):
        get_provider()
