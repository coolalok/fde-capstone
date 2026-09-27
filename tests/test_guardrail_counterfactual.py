"""The guardrail counterfactual's replay of src/route.py's rule order.

This tool exists to answer "what would the run have sent under different
guardrail rules?", and it refuses to report unless the unchanged rules first
reproduce every stored decision. That check is only worth anything while the
replay tracks the router: when route.py made answer_relevance advisory and the
replay kept treating it as a hard block, the tool stopped reporting on every
run made afterwards. So the rules here are asserted against the sets in
src.route rather than against copies of them.
"""
from __future__ import annotations

import json

import pytest

from evaluation import guardrail_counterfactual as gc
from src import route

AUTO, HOLD = "auto_respond", "escalate"


def _guardrail(name, *, passed=True, blocking=True, fail_safe=False, details=None):
    return {"name": name, "passed": passed, "blocking": blocking,
            "fail_safe": fail_safe, "reason": "test", "details": details or {}}


def _row(tid="T1", *, decision=AUTO, guardrails=(), **over):
    row = {"ticket_id": tid, "decision": decision, "degraded": False,
           "injection_flags": [], "intent": "billing_query", "confidence": 0.9,
           "retrieved_doc_ids": ["DOC-BILL-001"], "unknown": False,
           "guardrails": list(guardrails)}
    row.update(over)
    return row


def _sends(row):
    return gc.sends(row, pii_filter=False, drop_relevance=False)


# ─── the sets come from the router, not from a copy ──────────────────


def test_the_rule_sets_are_the_routers_own_objects():
    """A restated set drifts silently; a shared one cannot."""
    assert gc.ADVISORY_GUARDRAILS is route.ADVISORY_GUARDRAILS
    assert gc.COVERAGE_GUARDRAILS is route.COVERAGE_GUARDRAILS
    assert gc.NEVER_AUTO_RESPOND is route.NEVER_AUTO_RESPOND


# ─── happy path ──────────────────────────────────────────────────────


def test_a_confident_grounded_ticket_with_clean_guardrails_sends():
    assert _sends(_row(guardrails=[_guardrail("pii"), _guardrail("grounding")])) is True


# ─── adversarial: each rule that must hold a reply ───────────────────


def test_an_advisory_relevance_verdict_does_not_block():
    """route._is_advisory: a substantive answer_relevance failure is recorded
    and logged, but is not on its own a reason to withhold a reply."""
    assert _sends(_row(guardrails=[_guardrail("answer_relevance", passed=False)])) is True


def test_a_fail_safe_relevance_verdict_still_blocks():
    """fail_safe says the judge could not run, not that the draft is fine."""
    row = _row(guardrails=[_guardrail("answer_relevance", passed=False, fail_safe=True)])
    assert _sends(row) is False


@pytest.mark.parametrize("over", [
    {"guardrails": [_guardrail("grounding", passed=False)]},        # 2. safety
    {"injection_flags": ["ignore previous instructions"]},          # 2b. injection
    {"intent": "security_incident"},                                # 3. policy
    {"retrieved_doc_ids": []},                                      # 4. coverage
    {"unknown": True},                                              # 5. honesty
    {"confidence": 0.84},                                           # 6. quality
    {"guardrails": [_guardrail("confidence_floor", passed=False)]},  # 6. the floor guardrail
])
def test_every_rule_that_holds_a_reply_holds_it_in_the_replay(over):
    assert _sends(_row(**over)) is False


def test_the_coverage_guardrail_is_read_at_rule_six_not_as_a_safety_block():
    """D-14: confidence_floor never looked at the draft, so it is a coverage
    hold. It still stops the send, but below the policy and honesty rules."""
    row = _row(guardrails=[_guardrail("confidence_floor", passed=False)], unknown=True)
    assert _sends(row) is False


# ─── degraded ────────────────────────────────────────────────────────


def test_a_degraded_ticket_never_sends():
    assert _sends(_row(degraded=True, guardrails=[_guardrail("pii")])) is False


def test_a_row_with_no_guardrail_block_at_all_is_handled():
    assert _sends(_row(guardrails=[])) is True


# ─── the reproduction gate ───────────────────────────────────────────


def _write_run(tmp_path, rows):
    (tmp_path / "results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    tickets = tmp_path / "tickets.json"
    tickets.write_text(json.dumps(
        [{"ticket_id": r["ticket_id"], "labels": {"expected_route": AUTO}} for r in rows]))
    return ["--run", str(tmp_path), "--tickets", str(tickets)]


def test_a_replay_that_reproduces_the_run_reports(tmp_path, capsys):
    rows = [_row("T1", guardrails=[_guardrail("answer_relevance", passed=False)]),
            _row("T2", decision=HOLD, intent="feature_request")]
    assert gc.main(_write_run(tmp_path, rows)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["n"] == 2
    assert report["configs"]["as_run"] == {
        "sent": 1, "correct_sends": 1, "wrong_sends": 0,
        "send_precision": 1.0, "correct_fcr": 0.5}


def test_a_replay_that_does_not_reproduce_the_run_refuses_and_names_the_ticket(
        tmp_path, capsys):
    """A counterfactual on a replay that does not match the run is noise — for
    instance a run made before answer_relevance became advisory."""
    rows = [_row("T1"), _row("T2", decision=HOLD)]   # T2 held for no replayable reason
    assert gc.main(_write_run(tmp_path, rows)) == 1
    out = capsys.readouterr().out
    assert "T2" in out and "not reporting" in out
