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

    # False when the decision-log write for this classification failed. FR-20
    # was then not satisfied for this ticket, so the router must escalate
    # rather than auto-respond however high `confidence` is: a reply the
    # compliance review (EV-M5) cannot reconstruct must not reach a customer.
    decision_logged: bool = True

    @classmethod
    def unknown_fallback(cls, error: str, urgency: str = "medium") -> "ClassificationResult":
        """Build the FR-05 fallback. urgency defaults to 'medium' — a neutral
        floor when we couldn't classify. The router treats any 'unknown' as
        escalate regardless of urgency, so this value is informational.
        """
        return cls(
            intent="unknown",
            urgency=urgency,
            confidence=0.0,
            alternatives=[],
            reasoning="",
            error=error,
        )
