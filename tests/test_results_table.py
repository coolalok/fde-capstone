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


def test_fcr_without_labels_reports_the_send_rate_and_says_so():
    r = rt.first_contact_resolution([_row("A", AUTO), _row("B", HOLD)], {})
    assert r["achieved"] == "50.0% auto-sent"
    assert "No labels" in r["notes"]


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


def test_classification_precision_is_met_only_when_every_class_reaches_target():
    metrics = {"technical_metrics": {"intent_accuracy": 0.9, "intent_per_class": {
        "a": {"support": 10, "precision": 1.0, "recall": 1.0},
        "b": {"support": 10, "precision": 0.8, "recall": 1.0},
        "never_gold": {"support": 0, "precision": 0.0, "recall": 0.0},
    }}}
    r = rt.classification_precision(metrics, {"x": {}})
    assert r["achieved"] == "90.0% mean over 2 classes; 1 of 2 at ≥85%"
    assert r["status"] == rt.NOT_MET


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
