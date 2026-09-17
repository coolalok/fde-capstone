"""End-to-end smoke test for evaluation/harness.py — A9/A10 in miniature.

Per capstone-test-writer §The harness smoke test. Runs the real harness over a
handful of fixture tickets with a fake model client, so a regression in the
harness cannot silently poison B-21. No network is touched.

What this protects: the harness is the only thing that turns working components
into a graded artefact. If it stops writing a metric group, or stops
reconciling, the gate run produces a plausible-looking report that is wrong.
"""
from __future__ import annotations

import json
import re

import pytest

from evaluation.harness import build_metrics, main, process_ticket
from src.generate import strip_citation_markers
from evaluation.harness import process_ticket as harness_process_ticket

SMOKE_TICKETS = [
    {
        "ticket_id": "SMOKE-01", "channel": "email",
        "subject": "Cannot sign in", "body": "Invalid credentials since this morning.",
        "customer_name": "Test Customer", "customer_tier": "business",
        "labels": {"intent": "authentication_failure", "urgency": "medium",
                   "expected_route": "auto_respond", "answerable_from_docs": True,
                   "expected_doc_ids": ["DOC-AUTH-001"], "must_not_auto_respond": False},
    },
    {
        "ticket_id": "SMOKE-02", "channel": "chat", "subject": "",
        "body": "Please add per-project spend caps.",
        "customer_name": "Test Two", "customer_tier": "standard",
        "labels": {"intent": "feature_request", "urgency": "low",
                   "expected_route": "escalate", "answerable_from_docs": False,
                   "expected_doc_ids": [], "must_not_auto_respond": True},
    },
    {
        "ticket_id": "SMOKE-03", "channel": "forum", "subject": "Rollback",
        "body": "How do I revert to the previous revision?",
        "customer_name": "Test Three", "customer_tier": "enterprise",
        "labels": {"intent": "rollback_request", "urgency": "medium",
                   "expected_route": "auto_respond", "answerable_from_docs": True,
                   "expected_doc_ids": ["DOC-DEPLOY-002"], "must_not_auto_respond": False},
    },
]


class FakeModelClient:
    """Returns a schema-valid payload for whichever prompt it is handed.

    One fake for every stage: the harness threads a single call_model through
    classify, generate and the guardrails, so this must answer all three.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, system: str, user: str, seed: int = 0) -> str:
        self.calls.append(system[:40])
        if "classifier" in system:
            return json.dumps({"intent": "authentication_failure", "urgency": "medium",
                               "confidence": 0.92, "alternatives": [],
                               "reasoning": "credentials named"})
        if "PII detection" in system:
            return json.dumps({"passed": True, "detections": []})
        if "grounding-check" in system:
            return json.dumps({"passed": True, "unsupported_claims": []})
        if "commitment" in system or "tone" in system.lower():
            return json.dumps({"passed": True, "commitments": []})
        # generator
        return json.dumps({"answer": "Check the security page. [DOC-AUTH-001]",
                           "citations": ["DOC-AUTH-001"], "confidence": 0.9,
                           "unknown": False})


@pytest.fixture
def _no_retrieval(monkeypatch):
    """Keep the smoke test off Chroma as well as off the network."""
    from src.schema import Passage
    import evaluation.harness as h

    monkeypatch.setattr(
        h, "retrieve",
        lambda query, **kw: [Passage(doc_id="DOC-AUTH-001", score=0.7,
                                     text="Security page shows the lock.",
                                     title="Auth", category="authentication")])


def test_every_ticket_produces_a_row_and_a_decision(db, _no_retrieval):
    rows = [process_ticket(t, call_model=FakeModelClient()) for t in SMOKE_TICKETS]
    assert len(rows) == len(SMOKE_TICKETS), "zero silent drops"
    assert all(r.get("decision") for r in rows)
    assert all(r["latency_seconds"] >= 0 for r in rows)


def test_metrics_report_contains_every_required_group(db, _no_retrieval):
    """FR-22: counts, business, technical and governance metrics."""
    rows = [process_ticket(t, call_model=FakeModelClient()) for t in SMOKE_TICKETS]
    truth = {t["ticket_id"]: t["labels"] for t in SMOKE_TICKETS}
    m = build_metrics(rows, truth, run_id="smoke", skip_guardrails=False)
    for group in ("counts", "business_metrics", "technical_metrics", "governance_metrics"):
        assert group in m, f"missing metric group: {group}"
    for key in ("fcr_proxy", "escalation_rate", "repeat_contact_proxy", "ttr_seconds_median"):
        assert key in m["business_metrics"], key
    for key in ("latency_p50_seconds", "latency_p95_seconds", "retrieval_hit_at_3",
                "intent_per_class", "intent_accuracy", "citation_accuracy",
                "citation_accuracy_sent"):
        assert key in m["technical_metrics"], key
    for key in ("decisions_logged", "reconciles", "guardrail_activations",
                "pii_detections", "confidence_calibration"):
        assert key in m["governance_metrics"], key


def test_citation_accuracy_scores_drafts_against_expected_doc_ids():
    from evaluation.harness import _citation_accuracy

    truth = {
        "T1": {"expected_doc_ids": ["DOC-A-001"]},
        "T2": {"expected_doc_ids": ["DOC-A-001", "DOC-B-001"]},
        "T3": {"expected_doc_ids": []},
        "T4": {"expected_doc_ids": ["DOC-A-001"]},
    }
    rows = [
        {"ticket_id": "T1", "citations": ["DOC-A-001", "DOC-C-001"]},  # p 0.5, r 1.0
        {"ticket_id": "T2", "citations": ["DOC-A-001"]},               # p 1.0, r 0.5
        {"ticket_id": "T3", "citations": ["DOC-A-001"]},               # nothing expected
        {"ticket_id": "T4", "citations": []},                          # declined: not scored
    ]
    assert _citation_accuracy(rows, truth) == {
        "n": 2, "precision": 0.75, "recall": 0.75, "citing_with_no_expected_doc": 1,
    }


def test_latency_p95_is_never_below_p50(db, _no_retrieval):
    """Regression: int(n*0.95)-1 picked the FASTEST ticket at n=2."""
    rows = [process_ticket(t, call_model=FakeModelClient()) for t in SMOKE_TICKETS]
    m = build_metrics(rows, {}, run_id="smoke", skip_guardrails=False)
    t = m["technical_metrics"]
    assert t["latency_p95_seconds"] >= t["latency_p50_seconds"]
    assert t["latency_max_seconds"] >= t["latency_p95_seconds"]


def test_a8_reconciles_for_the_run(db, _no_retrieval, monkeypatch):
    """A8: every processed ticket has a decision-log row, scoped to this run."""
    from src.logging_store import new_run_id, set_run_id

    run_id = set_run_id(new_run_id("smoke"))
    rows = [process_ticket(t, call_model=FakeModelClient()) for t in SMOKE_TICKETS]
    m = build_metrics(rows, {}, run_id=run_id, skip_guardrails=False)
    g = m["governance_metrics"]
    assert g["reconciles"] is True, g
    assert g["decisions_logged"] == m["counts"]["tickets_processed"]
    assert g["missing_from_log"] == [] and g["extra_in_log"] == []


def test_a_ticket_that_raises_does_not_end_the_run(db, _no_retrieval, monkeypatch):
    """FR-23: one bad ticket degrades and escalates; the rest still process."""
    import evaluation.harness as h

    def explode(ticket, **kw):
        if ticket.ticket_id == "SMOKE-02":
            raise RuntimeError("provider unreachable")
        from src.schema import ClassificationResult
        return ClassificationResult(intent="onboarding", urgency="low", confidence=0.9)

    monkeypatch.setattr(h, "classify", explode)
    rows = [process_ticket(t, call_model=FakeModelClient()) for t in SMOKE_TICKETS]
    bad = [r for r in rows if r["ticket_id"] == "SMOKE-02"][0]
    assert bad["degraded"] is True
    assert bad["decision"] == "escalate"
    assert "provider unreachable" in bad["reason"]
    assert len(rows) == 3, "the run continued"


def test_full_cli_run_exits_zero_and_writes_both_artefacts(db, _no_retrieval, tmp_path,
                                                           monkeypatch):
    """FR-21/A9/A10: one command, unattended, exit 0, both files on disk."""
    import evaluation.harness as h

    monkeypatch.setattr(h, "process_ticket",
                        lambda raw, **kw: process_ticket(raw, call_model=FakeModelClient(),
                                                         **{k: v for k, v in kw.items()
                                                            if k != "call_model"}))
    src = tmp_path / "in.json"
    src.write_text(json.dumps(SMOKE_TICKETS))
    out = tmp_path / "out"
    code = main(["--input", str(src), "--output", str(out)])
    assert code == 0
    assert (out / "results.jsonl").exists()
    assert (out / "metrics_report.json").exists()
    report = json.loads((out / "metrics_report.json").read_text())
    assert report["counts"]["tickets_processed"] == len(SMOKE_TICKETS)
    assert len((out / "results.jsonl").read_text().strip().splitlines()) == len(SMOKE_TICKETS)


# ─── result rows must be auditable after the fact (2026-09-13) ───────


def test_row_records_the_draft_not_just_its_length(db, _no_retrieval):
    """Diagnosing a guardrail block needs the text that was judged.

    The DEV-0485 / VAL-0008 / VAL-0019 PII false positive could not be
    identified from the stored rows — only answer_len was kept — and cost a
    re-run against the live provider to reproduce. A blocked draft is never
    sent to the customer, so results.jsonl is the only place it survives.
    """
    row = process_ticket(SMOKE_TICKETS[0])
    assert "answer" in row
    assert isinstance(row["answer"], str)
    assert row["answer_len"] == len(row["answer"])


def test_fail_safe_blocks_are_reported_apart_from_real_findings():
    """A judge outage and a fabricating generator both block. A report that
    cannot tell them apart reads the outage as rampant fabrication — the
    misreading that cost time on Bug 5.
    """
    rows = [
        {"ticket_id": "T1", "decision": "block", "latency_seconds": 0.1,
         "guardrails": [
             {"name": "grounding", "passed": False, "blocking": True,
              "fail_safe": True, "reason": "grounding_guardrail_error: Timeout"},
         ]},
        {"ticket_id": "T2", "decision": "block", "latency_seconds": 0.1,
         "guardrails": [
             {"name": "grounding", "passed": False, "blocking": True,
              "fail_safe": False, "reason": "1 unsupported claim(s)"},
             {"name": "pii", "passed": False, "blocking": True,
              "fail_safe": False, "reason": "PII detected (email=1)"},
         ]},
        {"ticket_id": "T3", "decision": "block", "latency_seconds": 0.1,
         "guardrails": [
             {"name": "pii", "passed": False, "blocking": True,
              "fail_safe": True, "reason": "pii_guardrail_error: llm path failed"},
         ]},
    ]
    m = build_metrics(rows, {}, run_id="smoke", skip_guardrails=False)
    gov = m["governance_metrics"]

    # Both kinds still count as activations — they are all blocks (A7).
    assert gov["guardrail_activations"] == {"grounding": 2, "pii": 2}
    # But the fail-safe half is separable.
    assert gov["guardrail_fail_safe_blocks"] == {"grounding": 1, "pii": 1}
    # And a PII guardrail that ERRORED did not detect PII in a draft.
    assert gov["pii_detections"] == 1


def test_rows_are_streamed_not_buffered_to_the_end(db, _no_retrieval, tmp_path,
                                                   monkeypatch):
    """An interrupted run must leave the rows it already finished.

    A 40-minute B-21 run was killed at ~60 of 80 tickets and left an empty
    results file, because rows were buffered in memory and written once at the
    end. Partial evidence beats none.
    """
    inp = tmp_path / "t.json"
    inp.write_text(json.dumps(SMOKE_TICKETS[:3]))
    out = tmp_path / "res"

    real = harness_process_ticket
    seen: list[str] = []

    def die_on_third(raw, **kw):
        if len(seen) == 2:
            raise KeyboardInterrupt("simulated kill mid-run")
        seen.append(raw["ticket_id"])
        return real(raw, **kw)

    monkeypatch.setattr("evaluation.harness.process_ticket", die_on_third)
    with pytest.raises(KeyboardInterrupt):
        main(["--input", str(inp), "--output", str(out)])

    written = (out / "results.jsonl").read_text().strip().splitlines()
    assert len(written) == 2, "rows finished before the interrupt must survive"
    assert [json.loads(w)["ticket_id"] for w in written] == seen


# ─── debug trail: request in, response before and after guardrails ───


def test_row_captures_the_inbound_request_for_every_channel(db, _no_retrieval):
    """Until now only LENGTHS were logged (input_summary='body_len=310'),
    which cannot explain a misclassification or an ingest bug. Both the raw
    payload and the normalised ticket are kept — a difference between them
    IS the ingest bug.
    """
    for ticket in SMOKE_TICKETS:
        row = process_ticket(ticket)
        req = row["request"]
        assert req["raw"]["ticket_id"] == ticket["ticket_id"]
        assert req["normalised"]["channel"] == row["channel"]
        # The text itself, not a length.
        assert isinstance(req["normalised"]["body"], str)
        assert isinstance(req["normalised"]["original_body"], str)


def test_request_capture_never_contains_evaluation_labels(db, _no_retrieval):
    """Labels are ground truth. A production-shaped record must not carry
    them, or the trail becomes useless for judging real behaviour.
    """
    labelled = dict(SMOKE_TICKETS[0])
    labelled["labels"] = {"intent": "billing_query", "answerable_from_docs": True}
    row = process_ticket(labelled)
    assert "labels" not in row["request"]["raw"]
    assert "billing_query" not in json.dumps(row["request"])


def test_pre_and_post_guardrail_responses_are_both_recorded(db, _no_retrieval):
    """The point of the pair is to show what the guardrails changed. Today
    they only permit or withhold, never rewrite — so recording the equality
    is recording a claim that can later break.
    """
    row = process_ticket(SMOKE_TICKETS[0])
    pre, post = row["response_pre_guardrail"], row["response_post_guardrail"]

    assert pre["answer"] == row["answer"]
    assert set(post) == {
        "answer", "sent_to_customer", "withheld_by",
        "withheld_reason", "modified_from_draft", "markers_stripped",
    }
    if post["sent_to_customer"]:
        # The reply is the draft minus its internal citation markers.
        assert post["answer"] == strip_citation_markers(pre["answer"])
        assert post["withheld_by"] == []
    else:
        assert post["answer"] == "", "a withheld draft must not appear as sent"


def test_a_blocked_draft_is_kept_but_marked_not_sent(
    db, _no_retrieval, monkeypatch
):
    """The draft survives for review; the post-guardrail record shows it was
    never sent and names which guardrail withheld it.
    """
    from src.schema import GuardrailResult

    def one_block(response, ctx, **kw):
        return [GuardrailResult(name="pii", passed=False, blocking=True,
                                reason="PII detected (email=1)")]

    monkeypatch.setattr("evaluation.harness.run_all", one_block)
    row = process_ticket(SMOKE_TICKETS[0])

    assert row["decision"] == "block"
    assert row["response_post_guardrail"]["sent_to_customer"] is False
    assert row["response_post_guardrail"]["answer"] == ""
    assert row["response_post_guardrail"]["withheld_by"] == ["pii"]
    # ...but the draft is still inspectable.
    assert row["response_pre_guardrail"]["answer"] == row["answer"]


def test_degraded_ticket_still_carries_the_debug_fields(
    db, _no_retrieval, monkeypatch
):
    """A crashed ticket is the one you most want to inspect."""
    def boom(*a, **kw):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr("evaluation.harness.classify", boom)
    row = process_ticket(SMOKE_TICKETS[0])

    assert row["degraded"] is True
    assert row["request"]["raw"]["ticket_id"] == SMOKE_TICKETS[0]["ticket_id"]
    assert row["response_pre_guardrail"]["answer"] == ""
    assert row["response_post_guardrail"]["sent_to_customer"] is False


# ─── internal citation markers must not reach the customer (2026-09-13) ──
# None of the 200 senior-agent reference replies contains a [DOC-ID] marker;
# 15 of 20 auto-sent replies on the 13 Sep gate run did.


MARKER = re.compile(r"\[DOC-[A-Z]+-\d+\]")


def test_sent_reply_carries_no_internal_document_ids(db, _no_retrieval,
                                                     monkeypatch):
    """The customer-facing string must be free of [DOC-ID] markers."""
    from src.schema import GeneratedResponse

    drafted = ("Rotate the key first, then revoke the old one.[DOC-AUTH-004] "
               "Check the scopes [DOC-AUTH-002] before you deploy.")

    def fake_generate(ticket, passages, **kw):
        return GeneratedResponse(answer=drafted,
                                 citations=["DOC-AUTH-004", "DOC-AUTH-002"],
                                 confidence=0.95, unknown=False)

    monkeypatch.setattr("evaluation.harness.generate", fake_generate)
    monkeypatch.setattr("evaluation.harness.run_all", lambda r, c, **k: [])
    row = process_ticket(SMOKE_TICKETS[0])

    post = row["response_post_guardrail"]
    assert post["sent_to_customer"] is True
    assert not MARKER.search(post["answer"]), post["answer"]
    assert post["markers_stripped"] is True
    assert post["modified_from_draft"] is True
    # The sources are not lost — they live in the structured field.
    assert row["citations"] == ["DOC-AUTH-004", "DOC-AUTH-002"]
    # ...and the original draft is still inspectable for debugging.
    assert MARKER.search(row["response_pre_guardrail"]["answer"])


def test_escalated_draft_keeps_its_markers_for_the_human_reviewer(
    db, _no_retrieval, monkeypatch
):
    """A withheld draft goes to a person, who benefits from seeing which
    article each claim came from. Stripping is a customer-facing step only.
    """
    from src.schema import GuardrailResult

    monkeypatch.setattr(
        "evaluation.harness.run_all",
        lambda r, c, **k: [GuardrailResult(name="pii", passed=False,
                                           blocking=True, reason="PII")],
    )
    row = process_ticket(SMOKE_TICKETS[0])
    assert row["decision"] == "block"
    assert row["response_post_guardrail"]["answer"] == ""
    # The draft retains whatever the generator produced.
    assert row["response_pre_guardrail"]["answer"] == row["answer"]
