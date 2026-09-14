"""Tests for the B-24 fairness audit. Expected values are worked by hand."""
from __future__ import annotations

import json

import pytest

from evaluation.fairness_audit import (
    MIN_N,
    assess,
    by_segment,
    length_band,
    segment_metrics,
    wilson,
)


def _rec(segment="a", should_auto=True, sent=True, answerable=True, **over):
    r = {"language_fluency": segment, "should_auto": should_auto, "sent": sent,
         "decision_correct": sent == should_auto, "intent_correct": True,
         "answerable_label": answerable, "retrieval_hit": True if answerable else None,
         "confidence": 0.9}
    r.update(over)
    return r


# ─── statistics ──────────────────────────────────────────────────────


def test_wilson_matches_hand_worked_values():
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    lo, hi = wilson(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-4) and hi == 1.0
    assert wilson(0, 0) is None


@pytest.mark.parametrize("words, band", [
    (23, "short"), (24, "medium"), (31, "medium"), (32, "long"),
])
def test_length_band_uses_the_tercile_cuts(words, band):
    assert length_band(words, (23.0, 31.0)) == band


# ─── conditioning on ticket type ─────────────────────────────────────


def test_segment_mix_does_not_masquerade_as_unfairness():
    """Segment B sends in half unanswerable tickets and correctly holds them.
    Its raw auto-send rate is half of A's; its conditioned rates are identical.
    """
    a = [_rec("A") for _ in range(10)]
    held = [_rec("B", should_auto=False, sent=False, answerable=False) for _ in range(5)]
    b = [_rec("B") for _ in range(5)] + held
    ma, mb = segment_metrics(a), segment_metrics(b)
    assert ma["resolution_rate"]["value"] == mb["resolution_rate"]["value"] == 1.0
    assert ma["decision_correct"]["value"] == mb["decision_correct"]["value"] == 1.0
    assert mb["unsafe_send_rate"]["value"] == 0.0
    assert mb["composition"]["unanswerable"] == 5


# ─── judging gaps ────────────────────────────────────────────────────


def _segments(**spec):
    """spec: segment -> (correct, total) for decision_correct."""
    recs = []
    for seg, (k, n) in spec.items():
        recs += [_rec(seg) for _ in range(k)]
        recs += [_rec(seg, should_auto=True, sent=False) for _ in range(n - k)]
    return by_segment(recs, "language_fluency")


def test_a_clear_gap_with_separated_intervals_is_a_breach():
    a = assess(_segments(fluent=(60, 60), non_fluent=(10, 20)), "decision_correct", 0.15)
    assert a["verdict"] == "BREACH"


def test_a_gap_within_overlapping_intervals_is_not_called_significant():
    a = assess(_segments(fluent=(18, 20), non_fluent=(14, 20)), "decision_correct", 0.15)
    assert a["verdict"] == "BREACH_NOT_SIGNIFICANT"   # gap 0.20, intervals overlap


def test_a_small_gap_is_within_limit():
    a = assess(_segments(fluent=(18, 20), non_fluent=(17, 20)), "decision_correct", 0.15)
    assert a["verdict"] == "WITHIN_LIMIT"


def test_a_small_segment_is_reported_but_neither_judged_nor_best():
    a = assess(_segments(fluent=(15, 20), non_fluent=(12, 15), tiny=(3, 3)),
               "decision_correct", 0.15)
    assert a["best_segment"] != "tiny"
    assert "tiny" in a["unassessed"]
    assert {f["segment"]: f["status"] for f in a["segments"]}["tiny"] == "INSUFFICIENT_N"


def test_fewer_than_two_eligible_segments_cannot_be_judged():
    a = assess(_segments(fluent=(20, 20), non_fluent=(MIN_N - 1, MIN_N - 1)),
               "decision_correct", 0.15)
    assert a["verdict"] == "INSUFFICIENT_N"


def test_lower_is_better_for_unsafe_sends():
    recs = ([_rec("A", should_auto=False, sent=False, answerable=False) for _ in range(10)]
            + [_rec("B", should_auto=False, sent=True, answerable=False) for _ in range(10)])
    a = assess(by_segment(recs, "language_fluency"), "unsafe_send_rate", 0.15)
    assert a["best_segment"] == "A"
    assert {f["segment"]: f["gap_from_best"] for f in a["segments"]}["B"] == 1.0


# ─── canary on the committed B-21 run (capstone-test-writer) ─────────


def test_no_fluency_segment_is_wholly_ignored_in_the_b21_run():
    """Not a scoring test. If every non-fluent ticket that should be answered
    were held back, this fails and the problem is seen early.
    """
    tickets = {t["ticket_id"]: t for t in json.load(open("data/validation_tickets.json"))}
    rows = [json.loads(line) for line in
            open("evaluation/results/b21_openai_80_20260914/results.jsonl")]
    for fluency in ("fluent", "non_fluent"):
        group = [r for r in rows if tickets[r["ticket_id"]]["language_fluency"] == fluency
                 and tickets[r["ticket_id"]]["labels"]["expected_route"] == "auto_respond"]
        assert group, fluency
        assert any(r["decision"] == "auto_respond" for r in group), \
            f"no auto-responses for language_fluency={fluency}"


# ─── mix-adjusted quality (direct standardisation) ───────────────────


def test_mix_adjustment_equalises_segments_that_differ_only_in_mix():
    """Same treatment of like tickets, different mix: raw decision_correct
    differs, mix-adjusted quality does not.
    """
    a = ([_rec("A") for _ in range(16)] + [_rec("A", sent=False) for _ in range(4)]
         + [_rec("A", should_auto=False, sent=False, answerable=False) for _ in range(10)])
    b = ([_rec("B") for _ in range(8)] + [_rec("B", sent=False) for _ in range(2)]
         + [_rec("B", should_auto=False, sent=False, answerable=False) for _ in range(20)])
    segs = by_segment(a + b, "language_fluency")
    assert segs["A"]["decision_correct"]["value"] != segs["B"]["decision_correct"]["value"]
    assert segs["A"]["mix_adjusted_quality"]["value"] == segs["B"]["mix_adjusted_quality"]["value"]


def test_mix_adjusted_quality_matches_a_hand_worked_value():
    from evaluation.fairness_audit import mix_adjusted_quality, rate
    seg = {"resolution_rate": rate(30, 40), "unsafe_send_rate": rate(9, 21)}
    got = mix_adjusted_quality(seg, 0.6)
    assert got["value"] == pytest.approx(0.6 * 0.75 + 0.4 * (1 - 9 / 21), abs=1e-4)
    assert got["ci95"][0] < got["value"] < got["ci95"][1]
    assert got["n"] == 21


def test_mix_adjusted_quality_needs_both_components():
    from evaluation.fairness_audit import mix_adjusted_quality, rate
    seg = {"resolution_rate": rate(5, 5), "unsafe_send_rate": rate(0, 0)}
    assert mix_adjusted_quality(seg, 0.6)["value"] is None
