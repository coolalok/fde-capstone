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

import pytest

from evaluation.harness import build_metrics, main, process_ticket
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
                "intent_per_class", "intent_accuracy"):
        assert key in m["technical_metrics"], key
    for key in ("decisions_logged", "reconciles", "guardrail_activations",
                "pii_detections", "confidence_calibration"):
        assert key in m["governance_metrics"], key


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
