"""route.py — decide what happens to a ticket: auto-respond, escalate, or block.

Satisfies: FR-09 (deterministic routing),
           FR-10 (v2, escalation triggers — see D-07),
           FR-11 (escalations carry an EscalationBundle),
           FR-12 (human-readable reason).
Writes:    one row to the decision log per call.

Design decisions worth reading:

- **A pure function, and no model call.** ``route()`` reads only values that
  earlier stages already computed. There is no clock, no randomness, no
  network, and nothing read from module state. FR-09 and A5 are therefore
  structural rather than argued: identical inputs cannot produce different
  output. Note that docs/architecture.md previously justified router
  determinism via "temperature=0.0" — that was the wrong argument. The
  router does not call a model at all.

- **Rules are ordered, and the first match wins.** FR-12 requires the reason
  to name the cause, so the order below is the reported precedence, not an
  implementation detail. Governance failures outrank safety failures, which
  outrank policy, which outranks quality signals.

- **The never-auto-respond policy is on intent, not on the label** (D-07).
  ``labels.must_not_auto_respond`` is evaluation ground truth and is not on
  the Ticket (FR-01 v2). The policy set reproduces that flag exactly on both
  labelled sets; the caveat is that production sees the classifier's intent,
  so effective coverage is bounded by classifier recall (measured at B-21).

- **Retrieval being non-empty is NOT evidence the ticket is answerable**
  (D-02a). At the shipped threshold only 14 of 143 non-answerable dev tickets
  return zero passages, so the empty-retrieval rule is a weak signal. The
  policy set and the confidence floor do the real work.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.config import CONFIDENCE_THRESHOLD, MODEL_NAME
from src.logging_store import log_decision
from src.schema import (
    ClassificationResult,
    EscalationBundle,
    GeneratedResponse,
    GuardrailResult,
    Passage,
    Route,
    Ticket,
)

logger = logging.getLogger(__name__)

AUTO_RESPOND = "auto_respond"
ESCALATE = "escalate"
BLOCK = "block"

# D-07 — intents that never auto-answer, whatever the confidence.
# The first four reproduce labels.must_not_auto_respond at precision 1.000 /
# recall 1.000 on the 500-ticket dev set (87/87) and the 80-ticket validation
# set (14/14).
#
# "unknown" is a different KIND of entry and does not affect that derivation:
# it never appears as a labelled intent in either dataset (checked), because it
# is not a category of ticket at all. It is the fallback src/classify.py
# returns when classification FAILED — bad JSON, an unrecognised code, a dead
# provider. The system is saying it could not tell what the ticket is about.
#
# Auto-answering that is indefensible, and it was not hypothetical: on 13 Sep
# VAL-0002 ("Following up on my previous message. Any update?") classified as
# unknown, and a reply inventing a log-forwarding problem the customer had
# never mentioned was sent, with all five guardrails passing. The same ticket
# on an earlier run classified as unclear_request and was correctly escalated
# by this list — so the only thing separating a fabrication from a customer
# was which fallback the classifier happened to land on.
#
# This is the abstention principle applied at the classification stage: a
# system that cannot identify the question must not answer it. See the RAG
# triad note in D-07 for the complementary check on the generated answer.
NEVER_AUTO_RESPOND: frozenset[str] = frozenset(
    {
        "compliance_request",
        "security_incident",
        "feature_request",
        "unclear_request",
        "unknown",
    }
)

# How many classifier alternatives travel in the bundle. FR-11 says top-3.
_BUNDLE_ALTERNATIVES = 3


def route(
    ticket: Ticket,
    classification: ClassificationResult,
    passages: list[Passage],
    response: Optional[GeneratedResponse] = None,
    guardrail_results: Optional[list[GuardrailResult]] = None,
    *,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> Route:
    """Decide the action for one ticket. Pure function; never raises.

    Args:
        ticket: the normalised Ticket.
        classification: output of src.classify.classify.
        passages: output of src.retrieve.retrieve (empty list is valid).
        response: output of src.generate.generate, or None when generation
            was never attempted.
        guardrail_results: output of src.guardrails.run_all, or None when
            guardrails were never run (no draft to check).
        threshold: confidence floor for auto-respond. Defaults to
            CONFIDENCE_THRESHOLD; injectable so B-16's sweep can vary it
            without mutating config.

    Returns:
        A Route. ``bundle`` is populated for every non-auto_respond decision
        (FR-11) and is None for auto_respond.
    """
    guardrail_results = guardrail_results or []
    decision, trigger, reason = _decide(
        classification, passages, response, guardrail_results, threshold
    )

    bundle = (
        None
        if decision == AUTO_RESPOND
        else _build_bundle(classification, passages, response, guardrail_results, reason)
    )
    result = Route(
        decision=decision,
        reason=reason,
        trigger=trigger,
        bundle=bundle,
        threshold_applied=threshold,
    )
    _write_decision_log(ticket, classification, passages, result)
    return result


def _decide(
    classification: ClassificationResult,
    passages: list[Passage],
    response: Optional[GeneratedResponse],
    guardrail_results: list[GuardrailResult],
    threshold: float,
) -> tuple[str, str, str]:
    """The ordered rules. Returns (decision, trigger, reason).

    Precedence, highest first:
      1. governance  — an unlogged upstream decision (D-03b)
      2. safety      — a blocking guardrail did not pass
      3. policy      — intent never auto-answers (D-07)
      4. coverage    — retrieval found nothing
      5. honesty     — the generator declined to answer
      6. quality     — confidence below the floor
    """
    # 1. Governance. An unlogged decision cannot be reconstructed by the
    #    autumn compliance review (EV-M5), so it must not be auto-sent —
    #    checked BEFORE the confidence threshold, per D-03b.
    unlogged = [
        name
        for name, obj in (("classification", classification), ("generation", response))
        if obj is not None and not obj.decision_logged
    ]
    if unlogged:
        return (
            ESCALATE,
            "decision_not_logged",
            f"escalate: the {' and '.join(unlogged)} decision was not written to the "
            f"decision log, so this reply could not be reconstructed for audit; "
            f"escalating regardless of confidence {classification.confidence:.2f}",
        )

    # 2. Safety. Every guardrail in this project blocks rather than warns (A7).
    blocked = [g for g in guardrail_results if g.blocking and not g.passed]
    if blocked:
        names = ", ".join(g.name for g in blocked)
        detail = "; ".join(f"{g.name}: {g.reason}" for g in blocked)
        return (
            BLOCK,
            "guardrail_blocked",
            f"block: {len(blocked)} blocking guardrail(s) did not pass ({names}); "
            f"the drafted reply is withheld and a human must review it — {detail}",
        )

    # 3. Policy (D-07). These intents never auto-answer at any confidence.
    if classification.intent in NEVER_AUTO_RESPOND:
        return (
            ESCALATE,
            "never_auto_respond_intent",
            f"escalate: intent '{classification.intent}' is on the never-auto-respond "
            f"policy list (D-07), which always goes to a person regardless of the "
            f"{classification.confidence:.2f} confidence",
        )

    # 4. Coverage. Nothing crossed the retrieval threshold, so there is no
    #    documentation to ground a reply in (FR-07).
    if not passages:
        return (
            ESCALATE,
            "empty_retrieval",
            "escalate: search returned no help-article passage above the relevance "
            "threshold, so there is nothing to ground an answer in",
        )

    # 5. Honesty. The generator judged the passages insufficient (FR-14).
    if response is not None and response.unknown:
        why = response.error or "the retrieved passages did not support an answer"
        return (
            ESCALATE,
            "generator_unknown",
            f"escalate: the generator declined to answer rather than guess — {why}",
        )

    # 6. Quality. Confidence below the floor (FR-10, D-05).
    if classification.confidence < threshold:
        return (
            ESCALATE,
            "low_confidence",
            f"escalate: classifier confidence {classification.confidence:.2f} is below "
            f"the {threshold:.2f} auto-respond threshold for intent "
            f"'{classification.intent}'",
        )

    top = passages[0]
    return (
        AUTO_RESPOND,
        "confident_and_grounded",
        f"auto_respond: confidence {classification.confidence:.2f} above {threshold:.2f} "
        f"threshold; retrieval matched {top.doc_id} with score {top.score:.2f}; "
        f"all guardrails passed",
    )


def _build_bundle(
    classification: ClassificationResult,
    passages: list[Passage],
    response: Optional[GeneratedResponse],
    guardrail_results: list[GuardrailResult],
    reason: str,
) -> EscalationBundle:
    """Assemble what the human receives. FR-11.

    The draft travels even when a guardrail blocked it, flagged
    ``draft_blocked=True``: the reviewer needs to see what was caught and
    why, and a blocked draft is still a faster starting point than a blank
    page (EV-D3). It must never be sent as-is, which ``draft_blocked``
    signals to the caller.
    """
    blocked = bool([g for g in guardrail_results if g.blocking and not g.passed])
    return EscalationBundle(
        passages=list(passages),
        alternatives=list(classification.alternatives[:_BUNDLE_ALTERNATIVES]),
        draft="" if response is None else response.answer,
        draft_blocked=blocked,
        # FR-11's "tier-one uncertainty flag" has no human tier one in this
        # pipeline. The honest equivalent is the point at which the SYSTEM
        # was not sure — which is exactly the rule that fired.
        uncertainty=reason,
    )


def _write_decision_log(
    ticket: Ticket,
    classification: ClassificationResult,
    passages: list[Passage],
    result: Route,
) -> None:
    """One decision-log row per routing call. FR-20 / A8."""
    decision_id = log_decision(
        ticket_id=ticket.ticket_id,
        stage="routing",
        action_taken=result.decision,
        reason=result.reason,
        prediction=result.trigger,
        confidence=classification.confidence,
        alternatives=[[a.intent, a.confidence] for a in classification.alternatives],
        sources_used=[{"doc_id": p.doc_id, "score": p.score} for p in passages],
        threshold_applied=result.threshold_applied,
        model_name=MODEL_NAME,
        requirement_ids=["FR-09", "FR-10", "FR-11", "FR-12"],
        input_summary=(
            f"intent={classification.intent} "
            f"n_passages={len(passages)} "
            f"tier={ticket.customer_tier or 'unknown'}"
        ),
    )
    if decision_id is None:
        logger.error(
            "route.decision_not_logged",
            extra={"ticket_id": ticket.ticket_id, "decision": result.decision},
        )
