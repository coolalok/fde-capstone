"""The Evaluation Framework results table. Expected values are worked by hand.

A figure in this table is quoted in the report, so a wrong one is worse than a
missing one; and a row the project did not measure to the Framework's method must
say so rather than show a stand-in number.
"""
from __future__ import annotations

import pytest

from evaluation import results_table as rt

AUTO, HOLD = "auto_respond", "escalate"


def _row(tid, decision, *, latency=10.0, answer="", usage=None, guardrails=None, **extra):
    row = {"ticket_id": tid, "decision": decision, "latency_seconds": latency,
           "guardrails": guardrails or [],
           "response_post_guardrail": {"answer": answer,
                                       "sent_to_customer": decision == AUTO}}
    if usage is not None:
        row["usage"] = usage
    row.update(extra)
    return row


def _labels(**routes):
    return {tid: {"expected_route": route} for tid, route in routes.items()}


def test_fcr_counts_only_correct_sends_as_resolved():
    rows = [_row("A", AUTO), _row("B", AUTO), _row("C", AUTO), _row("D", HOLD)]
    r = rt.first_contact_resolution(rows, _labels(A=AUTO, B=AUTO, C=HOLD, D=HOLD))
    assert r["achieved"] == "50.0% correctly resolved (75.0% auto-sent)"
    assert r["status"] == rt.NOT_MET
    assert r["notes"].startswith("1 of 3 sent replies")
    assert "n=4" in r["confidence"]


def test_fcr_without_labels_is_unmeasured_not_met():
    """Deleting the labels must not turn a failing run into a passing one: the
    auto-send rate is a different measure and belongs in Notes, not in the
    Achieved cell where it reads as a resolution figure."""
    rows = [_row(f"S{i}", AUTO) for i in range(8)] + [_row("H", HOLD), _row("I", HOLD)]
    r = rt.first_contact_resolution(rows, {})          # 80% auto-sent, target 60%
    assert r["status"] == rt.NOT_MEASURED
    assert r["achieved"] == "Not measured"
    assert "80.0% of tickets were auto-sent" in r["notes"]
    assert "No labels" in r["confidence"]


def test_escalation_rate_counts_escalations_and_blocks():
    rows = [_row("A", AUTO), _row("B", "escalate"), _row("C", "block"), _row("D", AUTO)]
    r = rt.escalation_rate(rows)
    assert r["achieved"] == "50.0%"
    assert r["status"] == rt.NOT_MET


def test_replayed_tickets_are_not_live():
    assert rt.is_live(_row("A", AUTO))                                    # no usage: old run
    assert rt.is_live(_row("A", AUTO, usage={"calls": 6, "cached_calls": 0}))
    assert not rt.is_live(_row("A", AUTO, usage={"calls": 6, "cached_calls": 6}))
    # Recorded before cache hits were logged: completed with no call at all.
    assert not rt.is_live(_row("A", AUTO, usage={"calls": 0}))
    # A ticket with no calls because the classifier failed was still live.
    assert rt.is_live(_row("A", HOLD, usage={"calls": 0}, classifier_error="429"))


def test_latency_p95_excludes_cache_replayed_tickets():
    live = [_row(f"L{i}", AUTO, latency=float(i), usage={"calls": 6, "cached_calls": 0})
            for i in range(1, 21)]
    replayed = _row("R", AUTO, latency=0.1, usage={"calls": 6, "cached_calls": 6})
    r = rt.latency_p95(live + [replayed], {"model_name": "m", "guardrail_model": "g"})
    # Nearest rank over 20 live values: ceil(0.95 * 20) = 19th = 19.0 s.
    assert r["achieved"] == "19.0 s"
    assert "n=20 live tickets" in r["confidence"]
    assert "1 cache-replayed tickets excluded" in r["confidence"]


def test_private_data_scan_catches_a_planted_email_in_a_sent_reply_only():
    rows = [_row("A", AUTO, answer="Write to jane.doe@example.com for help."),
            _row("B", HOLD, answer="Held draft mentioning bob@example.com")]
    r = rt.private_data(rows, {"governance_metrics": {"pii_detections": 0}})
    assert r["achieved"] == "1"
    assert r["status"] == rt.NOT_MET
    assert "A (email)" in r["notes"]
    assert "1 sent replies" in r["confidence"]


def test_private_data_clean_run_meets_the_condition():
    r = rt.private_data([_row("A", AUTO, answer="Rotate the key from Settings.")],
                        {"governance_metrics": {"pii_detections": 2}})
    assert (r["achieved"], r["status"]) == ("0", rt.MET)
    assert "blocked 2 drafts" in r["notes"]


@pytest.mark.parametrize("row", [
    rt.satisfaction_proxy({}),
    rt.hallucination_rate({}),
    rt.citation_accuracy([], {"technical_metrics": {}}, {}),
])
def test_rows_not_measured_to_method_never_show_a_number(row):
    assert row["status"] == rt.NOT_MEASURED
    assert not any(ch.isdigit() for ch in row["achieved"])
    assert row["confidence"] and row["notes"], "every column is filled"


def test_nearby_evidence_goes_in_notes_labelled_as_a_different_measure():
    b18 = {"source_run": "run_x", "n": 50, "human_answer_relevance_mean": 4.86,
           "human_unsupported": 1, "judge_unsupported": 5, "pooled_spearman": 0.35}
    r = rt.hallucination_rate({"b18": b18})
    assert r["achieved"] == "Not measured to method"
    assert "1 of 50" in r["notes"] and "two people" in r["notes"]


def _per_class(**spec):
    """spec: class -> (support, predicted, precision)."""
    return {"technical_metrics": {"intent_accuracy": 0.9, "intent_per_class": {
        c: {"support": s, "predicted": p, "precision": v, "recall": 1.0}
        for c, (s, p, v) in spec.items()}}}


def test_classification_precision_is_met_only_when_every_class_reaches_target():
    metrics = _per_class(a=(10, 10, 1.0), b=(10, 10, 0.8), never_gold=(0, 4, 0.0))
    r = rt.classification_precision([], metrics, {"x": {}})
    assert r["achieved"] == ("90.0% mean over the 2 classes with a precision "
                             "denominator; 1 of 2 at ≥85%")
    assert r["status"] == rt.NOT_MET


def test_a_class_that_was_never_predicted_is_excluded_from_the_mean():
    """0/0 averaged in as a real zero understates every other class's work: the
    mean of 1.0 and 0.9 is 95%, not the 63.3% a phantom 0% would give."""
    metrics = _per_class(a=(10, 10, 1.0), b=(10, 10, 0.9), ghost=(12, 0, None))
    r = rt.classification_precision([], metrics, {"x": {}})
    assert r["achieved"].startswith("95.0% mean over the 2 classes")
    assert "ghost" in r["notes"] and "undefined rather than 0%" in r["notes"]
    assert "1 never" in r["confidence"], "the caveat can see the unmeasurable class"
    assert r["status"] == rt.NOT_MEASURED, "every measured class passes; one cannot be"


def test_the_n_beside_a_precision_is_the_precision_denominator():
    """support is tp+fn, the RECALL denominator. Printing it beside a precision
    computed over tp+fp names the wrong sample."""
    metrics = _per_class(weak=(19, 29, 0.5172), mid=(10, 25, 0.9), strong=(20, 20, 1.0))
    r = rt.classification_precision([], metrics, {"x": {}})
    assert "weak 52% (n=29)" in r["notes"], "29 predictions, not the 19 of support"
    assert "median 25" in r["confidence"]


def test_a_stored_run_without_the_precision_denominator_is_recomputed_from_its_rows():
    """Runs recorded before `predicted` existed wrote 0/0 and a measured 0.0
    identically, so the stored block cannot answer the question and the rows must."""
    legacy = {"technical_metrics": {"intent_accuracy": 0.5, "intent_per_class": {
        "a": {"support": 1, "precision": 1.0, "recall": 1.0},
        "ghost": {"support": 1, "precision": 0.0, "recall": 0.0},
    }}}
    rows = [_row("T1", AUTO, intent="a"), _row("T2", AUTO, intent="a")]
    labels = {"T1": {"intent": "a"}, "T2": {"intent": "ghost"}}
    r = rt.classification_precision(rows, legacy, labels)
    assert r["achieved"].startswith("50.0% mean over the 1 classes")
    assert "ghost" in r["notes"]


def test_a_run_where_nothing_was_predicted_reports_no_precision_at_all():
    metrics = _per_class(a=(10, 0, None), b=(10, 0, None))
    r = rt.classification_precision([], metrics, {"x": {}})
    assert (r["achieved"], r["status"]) == ("Not measured", rt.NOT_MEASURED)


def test_every_framework_row_and_column_is_present_in_the_markdown():
    rows = [_row("A", AUTO, answer="ok"), _row("B", HOLD)]
    tickets = {"A": {"ticket_id": "A"}, "B": {"ticket_id": "B"}}
    metrics = {"run_id": "harness-20260919T131836Z-abc", "model_name": "m",
               "guardrail_model": "g", "governance_metrics": {"decisions_logged": 2,
                                                              "reconciles": True}}
    table = rt.build(rows, metrics, tickets, evidence={})
    md = rt.to_markdown(table)
    assert "| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |" in md
    for measure, _, _ in rt.FRAMEWORK_ROWS:
        assert f"| {measure} |" in md
    for r in table["rows"]:
        assert r["achieved"] and r["confidence"] and r["notes"], r["measure"]
    assert table["header"]["run_date"] == "2026-09-19"
    assert "not recorded" in md, "a run without cache logging must not claim 0 cached calls"
    assert any("Hidden evaluation set runs: 0" in x for x in table["limitations"])


def test_code_version_ignores_result_only_commits_and_flags_uncommitted_code(monkeypatch):
    calls = []

    class _Done:
        def __init__(self, out):
            self.stdout = out

    def fake_run(args, **kw):
        calls.append(args)
        return _Done("abc1234" if args[1] == "log" else " M src/route.py")

    monkeypatch.setattr(rt.subprocess, "run", fake_run)
    assert rt.git_commit() == "abc1234 + uncommitted changes"
    assert calls[0][-3:] == list(rt.CODE_PATHS), "only code paths decide the version"


def test_markdown_splits_wrong_sends_from_wrong_holds_and_names_the_stage():
    rows = [_row("A", AUTO, answer="ok"), _row("B", AUTO, answer="ok"),
            _row("C", "block", trigger="guardrail_blocked", retrieved_doc_ids=["DOC-A"],
                 guardrails=[{"name": "answer_relevance", "passed": False,
                              "blocking": True, "fail_safe": False}],
                 stage_seconds={"classification": 2.0, "retrieval": 0.1,
                                "generation": 9.0, "guardrails": 20.0},
                 usage={"calls": 5, "cached_calls": 0})]
    tickets = {
        "A": {"ticket_id": "A", "labels": {"expected_route": AUTO,
                                           "answerable_from_docs": True}},
        "B": {"ticket_id": "B", "labels": {"expected_route": HOLD,
                                           "answerable_from_docs": False}},
        "C": {"ticket_id": "C", "labels": {"expected_route": AUTO,
                                           "answerable_from_docs": True,
                                           "expected_doc_ids": ["DOC-A"]}},
    }
    metrics = {"run_id": "harness-20260920T010000Z-abc", "governance_metrics": {}}
    md = rt.to_markdown(rt.build(rows, metrics, tickets, evidence={}))
    assert "| Send precision (sent replies that should have been sent) | 50.0% (1 of 2) |" in md
    assert "| Send coverage (tickets that should be answered, answered) | 50.0% (1 of 2) |" in md
    assert "| answerability:sent_unanswerable | 1 |" in md
    assert "| guardrail:answer_relevance:verdict | 1 |" in md
    assert "| guardrails | 20.0 | 20.0 | 20.0 |" in md


def test_markdown_omits_routing_and_stage_sections_when_there_is_nothing_to_show():
    rows = [_row("A", AUTO, answer="ok")]
    metrics = {"run_id": "harness-20260920T010000Z-abc", "governance_metrics": {}}
    md = rt.to_markdown(rt.build(rows, metrics, {"A": {"ticket_id": "A"}}, evidence={}))
    assert "## Routing against the labels" not in md
    assert "## Where the time goes" not in md
    assert "## Intent classification by class" not in md


def test_markdown_reports_precision_and_recall_per_class_with_the_confusion_matrix():
    """Evaluation Framework: "Report both, per class, and include the confusion
    matrix in your appendix." Hand-worked: gold a,a,b; predicted a,b,c. a is
    1/1 precise and 1/2 recalled; b was predicted once, wrongly, and labelled
    once, missed; c was predicted but never labelled, so it has no recall."""
    rows = [_row("T1", AUTO, intent="a"), _row("T2", AUTO, intent="b"),
            _row("T3", AUTO, intent="c")]
    tickets = {"T1": {"ticket_id": "T1", "labels": {"intent": "a"}},
               "T2": {"ticket_id": "T2", "labels": {"intent": "a"}},
               "T3": {"ticket_id": "T3", "labels": {"intent": "b"}}}
    metrics = {"run_id": "harness-20260920T010000Z-abc", "governance_metrics": {}}
    table = rt.build(rows, metrics, tickets, evidence={})
    md = rt.to_markdown(table)
    assert "| Intent | n labelled | n predicted | Precision | Recall |" in md
    assert "| a | 2 | 1 | 100.0% | 50.0% |" in md
    assert "| b | 1 | 1 | 0.0% | 0.0% |" in md
    assert "| c | 0 | 1 | 0.0% | n/a |" in md, "never labelled: no recall, not 0%"
    assert "| Labelled / predicted | 1 | 2 | 3 |" in md
    assert "| 1. a | **1** | 1 |  |" in md, "diagonal bold, off-diagonal plain"
    assert "| 2. b |  |  | 1 |" in md
    assert "| 3. c |  |  |  |" in md
    assert table["intent"]["confusion"] == {"a": {"a": 1, "b": 1}, "b": {"c": 1}}


def _ticket(tid, subject, body, route, answerable=True):
    return {"ticket_id": tid, "subject": subject, "body": body,
            "labels": {"expected_route": route, "answerable_from_docs": answerable}}


def test_tickets_whose_text_is_labelled_both_ways_are_counted(monkeypatch, tmp_path):
    # No dev file to compare against: the conflict is inside the run itself.
    monkeypatch.setattr(rt, "DEV_TICKETS_PATH", tmp_path / "absent.json")
    tickets = {
        "A": _ticket("A", "Roll back", "How do I revert?", AUTO, True),
        "B": _ticket("B", "Roll back", "How do I revert?", HOLD, False),   # same text, opposite
        "C": _ticket("C", "Billing", "Why is my invoice higher?", AUTO, True),
    }
    rows = [_row(t, AUTO) for t in tickets]
    got = rt.contested_labels(rows, tickets)
    assert got["n"] == 2 and got["tickets"] == ["A", "B"] and got["pairs_within_run"] == 1


def test_agreeing_duplicates_are_not_contested(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "DEV_TICKETS_PATH", tmp_path / "absent.json")
    tickets = {
        "A": _ticket("A", "Roll back", "How do I revert?", AUTO, True),
        "B": _ticket("B", "Roll back", "How do I revert?", AUTO, True),
    }
    got = rt.contested_labels([_row("A", AUTO), _row("B", AUTO)], tickets)
    assert got == {"n": 0, "tickets": [], "pairs_within_run": 0}


def test_a_ticket_file_without_labels_reports_nothing_contested(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "DEV_TICKETS_PATH", tmp_path / "absent.json")
    tickets = {"A": {"ticket_id": "A", "subject": "s", "body": "b"}}
    assert rt.contested_labels([_row("A", AUTO)], tickets)["n"] == 0


def test_the_limitation_line_names_the_count_and_the_in_run_pairs(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "DEV_TICKETS_PATH", tmp_path / "absent.json")
    tickets = {
        "A": _ticket("A", "Roll back", "How do I revert?", AUTO, True),
        "B": _ticket("B", "Roll back", "How do I revert?", HOLD, False),
    }
    rows = [_row("A", AUTO, answer="ok"), _row("B", HOLD)]
    metrics = {"run_id": "harness-20260920T010000Z-abc", "governance_metrics": {}}
    md = rt.to_markdown(rt.build(rows, metrics, tickets, evidence={}))
    assert "2 of 2 tickets have text that appears elsewhere" in md
    assert "1 such pair sits inside this run" in md


def test_a_halted_run_is_labelled_in_the_header_and_the_limitations():
    """Figures from a halted run describe the halt, not the system (D-15)."""
    rows = [_row("A", HOLD), _row("B", HOLD)]
    tickets = {"A": {"ticket_id": "A"}, "B": {"ticket_id": "B"}}
    metrics = {"run_id": "harness-20260920T101112Z-abc", "model_name": "m",
               "guardrail_model": "g",
               "governance_metrics": {"decisions_logged": 2, "reconciles": True,
                                      "kill_switch_active": True}}
    table = rt.build(rows, metrics, tickets, evidence={})
    assert table["header"]["kill_switch_active"] is True
    assert "Kill switch ACTIVE" in rt.to_markdown(table)
    assert any("kill switch was active" in line for line in table["limitations"])


# ─── cross-group variation: the status must follow the verdict ───────


def _region(tid, region, correct):
    """One ticket that should be auto-sent, and the row that got it right or wrong."""
    ticket = {"ticket_id": tid, "subject": "Sign in", "customer_region": region,
              "body": "I cannot sign in to the console this morning", "channel": "email",
              "language_fluency": "fluent", "customer_tier": "standard",
              "labels": {"expected_route": AUTO, "answerable_from_docs": True,
                         "expected_doc_ids": [], "intent": "authentication_failure"}}
    return ticket, _row(tid, AUTO if correct else HOLD)


def _regions(**spec):
    """spec: region -> (correct, total). Returns (rows, tickets)."""
    tickets, rows = {}, []
    for region, (k, n) in spec.items():
        for i in range(n):
            t, r = _region(f"{region}-{i}", region, i < k)
            tickets[t["ticket_id"]] = t
            rows.append(r)
    return rows, tickets


def test_cross_group_variation_is_met_when_every_segment_is_within_the_target():
    rows, tickets = _regions(europe=(20, 20), asia_pacific=(20, 20))
    r, _ = rt.cross_group_variation(rows, tickets)
    assert r["achieved"].startswith("0 pts")
    assert r["status"] == rt.MET


def test_a_breach_that_is_not_significant_is_unmeasured_not_failed():
    """The row used to print "breach not significant" and NOT MET in the same
    line. 8/12 against 12/12 is a 33-point gap whose intervals overlap: at these
    segment sizes the target cannot be resolved, so there is no verdict to give."""
    rows, tickets = _regions(latin_america=(8, 12), europe=(12, 12))
    r, _ = rt.cross_group_variation(rows, tickets)
    assert r["achieved"] == "33 pts (customer_region: latin_america vs europe)"
    assert r["status"] == rt.NOT_MEASURED
    assert r["confidence"] == ("breach not significant: latin_america n=12 "
                               "against europe n=12")
    assert "excluded" not in r["confidence"], "no segment was excluded on this run"


def test_a_breach_whose_intervals_separate_is_still_a_failure():
    """The fix must not launder a real gap: 50/100 against 100/100 separates."""
    rows, tickets = _regions(latin_america=(50, 100), europe=(100, 100))
    r, _ = rt.cross_group_variation(rows, tickets)
    assert r["achieved"] == "50 pts (customer_region: latin_america vs europe)"
    assert r["status"] == rt.NOT_MET
    assert r["confidence"].startswith("breach: latin_america n=100 against europe n=100")


def test_the_exclusion_note_only_claims_an_exclusion_that_ran():
    rows, tickets = _regions(latin_america=(8, 12), europe=(12, 12), asia_pacific=(0, 5))
    r, _ = rt.cross_group_variation(rows, tickets)
    assert f"; 1 segments under n={rt.fa.MIN_N} excluded" in r["confidence"]


def test_cross_group_variation_without_labels_is_unmeasured():
    rows = [_row("A", AUTO), _row("B", HOLD)]
    r, report = rt.cross_group_variation(rows, {"A": {"ticket_id": "A"}})
    assert (r["achieved"], r["status"]) == ("Not measured", rt.NOT_MEASURED)
    assert report == {}


def test_repeat_contacts_takes_its_baseline_from_history_and_stays_unmeasured():
    """The Dataset Guide calls history.* the current baseline. Hand-worked: 1 of
    4 tickets came back under human handling, so halved is 12.5% or lower. The
    run itself cannot see a customer return, so Achieved is not a number."""
    rows = [_row("A", AUTO, answer="ok"), _row("B", AUTO, answer="ok"),
            _row("C", HOLD), _row("D", HOLD)]
    tickets = {t: {"ticket_id": t, "history": {"repeat_contact": t == "A"}}
               for t in "ABCD"}
    labels = _labels(A=AUTO, B=HOLD, C=HOLD, D=HOLD)
    r = rt.repeat_contacts(rows, tickets, labels)
    assert r["baseline"] == "25.0% (history, n=4)"
    assert (r["achieved"], r["status"]) == ("Not measured", rt.NOT_MEASURED)
    assert "halved is 12.5% or lower" in r["notes"]
    assert "1 of 2 sent replies went to tickets the labels say must be held" in r["notes"]


def test_repeat_contacts_without_history_keeps_the_framework_baseline():
    r = rt.repeat_contacts([_row("A", AUTO)], {"A": {"ticket_id": "A"}}, {})
    assert r["baseline"] == "Not measured"
    assert "no baseline to halve" in r["notes"]


def test_availability_counts_every_kind_of_stage_failure_once():
    """Four failure shapes and one clean ticket: 1 of 5 fully available. A ticket
    with two failures is still one unavailable ticket."""
    rows = [_row("OK", AUTO),
            _row("D", HOLD, degraded=True, classifier_error="boom"),
            _row("C", HOLD, classifier_error="timeout"),
            _row("G", HOLD, generator_error="empty choices"),
            _row("F", "block", guardrails=[{"name": "pii", "passed": False,
                                            "fail_safe": True}])]
    r = rt.availability(rows)
    assert r["achieved"] == "20.0%"
    assert r["status"] == rt.NOT_MET
    assert r["notes"].startswith("1 of 5 tickets had every stage work. 4 hit")
    assert "5 of 5 still received a decision" in r["notes"]


def test_availability_says_when_the_sample_is_too_small_to_confirm_the_target():
    """100% of 80 has a Wilson lower bound near 95%: met on the point estimate,
    not confirmed. At 2000 clean tickets the bound clears 99.5% and the caveat goes."""
    small = rt.availability([_row(f"T{i}", AUTO) for i in range(80)])
    assert (small["achieved"], small["status"]) == ("100.0%", rt.MET)
    assert "cannot confirm 99.5%" in small["notes"]
    large = rt.availability([_row(f"T{i}", AUTO) for i in range(2000)])
    assert "cannot confirm" not in large["notes"]


# ─── calibration: an abstention is not a probability (2026-09-27) ────
# Source: evaluation/results/dev_local_410_20260924. 11 tickets came back
# unclear_request at confidence 0.0, none a classifier error, and all 11 gold
# labels were unclear_request — so band 0.0-0.1 read stated 0.00 against
# observed 1.00 and drove the tier-three condition to NOT MET on a +100.0 pt
# "gap", while the bands holding 399 of the 410 tickets were inside tolerance.


def _calib_metrics(buckets, **extra):
    g = {"decisions_logged": 1, "reconciles": True,
         "confidence_calibration": buckets}
    g.update(extra)
    return {"governance_metrics": g}


def _row_stub(status="MET"):
    return {"achieved": "0", "confidence": "n/a", "status": status}


def test_calibration_names_the_excluded_abstentions(db):
    conds = rt.governance_conditions(
        [{"ticket_id": "DEV-1"}],
        _calib_metrics(
            [{"bucket": "0.8-0.9", "n": 171, "stated_avg": 0.849,
              "observed": 0.813, "gap_pp": -3.7, "sufficient_n": True}],
            calibration_abstentions_excluded=11),
        _row_stub(), _row_stub())
    calib = next(c for c in conds if c["condition"] == "Confidence calibration")
    assert calib["status"] == rt.MET
    assert "11 abstentions" in calib["result"]
    assert "state no probability" in calib["result"]


def test_calibration_says_nothing_when_nothing_was_excluded(db):
    conds = rt.governance_conditions(
        [{"ticket_id": "DEV-1"}],
        _calib_metrics([{"bucket": "0.8-0.9", "n": 171, "stated_avg": 0.849,
                         "observed": 0.813, "gap_pp": -3.7, "sufficient_n": True}]),
        _row_stub(), _row_stub())
    calib = next(c for c in conds if c["condition"] == "Confidence calibration")
    assert "excluded from the gap" not in calib["result"]


def test_a_real_calibration_breach_still_fails(db):
    """The exclusion must not launder a genuine miscalibration into MET."""
    conds = rt.governance_conditions(
        [{"ticket_id": "DEV-1"}],
        _calib_metrics([{"bucket": "0.9-1.0", "n": 200, "stated_avg": 0.95,
                         "observed": 0.70, "gap_pp": -25.0, "sufficient_n": True}],
                       calibration_abstentions_excluded=11),
        _row_stub(), _row_stub())
    calib = next(c for c in conds if c["condition"] == "Confidence calibration")
    assert calib["status"] == rt.NOT_MET


# ─── limitations name the set the run actually used ──────────────────


def _hdr(n=3):
    return {"tickets": n, "hidden_set_runs": 0, "tickets_with_replayed_calls": 0}


def test_limitations_name_the_development_set_on_a_dev_run():
    out = " ".join(rt.limitations(_hdr(), [], [{"ticket_id": f"DEV-{i:04d}"}
                                               for i in range(1, 4)], {}))
    assert "labelled development set" in out
    assert "validation set" not in out
    assert "VAL-0004" not in out, "a dev run must not cite a ticket it never processed"


def test_limitations_keep_the_val_example_only_when_that_ticket_is_in_the_run():
    rows = [{"ticket_id": "VAL-0004"}, {"ticket_id": "VAL-0005"}]
    out = " ".join(rt.limitations(_hdr(2), [], rows, {}))
    assert "labelled validation set" in out
    assert "VAL-0004" in out


def test_limitations_stay_neutral_on_a_mixed_run():
    rows = [{"ticket_id": "DEV-0001"}, {"ticket_id": "VAL-0001"}]
    out = " ".join(rt.limitations(_hdr(2), [], rows, {}))
    assert "from a labelled data," in out or "labelled data" in out
