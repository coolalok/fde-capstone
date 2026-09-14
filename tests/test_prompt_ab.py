"""Tests for the prompt A/B harness: the diagnostics, the statistics and the
pre-registered decision rule. No model calls.
"""
from __future__ import annotations

import pytest

from evaluation.prompt_ab import (
    ALL_DIAGNOSTICS,
    decide,
    diagnostics,
    generation_prompt,
    paired_bootstrap,
    score_variant,
    summarise,
)
from src.schema import GeneratedResponse, GuardrailResult, Route


# ─── diagnostics ─────────────────────────────────────────────────────


@pytest.mark.parametrize("name, text", [
    ("first_person_promise", "I will take a closer look at your account directly."),
    ("first_person_promise", "I can start that request for you."),
    ("first_person_promise", "I'm happy to look further if this does not help."),
    ("first_person_promise", "Your refund request will be handled by the billing team."),
    ("followup_timeline", "The relevant team will get back to you within 2 business days."),
    ("followup_timeline", "We will follow up by tomorrow with an update in a few days."),
    ("internal_action", "We're still investigating the issue with your logs."),
    ("internal_action", "Our team has escalated this."),
    ("unsourced_hedge", "The usual cause is a stale session cookie."),
    ("unsourced_hedge", "In most cases this resolves itself."),
])
def test_diagnostics_fire(name, text):
    assert diagnostics(text)[name], (name, text)


@pytest.mark.parametrize("text", [
    # Documented product timings are facts, not follow-up promises.
    "Traffic moves within roughly thirty seconds and no rebuild takes place.",
    "A locked account unlocks automatically after thirty minutes.",
    "Download links are valid for twenty-four hours.",
    # The safe close recommended in the review.
    "If this does not resolve it, reply with what you observed at each step.",
    # Hedges that the articles themselves use.
    "The most common cause is device clock drift of more than thirty seconds.",
])
def test_diagnostics_stay_quiet_on_legitimate_text(text):
    assert not any(diagnostics(text).values()), (text, diagnostics(text))


# ─── statistics ──────────────────────────────────────────────────────


def test_paired_bootstrap_is_deterministic_and_brackets_the_mean():
    diffs = [0.1, -0.05, 0.2, 0.0, 0.15, -0.1, 0.05]
    a, b = paired_bootstrap(diffs), paired_bootstrap(diffs)
    assert a == b
    assert a["ci_low"] <= a["mean"] <= a["ci_high"]


def test_paired_bootstrap_of_no_difference_is_zero():
    got = paired_bootstrap([0.0] * 10)
    assert (got["mean"], got["ci_low"], got["ci_high"]) == (0.0, 0.0, 0.0)


def test_paired_bootstrap_empty():
    assert paired_bootstrap([])["mean"] is None


# ─── per-draft scoring ───────────────────────────────────────────────


class _Sim:
    def score(self, answer, reference):
        return 0.8


TRUTH = {
    "must_mention": ["cursor", "page size"],
    "must_not_claim": ["a refund has been issued"],
    "reference_response": "Thanks for the question. Cursor pagination avoids this. " * 3,
}


def _route(decision="auto_respond"):
    return Route(decision=decision, reason="r", trigger="t")


def test_score_variant_answered_ticket():
    resp = GeneratedResponse(answer="Use the cursor and keep page size low.[DOC-API-002]",
                             citations=["DOC-API-002"], confidence=0.9, unknown=False)
    row = score_variant(resp, [], _route(), TRUTH, _Sim())
    assert row["mentions_present"] == 2 and row["coverage"] == 1.0
    assert row["violations"] == []
    assert row["correctness"] == pytest.approx(0.75 * 1.0 + 0.25 * 0.8)


def test_score_variant_abstention_on_answerable_ticket_scores_zero():
    """Declining an answerable ticket must not be a free pass on quality."""
    resp = GeneratedResponse(answer="", citations=[], confidence=0.0, unknown=True)
    row = score_variant(resp, [], _route("escalate"), TRUTH, _Sim())
    assert row["correctness"] == 0.0
    assert row["coverage"] == 0.0


def test_score_variant_excludes_prompt_insensitive_and_fail_safe_blocks():
    resp = GeneratedResponse(answer="Use the cursor.", citations=["DOC-API-002"],
                             confidence=0.9, unknown=False)
    results = [
        GuardrailResult(name="confidence_floor", passed=False, reason="low"),
        GuardrailResult(name="grounding", passed=False, reason="judge down", fail_safe=True),
        GuardrailResult(name="answer_relevance", passed=False, reason="off topic"),
    ]
    row = score_variant(resp, results, _route("block"), None, None)
    assert row["prompt_sensitive_blocks"] == ["answer_relevance"]
    assert row["fail_safe_blocks"] == ["grounding"]


# ─── the decision rule ───────────────────────────────────────────────


def _side(**over):
    base = {"generator_errors": 0, "unknown": 5, "auto_respond": 10,
            "prompt_sensitive_block_tickets": 10, "fail_safe_block_tickets": 0,
            "diagnostics": {k: 0 for k in ALL_DIAGNOSTICS},
            "prohibited_claim_tickets": 0, "must_mention_coverage": 0.5,
            "mean_correctness": 0.6, "mean_similarity": 0.7}
    base.update(over)
    return base


def _summaries(held_c=None, unans_c=None, corr=(0.03, -0.01, 0.07), cov=(0.05, 0.0, 0.1)):
    held = {"n": 100, "baseline": _side(), "candidate": _side(**(held_c or {})),
            "correctness_diff": {"n": 60, "mean": corr[0], "ci_low": corr[1], "ci_high": corr[2]},
            "coverage_diff": {"n": 31, "mean": cov[0], "ci_low": cov[1], "ci_high": cov[2]}}
    unans_candidate = _side(**({"unknown": 60} | (unans_c or {})))
    unans = {"n": 143, "baseline": _side(unknown=60), "candidate": unans_candidate}
    return held, unans


def test_decide_adopts_a_clean_improvement():
    assert decide(*_summaries())["adopt_candidate"] is True


def test_decide_rejects_any_new_prohibited_claim():
    v = decide(*_summaries(held_c={"prohibited_claim_tickets": 1}))
    assert v["adopt_candidate"] is False


def test_decide_rejects_more_unanswerable_tickets_auto_sent():
    v = decide(*_summaries(unans_c={"auto_respond": 11}))
    assert v["adopt_candidate"] is False


def test_decide_rejects_a_drop_in_abstention_on_unanswerable():
    v = decide(*_summaries(unans_c={"unknown": 52}))   # 60/143 -> 52/143 is -0.056
    assert v["adopt_candidate"] is False


def test_decide_rejects_a_meaningful_correctness_drop():
    v = decide(*_summaries(corr=(0.01, -0.05, 0.06)))
    assert v["adopt_candidate"] is False


def test_decide_keeps_baseline_without_a_measured_gain():
    v = decide(*_summaries(corr=(0.0, -0.01, 0.01), cov=(0.0, -0.01, 0.01)))
    assert v["adopt_candidate"] is False


def test_decide_tolerates_one_extra_diagnostic_hit_but_not_two():
    one = {"diagnostics": {k: (1 if k == "internal_action" else 0) for k in ALL_DIAGNOSTICS}}
    two = {"diagnostics": {k: (2 if k == "internal_action" else 0) for k in ALL_DIAGNOSTICS}}
    assert decide(*_summaries(held_c=one))["adopt_candidate"] is True
    assert decide(*_summaries(held_c=two))["adopt_candidate"] is False


def test_summarise_pairs_only_error_free_tickets():
    ok = {"error": None, "unknown": False, "decision": "auto_respond",
          "prompt_sensitive_blocks": [], "fail_safe_blocks": [],
          "diagnostics": {k: False for k in ALL_DIAGNOSTICS},
          "violations": [], "mentions_required": 1, "mentions_present": 1,
          "coverage": 1.0, "similarity": 0.8, "correctness": 0.9}
    bad = ok | {"error": "APIConnectionError", "correctness": 0.0, "coverage": 0.0}
    rows = [{"baseline": ok, "candidate": ok}, {"baseline": ok, "candidate": bad}]
    s = summarise(rows)
    assert s["paired_n"] == 1
    assert s["correctness_diff"]["n"] == 1
    assert s["candidate"]["generator_errors"] == 1


def test_generation_prompt_restores_the_module_even_on_error():
    import src.generate as gen
    before = (gen._PROMPT_01, gen._PROMPT_01_VERSION)
    with pytest.raises(RuntimeError):
        with generation_prompt(before[0]):
            raise RuntimeError("boom")
    assert (gen._PROMPT_01, gen._PROMPT_01_VERSION) == before


# ─── amendment: doc_id used inside a sentence (raw draft) ────────────


@pytest.mark.parametrize("raw", [
    "To roll back, you can follow the steps in [DOC-DEPLOY-002].",   # v3.0, DEV-0009
    "See [DOC-AUTH-001] for details.",
    "As described in [DOC-API-003], compute the signature first.",
])
def test_marker_as_reference_fires_on_the_raw_draft(raw):
    assert diagnostics("", raw)["marker_as_reference"], raw


@pytest.mark.parametrize("raw", [
    "Revoke the old key once traffic has moved.[DOC-AUTH-004]",
    "The account unlocks after thirty minutes [DOC-AUTH-001]. Clear cookies next [DOC-AUTH-001].",
])
def test_marker_as_reference_ignores_a_trailing_marker(raw):
    assert not diagnostics("", raw)["marker_as_reference"], raw


def test_decide_counts_the_raw_diagnostic():
    two = {"diagnostics": {k: (2 if k == "marker_as_reference" else 0) for k in ALL_DIAGNOSTICS}}
    assert decide(*_summaries(held_c=two))["adopt_candidate"] is False


# ─── amendment 4: infrastructure failures (laptop sleep) ─────────────


@pytest.mark.parametrize("msg, infra", [
    ("APIConnectionError: Connection error.", True),
    ("guardrail_error: InternalServerError: 500", True),
    ("RateLimitError: 429", True),
    ("APITimeoutError: Request timed out.", False),   # a longer prompt can cause it
    ("ValueError: model output cut off at the provider's length limit", False),
    ("JSONDecodeError: Unterminated string", False),
    (None, False),
])
def test_infrastructure_error_classification(msg, infra):
    from evaluation.prompt_ab import is_infrastructure_error
    assert is_infrastructure_error(msg) is infra


def test_score_variant_flags_a_connection_failure_in_a_guardrail():
    resp = GeneratedResponse(answer="Use the cursor.", citations=["DOC-API-002"],
                             confidence=0.9, unknown=False)
    results = [GuardrailResult(name="grounding", passed=False, fail_safe=True,
                               reason="grounding_guardrail_error: APIConnectionError: x")]
    assert score_variant(resp, results, _route("block"), None, None)["infra_error"] is True


def test_summarise_excludes_infrastructure_failures_from_both_arms():
    ok = {"error": None, "unknown": False, "decision": "auto_respond",
          "prompt_sensitive_blocks": [], "fail_safe_blocks": [], "infra_error": False,
          "diagnostics": {k: False for k in ALL_DIAGNOSTICS}}
    broken = ok | {"error": "APIConnectionError: x", "unknown": True,
                   "decision": "escalate", "infra_error": True}
    rows = [{"baseline": ok, "candidate": ok, "infra_failure": False},
            {"baseline": broken, "candidate": ok, "infra_failure": True}]
    s = summarise(rows)
    assert (s["n"], s["n_attempted"], s["infra_failure_tickets"]) == (1, 2, 1)
    assert s["baseline"]["generator_errors"] == 0   # the failed ticket is not counted


def test_decide_is_inconclusive_when_infrastructure_failures_exceed_the_limit():
    held, unans = _summaries()
    held = held | {"n_attempted": 100, "infra_failure_tickets": 6}
    v = decide(held, unans)
    assert v["adopt_candidate"] is False and v["inconclusive"] is True


def test_decide_accepts_a_small_infrastructure_failure_share():
    held, unans = _summaries()
    held = held | {"n_attempted": 100, "infra_failure_tickets": 5}
    v = decide(held, unans)
    assert v["inconclusive"] is False and v["adopt_candidate"] is True
