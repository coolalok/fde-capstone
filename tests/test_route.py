"""Tests for src/route.py — deterministic routing.

Coverage per Sprint Plan B-15 definition of done:
  - deterministic (FR-09 / A5)
  - a fixture per escalation trigger, each naming its trigger (FR-10 v2)
  - escalations carry a complete EscalationBundle (FR-11)
  - every reason is human-readable and concrete (FR-12)
  - one decision-log row per call (FR-20 / A8)
"""
from __future__ import annotations

import sqlite3

import pytest

from src.route import AUTO_RESPOND, BLOCK, ESCALATE, NEVER_AUTO_RESPOND, route
from src.schema import (
    Alternative,
    ClassificationResult,
    GeneratedResponse,
    GuardrailResult,
    Passage,
    Ticket,
)

THRESHOLD = 0.80


def _ticket(**kw) -> Ticket:
    base = dict(ticket_id="T-1", channel="email", subject="s",
                body="cannot sign in", customer_tier="business")
    base.update(kw)
    return Ticket(**base)


def _classification(**kw) -> ClassificationResult:
    base = dict(intent="authentication_failure", urgency="medium", confidence=0.90,
                alternatives=[Alternative(intent="account_access", confidence=0.10)])
    base.update(kw)
    return ClassificationResult(**base)


def _passages(n=1) -> list[Passage]:
    return [Passage(doc_id=f"DOC-AUTH-00{i+1}", score=0.72 - i * 0.1,
                    text="passage text", title="Auth", category="authentication")
            for i in range(n)]


def _response(**kw) -> GeneratedResponse:
    base = dict(answer="Reset from settings. [DOC-AUTH-001]",
                citations=["DOC-AUTH-001"], confidence=0.88, unknown=False)
    base.update(kw)
    return GeneratedResponse(**base)


def _passing_guardrails() -> list[GuardrailResult]:
    return [GuardrailResult(name=n, passed=True, blocking=True, reason="ok")
            for n in ("pii", "grounding", "instruction_integrity", "confidence_floor")]


def _route(**kw):
    args = dict(ticket=_ticket(), classification=_classification(),
                passages=_passages(), response=_response(),
                guardrail_results=_passing_guardrails())
    args.update(kw)
    return route(args["ticket"], args["classification"], args["passages"],
                 args["response"], args["guardrail_results"], threshold=THRESHOLD)


# ─── happy path ──────────────────────────────────────────────────────


def test_confident_grounded_ticket_auto_responds(db):
    r = _route()
    assert r.decision == AUTO_RESPOND
    assert r.trigger == "confident_and_grounded"
    assert r.bundle is None, "auto_respond needs no escalation bundle"


# ─── FR-10 v2: one fixture per escalation trigger ────────────────────


def test_unlogged_decision_escalates_before_threshold_is_considered(db):
    """D-03b: an unlogged decision cannot be reconstructed for audit, so it
    escalates even at a confidence that would otherwise auto-respond."""
    c = _classification(confidence=0.99)
    c.decision_logged = False
    r = _route(classification=c)
    assert r.decision == ESCALATE
    assert r.trigger == "decision_not_logged"
    assert "decision log" in r.reason


@pytest.mark.parametrize("intent", sorted(NEVER_AUTO_RESPOND))
def test_policy_intents_never_auto_respond_at_any_confidence(db, intent):
    """D-07 / FR-10 v2: these four escalate however confident the classifier."""
    r = _route(classification=_classification(intent=intent, confidence=1.0))
    assert r.decision == ESCALATE
    assert r.trigger == "never_auto_respond_intent"
    assert intent in r.reason


def test_blocking_guardrail_routes_to_block(db):
    gs = _passing_guardrails()
    gs[0] = GuardrailResult(name="pii", passed=False, blocking=True,
                            reason="email address in outbound reply")
    r = _route(guardrail_results=gs)
    assert r.decision == BLOCK
    assert r.trigger == "guardrail_blocked"
    assert "pii" in r.reason


def test_empty_retrieval_escalates(db):
    r = _route(passages=[])
    assert r.decision == ESCALATE
    assert r.trigger == "empty_retrieval"


def test_generator_unknown_escalates(db):
    r = _route(response=_response(answer="", citations=[], unknown=True))
    assert r.decision == ESCALATE
    assert r.trigger == "generator_unknown"


def test_low_confidence_escalates(db):
    r = _route(classification=_classification(confidence=0.62))
    assert r.decision == ESCALATE
    assert r.trigger == "low_confidence"
    assert "0.62" in r.reason and "0.80" in r.reason


# ─── D-14: the confidence floor is not a safety failure ──────────────


def _floor_failed() -> list[GuardrailResult]:
    gs = _passing_guardrails()
    gs[3] = GuardrailResult(name="confidence_floor", passed=False, blocking=True,
                            reason="classifier confidence 0.620 is below the "
                                   "CONFIDENCE_THRESHOLD floor of 0.850")
    return gs


def test_confidence_floor_failure_escalates_rather_than_blocks(db):
    """D-14: the FR-19 floor reads classifier confidence, never the draft, so
    it cannot say the draft is unsafe. FR-10 and FR-19 both say escalate."""
    r = _route(classification=_classification(confidence=0.62),
               guardrail_results=_floor_failed())
    assert r.decision == ESCALATE
    assert r.trigger == "low_confidence"


def test_confidence_floor_failure_does_not_flag_the_draft(db):
    """Nothing looked at the draft, so the reviewer has nothing to be warned
    about — `draft_blocked` stays False (D-14)."""
    r = _route(classification=_classification(confidence=0.62),
               guardrail_results=_floor_failed())
    assert r.bundle.draft_blocked is False
    assert r.bundle.draft != ""


def test_floor_guardrail_holds_even_above_the_routers_own_threshold(db):
    """FR-19 is defence in depth: a sweep that injects a lower router threshold
    still cannot auto-send a draft the guardrail held (D-14)."""
    r = _route(classification=_classification(confidence=0.90),
               guardrail_results=_floor_failed())
    assert r.decision == ESCALATE
    assert r.trigger == "low_confidence"
    assert "confidence-floor guardrail" in r.reason


# ─── precedence ──────────────────────────────────────────────────────


def test_safety_failure_alongside_the_floor_still_blocks(db):
    """D-14 holds back the floor, not the checks that read the draft."""
    gs = _floor_failed()
    gs[0] = GuardrailResult(name="pii", passed=False, blocking=True, reason="leak")
    r = _route(classification=_classification(confidence=0.62), guardrail_results=gs)
    assert r.decision == BLOCK
    assert r.trigger == "guardrail_blocked"
    assert "confidence_floor" not in r.reason, "the floor is not why it was blocked"


def test_policy_list_outranks_the_confidence_floor(db):
    """7 of the 17 floor-only blocks on b21_openai_gemini_80_d12_20260920 were
    D-07 policy tickets the classifier was also unsure about. Rule 3 owns them
    (D-14)."""
    r = _route(classification=_classification(intent="security_incident",
                                              confidence=0.62),
               guardrail_results=_floor_failed())
    assert r.decision == ESCALATE
    assert r.trigger == "never_auto_respond_intent"


def test_guardrail_block_outranks_low_confidence(db):
    """Both conditions true: the reported trigger must be the higher rule, so
    the reason names what actually happened (FR-12)."""
    gs = _passing_guardrails()
    gs[1] = GuardrailResult(name="grounding", passed=False, blocking=True,
                            reason="unsupported claim")
    r = _route(classification=_classification(confidence=0.10), guardrail_results=gs)
    assert r.decision == BLOCK
    assert r.trigger == "guardrail_blocked"


def test_unlogged_decision_outranks_guardrail_block(db):
    gs = _passing_guardrails()
    gs[0] = GuardrailResult(name="pii", passed=False, blocking=True, reason="leak")
    c = _classification()
    c.decision_logged = False
    r = _route(classification=c, guardrail_results=gs)
    assert r.trigger == "decision_not_logged"


# ─── FR-11: the escalation bundle ────────────────────────────────────


def test_escalation_carries_a_complete_bundle(db):
    """FR-11: passages, top-3 alternatives, any draft, and the uncertainty."""
    c = _classification(confidence=0.55, alternatives=[
        Alternative(intent="account_access", confidence=0.20),
        Alternative(intent="sso_configuration", confidence=0.15),
        Alternative(intent="onboarding", confidence=0.05),
        Alternative(intent="rate_limit", confidence=0.01),
    ])
    r = _route(classification=c, passages=_passages(2))
    b = r.bundle
    assert b is not None
    assert len(b.passages) == 2, "the human should not have to re-run the search"
    assert len(b.alternatives) == 3, "FR-11 says top-3"
    assert b.draft.startswith("Reset from settings"), "draft saves a blank page"
    assert b.draft_blocked is False
    assert b.uncertainty == r.reason


def test_blocked_draft_travels_but_is_flagged(db):
    """A blocked draft still reaches the reviewer — they need to see what was
    caught — but must never be sent as-is."""
    gs = _passing_guardrails()
    gs[0] = GuardrailResult(name="pii", passed=False, blocking=True, reason="leak")
    r = _route(guardrail_results=gs)
    assert r.bundle.draft_blocked is True
    assert r.bundle.draft != ""


def test_bundle_present_for_every_non_auto_respond_decision(db):
    for kw in ({"passages": []},
               {"classification": _classification(confidence=0.1)},
               {"response": _response(answer="", citations=[], unknown=True)}):
        r = _route(**kw)
        assert r.decision != AUTO_RESPOND
        assert r.bundle is not None, f"no bundle for {r.trigger}"


# ─── FR-12: human-readable reasons ───────────────────────────────────


def test_every_reason_is_human_readable_and_concrete(db):
    """FR-12 acceptance: at least 5 words, states a concrete cause."""
    gs_block = _passing_guardrails()
    gs_block[0] = GuardrailResult(name="pii", passed=False, blocking=True, reason="leak")
    unlogged = _classification()
    unlogged.decision_logged = False
    for label, kw in [
        ("auto", {}),
        ("unlogged", {"classification": unlogged}),
        ("blocked", {"guardrail_results": gs_block}),
        ("policy", {"classification": _classification(intent="security_incident")}),
        ("empty", {"passages": []}),
        ("unknown", {"response": _response(answer="", citations=[], unknown=True)}),
        ("lowconf", {"classification": _classification(confidence=0.3)}),
    ]:
        r = _route(**kw)
        assert len(r.reason.split()) >= 5, f"{label}: reason too terse: {r.reason!r}"
        assert r.reason.startswith(r.decision), f"{label}: reason should name the action"
        assert not r.reason.isupper()


# ─── FR-09 / A5: determinism ─────────────────────────────────────────


def test_identical_input_produces_identical_decision_and_reason(db):
    """A5. Built twice from scratch so no shared mutable object can hide a
    dependency on call order."""
    for kw in ({}, {"passages": []}, {"classification": _classification(confidence=0.2)}):
        a = _route(**kw)
        b = _route(**kw)
        assert (a.decision, a.reason, a.trigger) == (b.decision, b.reason, b.trigger)


def test_router_makes_no_model_call(db, monkeypatch):
    """Determinism is structural: the router must not reach the network. Any
    attempt to build an OpenAI client would raise here."""
    import src.route as route_mod
    monkeypatch.setattr(route_mod, "log_decision", lambda **kw: "DL-x")
    assert not hasattr(route_mod, "_openrouter_call")
    r = _route()
    assert r.decision == AUTO_RESPOND


# ─── FR-20 / A8: decision log ────────────────────────────────────────


def test_one_decision_log_row_per_call(db):
    _route(ticket=_ticket(ticket_id="T-LOG"))
    with sqlite3.connect(db) as c:
        rows = c.execute(
            "SELECT stage, action_taken, prediction, threshold_applied, sources_used "
            "FROM decisions WHERE ticket_id = 'T-LOG'").fetchall()
    assert len(rows) == 1
    stage, action, trigger, threshold, sources = rows[0]
    assert stage == "routing"
    assert action == AUTO_RESPOND
    assert trigger == "confident_and_grounded"
    assert threshold == THRESHOLD
    assert "DOC-AUTH-001" in sources


def test_escalation_log_row_has_non_empty_sources_used(db):
    """FR-11 acceptance: every escalation record carries its sources."""
    _route(ticket=_ticket(ticket_id="T-ESC"),
           classification=_classification(confidence=0.4))
    with sqlite3.connect(db) as c:
        action, sources = c.execute(
            "SELECT action_taken, sources_used FROM decisions "
            "WHERE ticket_id = 'T-ESC'").fetchone()
    assert action == ESCALATE
    assert "DOC-AUTH-001" in sources


# ─── abstention: an unidentifiable ticket is never auto-answered ──────
# VAL-0002, 13 Sep: "Following up on my previous message. Any update?"
# classified as unknown, and a reply inventing a log-forwarding problem the
# customer had never mentioned was auto-sent with all five guardrails passing.


def test_unknown_intent_never_auto_responds(db):
    """The classifier could not tell what the ticket is about. Answering it
    anyway is the failure that reached a customer.
    """
    r = _route(classification=_classification(intent="unknown", confidence=0.99))
    assert r.decision == ESCALATE
    assert r.trigger == "never_auto_respond_intent"


def test_unknown_outranks_high_confidence(db):
    """Confidence is about the label, not about whether the ticket was
    understood. A confident 'I don't know' is still 'I don't know'.
    """
    for conf in (0.90, 0.95, 0.99, 1.0):
        r = _route(classification=_classification(intent="unknown", confidence=conf))
        assert r.decision == ESCALATE, f"auto-responded at confidence {conf}"


def test_unknown_still_carries_an_escalation_bundle(db):
    """A human picking this up gets the passages and alternatives, per FR-11 —
    escalating must not mean discarding the work already done.
    """
    r = _route(classification=_classification(intent="unknown"))
    assert r.bundle is not None
    assert r.bundle.passages, "retrieved passages must travel to the human"


def test_the_four_labelled_intents_are_unchanged(db):
    """'unknown' is an orthogonal rule, not a revision of the D-07 derivation.
    It never appears as a labelled intent in either dataset, so the
    precision 1.000 / recall 1.000 result against must_not_auto_respond still
    rests on exactly these four.
    """
    assert NEVER_AUTO_RESPOND == {
        "compliance_request",
        "security_incident",
        "feature_request",
        "unclear_request",
        "unknown",
    }


def test_a_normal_intent_still_auto_responds(db):
    """The guard that stops this widening into 'escalate everything'."""
    r = _route()
    assert r.decision == AUTO_RESPOND


# ─── kill switch (Governance Framework §5, D-15) ────────────────────


def test_kill_switch_escalates_a_ticket_that_would_otherwise_be_sent(db, monkeypatch):
    """The whole point: a ticket clearing every rule still goes to a person."""
    monkeypatch.setenv("KILL_SWITCH", "1")
    r = _route(classification=_classification(confidence=0.99))
    assert r.decision == ESCALATE
    assert r.trigger == "kill_switch_active"
    assert "KILL_SWITCH" in r.reason and "halted" in r.reason


def test_kill_switch_outranks_every_other_rule(db, monkeypatch):
    """Rule 0. Even a PII block — which would otherwise return block — is
    reported as the halt, so the block queue is not filled by a deliberate stop."""
    monkeypatch.setenv("KILL_SWITCH", "1")
    gs = _passing_guardrails()
    gs[0] = GuardrailResult(name="pii", passed=False, blocking=True,
                            reason="email address in outbound reply")
    r = _route(guardrail_results=gs, classification=_classification(intent="compliance_request"),
               passages=[])
    assert (r.decision, r.trigger) == (ESCALATE, "kill_switch_active")


def test_kill_switch_still_hands_the_human_a_bundle(db, monkeypatch):
    """The pipeline keeps working under the halt: FR-11's bundle is intact, so
    the people absorbing the queue are not worse off than on a normal day."""
    monkeypatch.setenv("KILL_SWITCH", "1")
    r = _route()
    assert r.bundle is not None
    assert r.bundle.passages and r.bundle.draft


@pytest.mark.parametrize("value, halted", [
    ("1", True), ("true", True), ("TRUE", True), ("on", True), ("yes", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_kill_switch_reads_the_environment_on_every_call(db, monkeypatch, value, halted):
    """Read at call time, not at import: a running process must halt without a
    restart, which is what makes it a kill switch rather than a config change."""
    monkeypatch.setenv("KILL_SWITCH", value)
    r = _route(classification=_classification(confidence=0.99))
    assert (r.trigger == "kill_switch_active") is halted


def test_service_resumes_when_the_switch_is_cleared(db, monkeypatch):
    monkeypatch.setenv("KILL_SWITCH", "1")
    assert _route().decision == ESCALATE
    monkeypatch.delenv("KILL_SWITCH")
    assert _route().decision == AUTO_RESPOND, "no restart needed to resume"


# ─── injection attempts (R-03, D-16) ────────────────────────────────


def test_an_injection_attempt_escalates_and_names_itself(db):
    """R-03: block, escalate and record. The reason must name the attempt, not
    a downstream symptom — on the 20 Sep probe the blocks came from answer
    relevance, so nothing in the record said an attack had been attempted."""
    ticket = _ticket(injection_flags=["instruction_override"])
    r = _route(ticket=ticket)
    assert r.decision == ESCALATE
    assert r.trigger == "injection_suspected"
    assert "instruction_override" in r.reason
    assert "recorded for review" in r.reason


def test_a_real_guardrail_fault_still_blocks_over_an_injection_flag(db):
    """A draft with PII in it is a block whatever the ticket said: the stronger
    statement wins, and the draft is withheld rather than merely escalated."""
    gs = _passing_guardrails()
    gs[0] = GuardrailResult(name="pii", passed=False, blocking=True,
                            reason="email address in outbound reply")
    r = _route(ticket=_ticket(injection_flags=["jailbreak"]), guardrail_results=gs)
    assert (r.decision, r.trigger) == (BLOCK, "guardrail_blocked")


def test_an_injection_flag_outranks_the_policy_and_confidence_rules(db):
    """So the reason names the attempt rather than 'low confidence'."""
    r = _route(ticket=_ticket(injection_flags=["jailbreak"]),
               classification=_classification(intent="compliance_request", confidence=0.10))
    assert r.trigger == "injection_suspected"


def test_the_escalation_still_carries_a_bundle(db):
    """The person absorbing a suspected attack gets the same evidence as any
    other escalation (FR-11), including the draft the model produced."""
    r = _route(ticket=_ticket(injection_flags=["persona_override"]))
    assert r.bundle is not None and r.bundle.passages
