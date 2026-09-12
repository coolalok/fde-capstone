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
    import os

    from src.config import GUARDRAIL_MODEL, MODEL_NAME

    if os.environ.get("GUARDRAIL_MODEL"):
        pytest.skip(
            "GUARDRAIL_MODEL overridden locally. This test guards the COMMITTED "
            "defaults, which is what the assessor runs. If your override makes "
            "judge == generator, the model is grading its own output and any "
            "guardrail pass-rate from that run is confounded by self-preference "
            "bias — capstone-prompt-writer forbids it for judges."
        )
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


# ─── malformed provider envelope (VAL-0011, 2026-09-09) ──────────────
#
# OpenRouter answered 200 with choices=None. Subscripting it raised
# "TypeError: 'NoneType' object is not subscriptable" from inside the caller's
# broad except, so the guardrail recorded the symptom instead of the cause.
# Fail-safe still blocked the ticket (A7 held) — the defect was diagnostic, and
# it is the class of thing that only shows up under provider load.


def _client_returning(choices):
    class _Completion:
        pass

    completion = _Completion()
    completion.choices = choices

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        class chat:  # noqa: N801 - mirrors the SDK shape
            class completions:
                @staticmethod
                def create(**kwargs):
                    return completion

    return _FakeClient


@pytest.mark.parametrize("module", CALL_SITES)
def test_null_choices_raises_its_true_cause(module, monkeypatch):
    import importlib

    import openai

    mod = importlib.import_module(module)
    monkeypatch.setattr(openai, "OpenAI", _client_returning(None))
    monkeypatch.setattr(mod, "require_key", lambda: "k", raising=False)

    with pytest.raises(ValueError, match="no choices"):
        mod._openrouter_call("system", "user", 0)


@pytest.mark.parametrize("module", CALL_SITES)
def test_empty_choices_list_also_raises_the_cause(module, monkeypatch):
    """[] is the other malformed shape; it raised IndexError before."""
    import importlib

    import openai

    mod = importlib.import_module(module)
    monkeypatch.setattr(openai, "OpenAI", _client_returning([]))
    monkeypatch.setattr(mod, "require_key", lambda: "k", raising=False)

    with pytest.raises(ValueError, match="no choices"):
        mod._openrouter_call("system", "user", 0)


def test_malformed_envelope_is_counted_as_its_own_failure_type(db, monkeypatch):
    """The point of raising the cause: MODEL_CALL_FAILURES must separate a
    malformed envelope from a rate limit. Yesterday's gate run was only
    interpretable because those were distinguishable."""
    import openai

    import src.classify as c
    from src.schema import Ticket

    before = _failure_count("classification", "ValueError")
    monkeypatch.setattr(openai, "OpenAI", _client_returning(None))
    monkeypatch.setattr(c, "require_key", lambda: "k", raising=False)

    result = c.classify(Ticket(ticket_id="ENV-1", channel="email", subject="s", body="b"))
    assert result.intent == "unknown"
    assert "no choices" in (result.error or "")
    assert _failure_count("classification", "ValueError") == before + 1


# ─── provider seam defaults (cost-nothing rule / D-01) ───────────────


def test_provider_defaults_stay_on_the_free_tier():
    """The assessor runs this on their own machine with their own free-tier
    key. capstone-conventions' cost-nothing rule and D-01 both require the
    committed defaults to point at OpenRouter. The seam exists only so a paid
    endpoint can be pointed at for DIAGNOSIS, via .env, which is gitignored."""
    import os

    from src.config import MODEL_BASE_URL

    if os.environ.get("MODEL_BASE_URL"):
        pytest.skip("MODEL_BASE_URL overridden in this environment")
    assert MODEL_BASE_URL == "https://openrouter.ai/api/v1"


def test_model_api_key_falls_back_to_the_openrouter_key():
    """Existing .env files set only OPENROUTER_API_KEY; they must keep working."""
    import os

    from src.config import MODEL_API_KEY, OPENROUTER_API_KEY

    if os.environ.get("MODEL_API_KEY"):
        pytest.skip("MODEL_API_KEY set explicitly in this environment")
    assert MODEL_API_KEY == OPENROUTER_API_KEY


@pytest.mark.parametrize("module", CALL_SITES)
def test_call_sites_read_the_configured_endpoint(module, monkeypatch):
    """Catches a future edit that re-hardcodes the OpenRouter URL."""
    import importlib

    import openai

    mod = importlib.import_module(module)
    captured: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop after construction")

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    # The judge reads its OWN endpoint and key, so it can sit on a different
    # provider from the generator — independence (D-07/Bug 5) can require a
    # different provider, not just a different model name. Everything else
    # reads the generator's.
    if module == "src.guardrails":
        prefix = "GUARDRAIL"
    else:
        prefix = "MODEL"
        monkeypatch.setattr(mod, "require_key", lambda: "test-key", raising=False)
    monkeypatch.setattr(mod, f"{prefix}_BASE_URL", "https://example.test/v1",
                        raising=False)
    monkeypatch.setattr(mod, f"{prefix}_API_KEY", "test-key", raising=False)

    with pytest.raises(RuntimeError):
        mod._openrouter_call("system", "user", 0)
    assert captured.get("base_url") == "https://example.test/v1"
    assert captured.get("api_key") == "test-key"


def test_judge_endpoint_defaults_to_the_generators():
    """An unset GUARDRAIL_BASE_URL/KEY must behave exactly as before the split,
    so existing .env files keep working untouched.
    """
    import os

    from src.config import (
        GUARDRAIL_API_KEY,
        GUARDRAIL_BASE_URL,
        MODEL_API_KEY,
        MODEL_BASE_URL,
    )

    if os.environ.get("GUARDRAIL_BASE_URL") or os.environ.get("GUARDRAIL_API_KEY"):
        pytest.skip("judge endpoint overridden in this environment")
    assert GUARDRAIL_BASE_URL == MODEL_BASE_URL
    assert GUARDRAIL_API_KEY == MODEL_API_KEY


def test_guardrails_refuses_to_run_without_a_judge_key(monkeypatch):
    """require_key() checks the GENERATOR's key. Since the judge can now be on
    another provider, that check can pass while the judge has no credentials —
    every guardrail would then fail safe and block the run without the log
    naming why.
    """
    import src.guardrails as g

    monkeypatch.setattr(g, "GUARDRAIL_API_KEY", "", raising=False)
    with pytest.raises(RuntimeError, match="No judge key set"):
        g._openrouter_call("system", "user", 0)
