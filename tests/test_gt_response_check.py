"""Tests for the ground-truth response evaluation.

Every field in data/ground_truth_responses.json must be honoured and honoured
CORRECTLY — a metric that is computed wrongly is worse than one not computed,
because it gets quoted.
"""
from __future__ import annotations

import json

import pytest

from evaluation.gt_response_check import (
    CLAIM_DETECTORS,
    mentions,
    _W_FACTUAL,
    _W_SIMILARITY,
    answer_correctness,
    check_answer,
    context_recall,
    is_boilerplate_reference,
    _mean,
)


# ─── expected_doc_ids -> context recall ──────────────────────────────


@pytest.mark.parametrize("retrieved, expected, want", [
    (["DOC-A-001", "DOC-B-002"], ["DOC-A-001"], 1.0),
    (["DOC-B-002"], ["DOC-A-001"], 0.0),
    (["DOC-A-001"], ["DOC-A-001", "DOC-B-002"], 0.5),
    # Duplicate chunks of one article must not inflate recall.
    (["DOC-A-001", "DOC-A-001"], ["DOC-A-001", "DOC-B-002"], 0.5),
])
def test_context_recall(retrieved, expected, want):
    assert context_recall(retrieved, expected) == want


def test_context_recall_is_none_when_nothing_is_expected():
    """Not zero. Scoring an unscoreable ticket 0 would understate retrieval."""
    assert context_recall(["DOC-A-001"], []) is None


def test_mean_excludes_none_rather_than_counting_it_as_zero():
    assert _mean([1.0, None, 0.0]) == 0.5
    assert _mean([None, None]) is None


# ─── reference_response -> boilerplate detection ─────────────────────


def test_boilerplate_reference_is_recognised():
    """79 of 200 references are this content-free holding reply. Scoring
    similarity against it measures politeness, not correctness.
    """
    gt = json.load(open("data/ground_truth_responses.json"))
    flagged = [g for g in gt if is_boilerplate_reference(g["reference_response"])]
    assert len(flagged) == 79, f"expected 79 boilerplate references, got {len(flagged)}"
    # And every one of them asserts no facts — consistent with carrying none.
    assert all(not g["must_mention"] for g in flagged)


def test_specific_references_are_not_flagged():
    gt = json.load(open("data/ground_truth_responses.json"))
    specific = [g for g in gt if not is_boilerplate_reference(g["reference_response"])]
    assert len(specific) == 121
    assert all(len(g["reference_response"]) > 200 for g in specific)


# ─── RAGAS answer correctness ────────────────────────────────────────


def test_answer_correctness_perfect_case():
    """All facts present, nothing prohibited, identical to reference."""
    assert answer_correctness(4, 0, 0, 1.0) == 1.0


def test_answer_correctness_penalises_a_prohibited_claim():
    """A false positive must cost, even with every required fact present."""
    clean = answer_correctness(4, 0, 0, 0.8)
    violating = answer_correctness(4, 0, 1, 0.8)
    assert violating < clean


def test_answer_correctness_penalises_a_missing_fact():
    complete = answer_correctness(4, 0, 0, 0.8)
    incomplete = answer_correctness(3, 1, 0, 0.8)
    assert incomplete < complete


def test_answer_correctness_uses_the_ragas_f1_formula():
    """F1 = TP / (TP + 0.5*(FP+FN)). With TP=2, FP=1, FN=1 that is 2/3."""
    got = answer_correctness(2, 1, 1, 0.0)
    assert got == pytest.approx(_W_FACTUAL * (2 / 3), abs=1e-4)


def test_answer_correctness_weights_match_ragas_defaults():
    assert (_W_FACTUAL, _W_SIMILARITY) == (0.75, 0.25)
    assert _W_FACTUAL + _W_SIMILARITY == 1.0


def test_answer_correctness_falls_back_to_similarity_with_nothing_to_check():
    """A ticket asserting no facts either way must not be scored 0.75-down for
    having nothing to check.
    """
    assert answer_correctness(0, 0, 0, 0.6) == 0.6


def test_answer_correctness_without_a_reference_uses_factual_only():
    assert answer_correctness(2, 0, 0, None) == 1.0


# ─── must_mention / must_not_claim still work ────────────────────────


def test_check_answer_counts_missing_facts_and_violations():
    out = check_answer(
        answer="We have issued a refund. The cursor marks your position.",
        must_not_claim=["a refund has been issued"],
        must_mention=["cursor", "page size"],
    )
    assert [v["claim"] for v in out["violations"]] == ["a refund has been issued"]
    assert out["must_mention_missing"] == ["page size"]
    assert out["must_mention_total"] == 2


# ─── the refund prohibition needs PAST tense too (2026-09-13) ────────
# _RE_REFUND (tone/scope) targets future COMMITMENTS, because that is the
# liability risk it exists to stop. The ground truth prohibits asserting a
# refund ALREADY happened — and _RE_REFUND does not match the ground truth's
# own wording, so reusing it alone left this prohibition unchecked.


@pytest.mark.parametrize("text", [
    "a refund has been issued",          # the ground truth's literal wording
    "We have issued a refund.",
    "your refund has been processed",
    "you have been refunded",
    "I have applied a credit",
    "your refund was approved",
    "we will refund you",                # the future case must still fire
])
def test_refund_prohibition_detects_past_and_future(text):
    assert CLAIM_DETECTORS["a refund has been issued"].search(text), text


@pytest.mark.parametrize("text", [
    "no refund is available under the policy",
    "refunds are handled by the billing team",
    "you can request a refund from the billing page",
    "refund policy details are on the billing page",
])
def test_refund_prohibition_does_not_fire_on_describing_policy(text):
    """Explaining how refunds work is not claiming one was issued. This is the
    guard that stops the fix widening into flagging every mention of the word.
    """
    assert not CLAIM_DETECTORS["a refund has been issued"].search(text), text


def test_every_ground_truth_prohibition_has_a_detector():
    """A prohibition with no detector is silently unchecked, and the report
    would show zero violations for it however the generator behaved.
    """
    gt = json.load(open("data/ground_truth_responses.json"))
    prohibitions = {c for g in gt for c in g["must_not_claim"]}
    undetected = prohibitions - set(CLAIM_DETECTORS)
    assert not undetected, f"no detector for: {undetected}"


# ─── must_mention matching (2026-09-14) ──────────────────────────────
# Substring matching failed correct replies ("raw request body" vs "raw body")
# and passed irrelevant ones ("port" inside "support").


@pytest.mark.parametrize("answer, phrase", [
    ("Compute the signature over the raw request body.", "raw body"),   # DOC-API-003 wording
    ("Your account is locked after five attempts.", "account lock"),
    ("The account remains locked until an admin releases it.", "account lock"),
    ("Pass the next cursors in order.", "cursor"),
    ("Retry with exponential back-off.", "backoff"),
    ("Limits apply per-organisation.", "per organisation"),
    ("Keep page size at or below two hundred.", "page size"),
    ("Make the handler Idempotent.", "idempotent"),
    ("Expose the port the application listens on.", "port"),
])
def test_mentions_accepts_real_wording(answer, phrase):
    assert mentions(answer, phrase), (answer, phrase)


@pytest.mark.parametrize("answer, phrase", [
    ("Please contact support if this continues.", "port"),    # substring, not the word
    ("Open the portal and check again.", "port"),             # not an inflection
    ("The raw data sent in the request message body.", "raw body"),  # too far apart
    ("Open the next page. Size limits also apply.", "page size"),    # across a sentence
    ("Lock the account first.", "account lock"),              # wrong order
    ("", "cursor"),
])
def test_mentions_rejects_near_misses(answer, phrase):
    assert not mentions(answer, phrase), (answer, phrase)


def test_check_answer_credits_article_wording_for_a_required_fact():
    out = check_answer(
        answer="Compute the signature over the raw request body before parsing.",
        must_not_claim=[], must_mention=["raw body"],
    )
    assert out["must_mention_missing"] == []


def test_every_must_mention_term_is_reachable_from_the_help_articles():
    """A required fact the articles cannot supply can never be scored by a
    grounded reply, so it would silently depress coverage.
    """
    gt = json.load(open("data/ground_truth_responses.json"))
    articles = " ".join(d["content"] for d in json.load(open("data/documentation.json")))
    terms = {t for g in gt for t in g["must_mention"]}
    unreachable = sorted(t for t in terms if not mentions(articles, t))
    assert not unreachable, f"no article wording satisfies: {unreachable}"


# ─── "fixed on our side" matches a FIX, not activity (2026-09-14) ────


@pytest.mark.parametrize("text", [
    "We have fixed the issue.",
    "This has been resolved.",
    "Our team has deployed a fix.",
    "The issue is now corrected.",
])
def test_fixed_on_our_side_detects_fix_claims(text):
    assert CLAIM_DETECTORS["the issue has been fixed on our side"].search(text), text


@pytest.mark.parametrize("text", [
    "We have reviewed your request.",
    "We are investigating this.",
    "We have checked the documentation for you.",
    "If this does not help, reply with what you observed at each step.",
])
def test_fixed_on_our_side_ignores_activity_claims(text):
    assert not CLAIM_DETECTORS["the issue has been fixed on our side"].search(text), text
