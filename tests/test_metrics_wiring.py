"""The Prometheus metrics are wired to the pipeline, not just declared.

src/metrics.py declared five metrics from Week 1, but only the two failure
counters were ever incremented: the dashboard the Setup Guide §06 asks for
(tickets by channel and outcome, latency, guardrail activations, confidence
distribution) would have been empty on every panel. These tests read the
registry before and after a call, so a metric that stops being recorded fails
here rather than showing up as a flat line in a screenshot.

No network: every model call goes through a stub.
"""
from __future__ import annotations

from prometheus_client import REGISTRY

from src.schema import (
    ClassificationResult,
    GeneratedResponse,
    GuardrailContext,
    GuardrailResult,
    Passage,
    Ticket,
)


def _value(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels or None) or 0.0


def _hist_count(name: str) -> float:
    return _value(f"{name}_count")


def _ticket() -> Ticket:
    return Ticket(ticket_id="MET-01", channel="email", subject="Cannot sign in",
                  body="Invalid credentials since this morning.")


def test_classifier_records_the_confidence_distribution(db):
    from src.classify import classify

    before = _hist_count("classification_confidence")
    result = classify(_ticket(), call_model=lambda s, u, seed=0: (
        '{"intent": "authentication_failure", "urgency": "medium", '
        '"confidence": 0.92, "alternatives": [], "reasoning": "credentials named"}'))
    assert result.error is None
    assert _hist_count("classification_confidence") == before + 1


def test_a_classifier_fallback_is_not_a_confidence_observation(db):
    """A fallback states 0.0 because the model never answered. Recording it would
    put a spike at zero that reads as an overcautious classifier, not an outage."""
    from src.classify import classify

    before = _hist_count("classification_confidence")
    result = classify(_ticket(), call_model=lambda s, u, seed=0: (_ for _ in ()).throw(
        TimeoutError("provider unreachable")))
    assert result.error is not None
    assert _hist_count("classification_confidence") == before


def test_guardrail_blocks_are_counted_by_guardrail(db):
    from src.guardrails import run_all

    class _Blocked:
        name = "pii"
        blocking = True

        def check(self, response, context):
            return GuardrailResult(name="pii", passed=False, blocking=True,
                                   reason="PII detected (email=1)")

    class _Passed:
        name = "grounding"
        blocking = True

        def check(self, response, context):
            return GuardrailResult(name="grounding", passed=True, blocking=True, reason="ok")

    before_blocked = _value("guardrail_blocks_total", guardrail="pii")
    before_passed = _value("guardrail_blocks_total", guardrail="grounding")

    run_all(
        GeneratedResponse(answer="Check the security page.", citations=["DOC-AUTH-001"],
                          confidence=0.9, unknown=False),
        GuardrailContext(ticket=_ticket(),
                         passages=[Passage(doc_id="DOC-AUTH-001", score=0.7,
                                           text="Security page shows the lock.",
                                           title="Auth", category="authentication")],
                         classification=ClassificationResult(
                             intent="authentication_failure", urgency="medium",
                             confidence=0.92)),
        guardrails=[_Blocked(), _Passed()],
    )

    assert _value("guardrail_blocks_total", guardrail="pii") == before_blocked + 1
    assert _value("guardrail_blocks_total", guardrail="grounding") == before_passed


def test_harness_counts_each_ticket_by_channel_and_outcome(db, monkeypatch):
    """The panel the Setup Guide asks for is tickets split by channel AND outcome."""
    import evaluation.harness as h
    from tests.test_harness_smoke import SMOKE_TICKETS, FakeModelClient

    monkeypatch.setattr(h, "retrieve", lambda query, **kw: [])

    raw = SMOKE_TICKETS[0]
    row = h.process_ticket(raw, call_model=FakeModelClient())
    before = _value("tickets_processed_total", channel="email", outcome=row["decision"])
    latency_before = _hist_count("response_seconds")

    again = h.process_ticket(raw, call_model=FakeModelClient())

    assert again["decision"] == row["decision"]
    assert _value("tickets_processed_total", channel="email",
                  outcome=row["decision"]) == before + 1
    assert _hist_count("response_seconds") == latency_before + 1


def test_metrics_server_is_off_unless_asked_for():
    """A graded run must not need a free port; the metrics report is the artefact."""
    from src.config import METRICS_PORT

    assert METRICS_PORT == 0, (
        "METRICS_PORT is set in this environment; the committed default must be 0")
