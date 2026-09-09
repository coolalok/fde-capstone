"""Every model call must be time-bounded. A9 / A11.

Regression for 2026-09-04: no OpenAI client set a timeout, so all three call
sites inherited the SDK default of a 600s read timeout with 2 retries — one
unresponsive call could occupy ~30 minutes. A validation sweep hung for two
hours at ticket 40 of 80. A9 promises the evaluation set is processed
unattended in one command; an unbounded call makes that promise unkeepable.

This went unnoticed because every other test stubs the model, so nothing
exercised a slow or unresponsive call.
"""
from __future__ import annotations

import pytest

from src.config import MODEL_MAX_RETRIES, MODEL_TIMEOUT_SECONDS


CALL_SITES = ["src.classify", "src.generate", "src.guardrails"]


def test_timeout_is_configured_and_sane():
    assert 0 < MODEL_TIMEOUT_SECONDS <= 120, (
        "a healthy call runs ~2s; a bound above 120s defeats the purpose"
    )
    assert 0 <= MODEL_MAX_RETRIES <= 3


@pytest.mark.parametrize("module", CALL_SITES)
def test_every_client_is_bounded(module, monkeypatch):
    """Construct each module's real client with a fake OpenAI and assert the
    bound is passed. Catches a new call site added without a timeout."""
    import importlib

    mod = importlib.import_module(module)
    captured: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop after construction")

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(mod, "OPENROUTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(mod, "require_key", lambda: "test-key", raising=False)

    with pytest.raises(RuntimeError):
        mod._openrouter_call("system", "user", 0)

    assert captured.get("timeout") == MODEL_TIMEOUT_SECONDS, (
        f"{module}._openrouter_call built an OpenAI client without a timeout"
    )
    assert captured.get("max_retries") == MODEL_MAX_RETRIES


def test_a_timing_out_call_still_degrades_gracefully(db):
    """A11: the bound makes the failure *arrive*; the fallback still handles it."""
    import httpx

    from src.classify import classify
    from src.schema import Ticket

    def _times_out(system, user, seed):
        raise httpx.ReadTimeout("request timed out")

    result = classify(
        Ticket(ticket_id="T-TIMEOUT", channel="email", subject="s", body="b"),
        call_model=_times_out,
    )
    assert result.intent == "unknown"
    assert result.confidence == 0.0
    assert "ReadTimeout" in (result.error or "")


# ─── observability of model-call failures ────────────────────────────
#
# Added 2026-09-06. A rate-limited run and a healthy-but-poor run produce the
# same SHAPE of output — everything degrades to unknown — so without a counted
# failure signal an unattended run cannot tell you it was rate-limited. Same
# trap as the unpinned httpx: silent degradation that reads as poor quality.


def _failure_count(stage: str, error_type: str) -> float:
    from src.metrics import MODEL_CALL_FAILURES

    for metric in MODEL_CALL_FAILURES.collect():
        for s in metric.samples:
            if (
                s.name.endswith("_total")
                and s.labels.get("stage") == stage
                and s.labels.get("error_type") == error_type
            ):
                return s.value
    return 0.0


def test_classifier_failure_is_counted_by_stage_and_type(db):
    from src.classify import classify
    from src.schema import Ticket

    class RateLimitError(Exception):
        pass

    before = _failure_count("classification", "RateLimitError")
    classify(
        Ticket(ticket_id="M-1", channel="email", subject="s", body="b"),
        call_model=lambda s, u, seed: (_ for _ in ()).throw(RateLimitError("429")),
    )
    assert _failure_count("classification", "RateLimitError") == before + 1


def test_generator_failure_is_counted(db):
    from src.generate import generate
    from src.schema import Passage, Ticket

    class APIError(Exception):
        pass

    before = _failure_count("generation", "APIError")
    generate(
        Ticket(ticket_id="M-2", channel="email", subject="s", body="b"),
        [Passage(doc_id="DOC-A", score=0.5, text="x", title="t", category="c")],
        ticket_id="M-2",
        call_model=lambda s, u, seed: (_ for _ in ()).throw(APIError("boom")),
    )
    assert _failure_count("generation", "APIError") == before + 1


def test_unparseable_response_text_is_kept_for_diagnosis(db, caplog):
    """A model that starts emitting prose instead of JSON must be
    distinguishable from a network fault. Before this, the text was lost and
    both looked like 'the call failed'."""
    import logging

    from src.classify import classify
    from src.schema import Ticket

    prose = "I think the answer is authentication_failure, hope that helps!"
    with caplog.at_level(logging.WARNING, logger="src.classify"):
        classify(
            Ticket(ticket_id="M-3", channel="email", subject="s", body="b"),
            call_model=lambda s, u, seed: prose,
        )
    heads = [getattr(r, "raw_response_head", None) for r in caplog.records]
    assert prose in heads, "the unparseable response text was not logged"


def test_no_raw_text_logged_when_the_call_never_returned(db, caplog):
    """A network failure has no response to keep — the field must be None, not
    a stale value from a previous ticket."""
    import logging

    from src.classify import classify
    from src.schema import Ticket

    with caplog.at_level(logging.WARNING, logger="src.classify"):
        classify(
            Ticket(ticket_id="M-4", channel="email", subject="s", body="b"),
            call_model=lambda s, u, seed: (_ for _ in ()).throw(ConnectionError("down")),
        )
    heads = [getattr(r, "raw_response_head", "MISSING") for r in caplog.records]
    assert heads and all(h is None for h in heads)


# ─── the guardrail judge is a separate model (Bug 5) ─────────────────


def test_guardrail_judge_is_not_the_generator_model():
    """The 8B generator cannot verify its own claims: it blocked 71 of 71 drafts
    on the validation set, rejecting text byte-for-byte present in the cited
    passage. Prompt recalibration did not move it, so the judge must be a
    different, stronger model. capstone-prompt-writer sets the same rule for
    evaluation judges (self-preference bias)."""
    from src.config import GUARDRAIL_MODEL, MODEL_NAME

    assert GUARDRAIL_MODEL, "guardrails need an explicit judge model"
    assert GUARDRAIL_MODEL != MODEL_NAME
    assert GUARDRAIL_MODEL.split("/")[0] != MODEL_NAME.split("/")[0], (
        "judge and generator must not share a model family"
    )


def test_guardrail_call_site_uses_the_judge_model(monkeypatch):
    """Catches a future edit that quietly reverts the guardrails to MODEL_NAME."""
    import openai

    import src.guardrails as g
    from src.config import GUARDRAIL_MODEL

    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        class chat:  # noqa: N801 - mirrors the SDK's shape
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    raise RuntimeError("stop after capture")

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    monkeypatch.setattr(g, "require_key", lambda: "k", raising=False)
    with pytest.raises(RuntimeError):
        g._openrouter_call("system", "user", 0)
    assert captured.get("model") == GUARDRAIL_MODEL


def test_empty_provider_content_raises_its_true_cause(monkeypatch):
    """A 200 with null content used to become "" and then fail JSON parsing as
    'Expecting value' — a misleading error for a provider returning nothing."""
    import openai

    import src.guardrails as g

    class _Msg:
        content = None

    class _Choice:
        message = _Msg()

    class _Completion:
        choices = [_Choice()]

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        class chat:  # noqa: N801
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _Completion()

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    monkeypatch.setattr(g, "require_key", lambda: "k", raising=False)
    with pytest.raises(ValueError, match="empty content"):
        g._openrouter_call("system", "user", 0)
