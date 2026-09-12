"""Pydantic models used across components.

Kept small and centralised so every component reads the same shapes.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Ticket(BaseModel):
    """A normalised support ticket.

    The ingest step (FR-01/02/03) produces one of these. Downstream components
    read it. Segment fields (customer_tier, customer_region, customer_name,
    language_fluency) are carried on the Ticket for the router and for the
    decision log — they are NOT passed to the classifier per FR-04 v2.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)

    ticket_id: str
    channel: str  # email | chat | docs_comment | forum
    subject: str = ""
    body: str = ""
    received_at: str = ""

    # Ingest bookkeeping
    original_body: str = ""
    warnings: list[str] = Field(default_factory=list)

    # Customer segment fields — carried but never passed to the classifier
    customer_id: str = ""
    customer_name: str = ""
    customer_tier: str = ""
    customer_region: str = ""
    language_fluency: str = ""


class Alternative(BaseModel):
    """One alternative-intent guess with its own confidence."""

    intent: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClassificationResult(BaseModel):
    """Return type of src.classify.classify. Per FR-04 and FR-05.

    On success `error` is None. On any failure (network, parse, schema),
    `intent="unknown"`, `confidence=0.0`, `error=<str>`. The classifier
    never raises out of the pipeline (per acceptance criterion A11).
    """

    intent: str
    urgency: str  # high | medium | low
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: list[Alternative] = Field(default_factory=list)
    reasoning: str = ""
    error: Optional[str] = None

    # Governance flag set by classify() when log_decision failed to persist.
    # Router treats decision_logged=False as a hard-escalate signal (per D-06,
    # EV-M5). See src/classify.py and Bug 1 in the Stage 5 revision log.
    decision_logged: bool = True

    @classmethod
    def unknown_fallback(cls, error: str, urgency: str = "medium") -> "ClassificationResult":
        return cls(
            intent="unknown",
            urgency=urgency,
            confidence=0.0,
            alternatives=[],
            reasoning="",
            error=error,
        )


class Passage(BaseModel):
    """One retrieved passage from the help-article corpus. Per FR-06 and FR-07.

    Passages are ordered by relevance score (higher = better). Callers cite by
    doc_id — that identifier is what resolves back to a full article. `text` is
    what the retriever returned (post-B-30 this includes the title header); the
    raw chunk without the title header is preserved as `chunk_text` for any
    consumer that needs just the passage body.
    """

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    score: float = Field(ge=0.0, le=1.0)
    text: str
    title: str = ""
    category: str = ""
    chunk_index: int = 0
    chunk_text: str = ""


class GeneratedResponse(BaseModel):
    """Return type of src.generate.generate. Per FR-13, FR-14, FR-15.

    On success `error` is None. On any failure (network, parse, schema
    violation, retry exhaustion, citation resolution failure), returns an
    unknown-response with `error` populated. The generator never raises out of
    the pipeline (per acceptance criterion A11).

    Field semantics:
      - answer: the drafted reply to the customer. Empty string ("") when
        unknown is true.
      - citations: doc_ids the answer relies on. Each citation MUST be present
        in the retrieval result the caller supplied. Empty list ([]) when
        unknown is true.
      - confidence: the model's stated confidence in [0, 1]. 0.0 on
        unknown_fallback.
      - unknown: true when the passages do not support an answer (FR-14) or
        when generation failed. When true, answer is "" and citations is [].
      - retries: how many times the Self-RAG loop retried (0 or 1).
    """

    answer: str
    citations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    unknown: bool
    retries: int = 0
    error: Optional[str] = None
    decision_logged: bool = True

    @classmethod
    def unknown_fallback(
        cls, error: str, retries: int = 0
    ) -> "GeneratedResponse":
        return cls(
            answer="",
            citations=[],
            confidence=0.0,
            unknown=True,
            retries=retries,
            error=error,
        )


class GuardrailResult(BaseModel):
    """One guardrail's verdict on a generated response.

    Every guardrail in this project is blocking (per A7). A non-passing
    result with ``blocking=True`` is what makes the router pick ``block``.

    Fields:
      - name: guardrail identifier, e.g. ``"pii" | "grounding" |
        "instruction_integrity" | "confidence_floor"``.
      - passed: True when the response cleared the check.
      - blocking: True for every guardrail in this project (A7). Kept as a
        field so a future non-blocking check can be added without changing
        the router.
      - reason: short human-readable sentence for the decision log's
        ``guardrail_results`` column and the router's ``reason`` string.
      - details: structured verdict payload — e.g. PII detections list,
        unsupported-claim list. Deliberately loose (Dict[str, Any]) so each
        guardrail can carry its own shape without inflating the schema.
      - fail_safe: True when passed=False because the CHECK failed, not
        because the answer did — the judge model errored, returned an
        unparseable verdict, or broke its own passed/detections contract.
        Both still block (A7/A11, fail safe); the flag exists because they
        mean opposite things to a reader. A run where the judge provider
        rate-limits reports "grounding blocked 71/71", which looks like
        rampant fabrication and is actually an outage. That misreading cost
        real time on Bug 5, and nothing in the result row distinguished the
        two cases. Routing behaviour is deliberately unchanged.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    passed: bool
    blocking: bool = True
    fail_safe: bool = False
    reason: str = ""
    details: dict = Field(default_factory=dict)


class GuardrailContext(BaseModel):
    """Everything a guardrail is allowed to see when scoring one response.

    Carried explicitly (rather than passing globals) so the guardrails stay
    pure functions of ``(response, context)`` — testable without any
    global state. The ticket is here for the PII customer-name whitelist
    (FR-16); passages are here for the grounding check (FR-17); the
    classification is here for the confidence-floor check (FR-19).
    """

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    ticket: Ticket
    passages: list[Passage] = Field(default_factory=list)
    classification: "ClassificationResult"


GuardrailContext.model_rebuild()


class EscalationBundle(BaseModel):
    """What a human receives when the system hands a ticket over. Per FR-11.

    EV-D1: escalations today arrive as a bare forwarded ticket, so Daniel
    re-reads it, re-searches the docs, and re-asks the customer things they
    already answered. EV-D3 is his stated ideal: the original ticket, what
    tier one thought it was about, the relevant help articles, and the
    specific point where tier one wasn't sure. These four fields are that
    list, produced by the pipeline instead of a person.

    This is not decoration. EV-DATA-03 found 46 of 189 correct escalations
    (24.3%) still have an answer in the help articles — those tickets need a
    human AND the article the retriever already found.
    """

    model_config = ConfigDict(extra="ignore")

    passages: list[Passage] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    draft: str = ""
    draft_blocked: bool = False
    uncertainty: str = ""


class Route(BaseModel):
    """The router's decision for one ticket. Per FR-09 through FR-12.

    `decision` is the action taken. `reason` is written for a support manager
    to read, not a numeric code (FR-12). `trigger` is the machine-readable
    name of the rule that fired, so the decision log can be grouped without
    parsing prose.
    """

    model_config = ConfigDict(extra="ignore")

    decision: str  # auto_respond | escalate | block
    reason: str
    trigger: str
    bundle: Optional[EscalationBundle] = None
    threshold_applied: float = 0.0
