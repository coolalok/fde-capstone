"""Smoke tests for src/api.py — the HTTP wrapper over the harness pipeline.

Per capstone-test-writer §The three test cases. The endpoints are thin
composition over stages already covered by their own tests; this file's job
is to catch wiring regressions — a route that stops registering, a healthz
that returns 500 on a clean checkout, a metrics endpoint that stops emitting
one of the pack-mandated series.

No network is touched. classify/retrieve/generate/run_all/route are stubbed
per test so the endpoint's plumbing is exercised without pulling the model
provider or Chroma into the test path. The stubs return the same shapes the
real functions return, so a change to a return-type signature that would
break the endpoint also breaks these tests.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A TestClient with the pipeline stubbed out.

    Every stage is monkey-patched to a schema-valid return value. The test
    then asserts the endpoint composes them correctly.
    """
    from fastapi.testclient import TestClient

    from src import api as api_module
    from src.schema import (
        Alternative,
        ClassificationResult,
        GeneratedResponse,
        Passage,
        Route,
    )

    def fake_classify(ticket, **_):
        return ClassificationResult(
            intent="authentication_failure",
            urgency="medium",
            confidence=0.92,
            alternatives=[Alternative(intent="account_access", confidence=0.05)],
            reasoning="stubbed",
        )

    def fake_retrieve(query, *, ticket_id, **_):
        return [
            Passage(
                doc_id="DOC-AUTH-001",
                score=0.87,
                text="stubbed passage",
                title="Auth",
                category="auth",
                chunk_index=0,
                chunk_text="stubbed passage",
            )
        ]

    def fake_generate(ticket, passages, *, ticket_id, **_):
        return GeneratedResponse(
            answer="Check the security page. [DOC-AUTH-001]",
            citations=["DOC-AUTH-001"],
            confidence=0.9,
            unknown=False,
        )

    def fake_run_all(response, context, **_):
        return []  # all pass

    def fake_route(ticket, classification, passages, response=None,
                   guardrail_results=None, **_):
        return Route(
            decision="auto_respond",
            reason="stubbed",
            trigger="confident_and_grounded",
            bundle=None,
            threshold_applied=0.85,
        )

    monkeypatch.setattr(api_module, "classify", fake_classify)
    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)
    monkeypatch.setattr(api_module, "generate", fake_generate)
    monkeypatch.setattr(api_module, "run_all", fake_run_all)
    monkeypatch.setattr(api_module, "route", fake_route)

    # /healthz reads MODEL_API_KEY and CHROMA_PATH at request time via the
    # module-level constants. Point CHROMA_PATH at a real directory so the
    # health check reports it exists, and ensure a key looks present.
    (tmp_path / "chroma").mkdir()
    monkeypatch.setattr(api_module, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(api_module, "MODEL_API_KEY", "test-key-not-real")
    monkeypatch.setattr(api_module, "GUARDRAIL_MODEL", "test-judge-model")
    # Point the decision-log DB at the tmp path too so _sqlite_writable passes.
    monkeypatch.setattr(api_module, "DATABASE_URL",
                        f"sqlite:///{tmp_path / 'decisions.db'}")

    return TestClient(api_module.app)


# ─── happy path ──────────────────────────────────────────────────────


def test_root_lists_the_three_endpoints(client):
    """GET / returns the service card with the three real endpoints named."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "CloudServe Support Automation"
    endpoints = body["endpoints"]
    assert "POST /ticket" in endpoints
    assert "GET /healthz" in endpoints
    assert "GET /metrics" in endpoints


def test_healthz_reports_all_four_checks_green_on_a_valid_setup(client):
    """GET /healthz returns 200 and every check true when config is valid."""
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["chroma_path_exists"] is True
    assert body["checks"]["sqlite_writable"] is True
    assert body["checks"]["model_key_present"] is True
    assert body["checks"]["guardrail_model_configured"] is True


def test_metrics_returns_prometheus_text_with_expected_series(client):
    """GET /metrics returns Prometheus format with the Setup Guide §06 series.

    The five panels the pack names each map to one metric in src/metrics.py;
    this test asserts every one is exposed. A regression that renamed or
    dropped one would leave a panel blank.
    """
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    # Five Setup Guide §06 panels + two build-necessary extras.
    for series in [
        "tickets_processed_total",
        "response_seconds",
        "guardrail_blocks_total",
        "classification_confidence",
        "model_call_failures_total",
        "decision_log_write_failures_total",
    ]:
        assert series in body, f"missing metric: {series}"


def test_ticket_returns_route_and_citations_on_the_happy_path(client):
    """POST /ticket composes classify → retrieve → generate → guardrails →
    route and returns the decision plus citations.

    Also asserts the answer has inline [DOC-*] markers stripped before the
    customer sees it (strip_citation_markers is applied on the auto_respond
    path — same rule the harness applies before writing the reply)."""
    payload = {
        "ticket_id": "TEST-1",
        "channel": "email",
        "subject": "Cannot sign in",
        "body": "Invalid credentials since this morning.",
        "customer_tier": "business",
    }
    r = client.post("/ticket", json=payload)
    assert r.status_code == 200
    body = r.json()

    assert body["ticket_id"] == "TEST-1"
    assert body["decision"] == "auto_respond"
    assert body["intent"] == "authentication_failure"
    assert body["confidence"] == pytest.approx(0.92)
    assert body["threshold_applied"] == pytest.approx(0.85)
    assert body["citations"] == [{"doc_id": "DOC-AUTH-001", "score": 0.87}]
    assert body["unknown"] is False
    assert body["escalation_bundle_present"] is False
    assert body["latency_seconds"] >= 0
    assert body["escalation_bundle"] is None, "nothing to hand over when it is sent"

    # Customer-facing string must have the inline marker stripped.
    assert "[DOC-AUTH-001]" not in body["answer"]
    assert "Check the security page" in body["answer"]


# ─── adversarial paths ──────────────────────────────────────────────


def test_ticket_rejects_missing_required_fields(client):
    """POST /ticket without ticket_id/channel/body returns 422 from Pydantic."""
    r = client.post("/ticket", json={"body": "just a body"})
    assert r.status_code == 422
    err = r.json()
    missing = {"->".join(map(str, e["loc"])) for e in err["detail"]}
    assert "body->ticket_id" in missing
    assert "body->channel" in missing


def test_ticket_survives_a_pipeline_exception_and_returns_500(client, monkeypatch):
    """A11 last defence: an unexpected exception below the endpoint is caught,
    logged, and returned as HTTP 500 with a structured body — the process
    keeps serving."""
    from src import api as api_module

    def raiser(*_, **__):
        raise RuntimeError("simulated stage crash")

    monkeypatch.setattr(api_module, "classify", raiser)

    r = client.post("/ticket", json={
        "ticket_id": "ERR-1",
        "channel": "email",
        "body": "test",
    })
    assert r.status_code == 500
    body = r.json()
    assert body["ticket_id"] == "ERR-1"
    assert "RuntimeError" in body["error"]
    assert body["elapsed_seconds"] >= 0

    # The process is still up — the next request works.
    r2 = client.get("/healthz")
    assert r2.status_code == 200


# ─── degraded path ──────────────────────────────────────────────────


def test_healthz_reports_503_when_a_check_fails(client, monkeypatch):
    """A missing model key trips healthz — the assessor's most common failure
    (Setup Guide §09 first row) is visible from the outside."""
    from src import api as api_module

    monkeypatch.setattr(api_module, "MODEL_API_KEY", "")

    r = client.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "fail"
    assert body["checks"]["model_key_present"] is False
    # Other checks still report — the caller can see which one failed.
    assert body["checks"]["chroma_path_exists"] is True


# ─── FR-11: the escalation bundle reaches the human ─────────────────


def test_an_escalation_returns_the_bundle_the_human_needs(client, monkeypatch):
    """FR-11. The bundle was built for every escalation and only its existence
    reported; EV-D1 is that a bare forwarded ticket makes the agent re-search
    what the retriever already found."""
    from src import api as api_module
    from src.schema import Alternative, EscalationBundle, Passage, Route

    def escalating_route(ticket, classification, passages, response=None,
                         guardrail_results=None, **_):
        return Route(
            decision="escalate",
            reason="escalate: intent 'compliance_request' is on the never-auto-respond list",
            trigger="never_auto_respond_intent",
            threshold_applied=0.85,
            bundle=EscalationBundle(
                passages=[Passage(doc_id="DOC-SEC-003", score=0.71, text="Audit logs…",
                                  title="Audit logging", category="security",
                                  chunk_index=0, chunk_text="Audit logs…")],
                alternatives=[Alternative(intent="account_access", confidence=0.2)],
                draft="Here is what the retention policy says.",
                draft_blocked=True,
                uncertainty="intent is on the never-auto-respond list",
            ),
        )

    monkeypatch.setattr(api_module, "route", escalating_route)
    r = client.post("/ticket", json={"ticket_id": "TEST-ESC", "channel": "email",
                                     "subject": "Retention", "body": "How long are logs kept?"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "escalate"
    assert body["escalation_bundle_present"] is True

    bundle = body["escalation_bundle"]
    assert bundle["passages"] == [{"doc_id": "DOC-SEC-003", "title": "Audit logging",
                                   "score": 0.71, "text": "Audit logs…"}]
    assert bundle["alternatives"] == [{"intent": "account_access", "confidence": 0.2}]
    assert bundle["draft"] == "Here is what the retention policy says."
    assert bundle["draft_blocked"] is True, "the reviewer must be told not to send it as-is"
    assert bundle["uncertainty"]
