"""Token and cost accounting. Expected costs are computed by hand."""
from __future__ import annotations

import importlib

import pytest

from src import usage


@pytest.fixture(autouse=True)
def _empty_record():
    usage.drain()
    yield
    usage.drain()


class _Usage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


def test_free_tier_models_cost_nothing():
    assert usage.cost_usd("google/gemma-4-31b-it:free", 10_000, 2_000) == 0.0


def test_priced_model_uses_input_and_output_rates():
    # gpt-4o-mini: 1,000,000 in at $0.15 + 500,000 out at $0.60 = 0.15 + 0.30
    assert usage.cost_usd("gpt-4o-mini", 1_000_000, 500_000) == pytest.approx(0.45)


def test_local_ollama_models_cost_nothing():
    assert usage.cost_usd("llama3.1-8b-ctx8k", 5_000, 500) == 0.0
    assert usage.cost_usd("qwen2.5-7b-ctx8k", 5_000, 500) == 0.0


def test_unlisted_model_is_unpriced_not_zero():
    assert usage.cost_usd("some-new-model", 100, 100) is None


def test_record_then_drain_empties_the_record():
    usage.record("classification", "gpt-4o-mini", _Usage(100, 20))
    calls = usage.drain()
    assert calls == [{"stage": "classification", "model": "gpt-4o-mini", "cached": False,
                      "prompt_tokens": 100, "completion_tokens": 20,
                      "cost_usd": pytest.approx((100 * 0.15 + 20 * 0.60) / 1e6),
                      "cost_saved_usd": 0.0}]
    assert usage.drain() == []


def test_missing_usage_is_visible_not_zero():
    usage.record("guardrail", "gpt-4o-mini", None)
    s = usage.summarise(usage.drain())
    assert s["calls"] == 1 and s["calls_without_usage"] == 1
    assert s["prompt_tokens"] == 0 and s["cost_usd"] == 0


def test_summarise_totals_by_stage_and_counts_unpriced_calls():
    usage.record("classification", "x:free", _Usage(100, 10))
    usage.record("guardrail", "x:free", _Usage(300, 30))
    usage.record("guardrail", "unlisted", _Usage(50, 5))
    s = usage.summarise(usage.drain())
    assert s["calls"] == 3
    assert s["prompt_tokens"] == 450 and s["completion_tokens"] == 45
    assert s["cost_usd"] == 0.0 and s["unpriced_calls"] == 1
    assert s["by_stage"]["guardrail"] == {"calls": 2, "cached_calls": 0,
                                          "prompt_tokens": 350, "completion_tokens": 35}


def test_cached_calls_are_counted_apart_and_never_billed():
    """A replayed reply is logged, but its tokens are replayed, not spent."""
    usage.record("generation", "gpt-4o-mini", _Usage(1_000_000, 0))
    replayed = {"prompt_tokens": 2_000_000, "completion_tokens": 500_000}
    unknown = {"prompt_tokens": None, "completion_tokens": None}
    usage.record("generation", "gpt-4o-mini", replayed, cached=True)
    usage.record("guardrail", "gpt-4o-mini", unknown, cached=True)
    s = usage.summarise(usage.drain())
    assert (s["calls"], s["live_calls"], s["cached_calls"]) == (3, 1, 2)
    assert s["prompt_tokens"] == 1_000_000 and s["cost_usd"] == pytest.approx(0.15)
    assert s["cached_prompt_tokens"] == 2_000_000
    assert s["cached_completion_tokens"] == 500_000
    assert s["cost_saved_usd"] == pytest.approx(0.30 + 0.30)
    assert s["cached_calls_without_counts"] == 1
    assert s["by_stage"]["generation"] == {"calls": 2, "cached_calls": 1,
                                           "prompt_tokens": 1_000_000, "completion_tokens": 0}


def _client_with_usage(prompt, completion):
    class _Message:
        content = '{"ok": true}'

    class _Choice:
        message = _Message()
        finish_reason = "stop"

    class _Completion:
        choices = [_Choice()]
        usage = _Usage(prompt, completion)

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        class chat:  # noqa: N801 - mirrors the SDK shape
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _Completion()

    return _FakeClient


@pytest.mark.parametrize("module, stage", [
    ("src.classify", "classification"),
    ("src.generate", "generation"),
    ("src.guardrails", "guardrail"),
])
def test_every_call_site_records_the_providers_token_counts(module, stage, monkeypatch):
    import openai

    mod = importlib.import_module(module)
    monkeypatch.setattr(openai, "OpenAI", _client_with_usage(1200, 80))
    monkeypatch.setattr(mod, "require_key", lambda: "k", raising=False)
    monkeypatch.setattr(mod, "GUARDRAIL_API_KEY", "k", raising=False)

    mod._openrouter_call("system", "user", 0)

    calls = usage.drain()
    assert len(calls) == 1
    assert calls[0]["stage"] == stage
    assert (calls[0]["prompt_tokens"], calls[0]["completion_tokens"]) == (1200, 80)
