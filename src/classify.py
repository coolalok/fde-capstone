"""classify.py — assign an intent, urgency, and calibrated confidence to a ticket.

Satisfies: FR-04 (v2, classifier is fairness-blind to segment fields),
           FR-05 (graceful fallback to unknown on any failure).
Uses prompt: PR-CLASSIFY-01 (version read from the file's frontmatter at import).
Writes:      one row to the decision log per call (feeds A8 reconciliation).

The classifier is a pure function of `(channel, subject, body, seed)`. It does
NOT see customer_tier, customer_region, customer_name, or language_fluency —
per FR-04 v2 (fairness). Tier-aware policy lives in src/route.py.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

from src.config import (
    MODEL_MAX_RETRIES,
    MODEL_NAME,
    MODEL_TIMEOUT_SECONDS,
    OPENROUTER_API_KEY,
    require_key,
)
from src.logging_store import log_decision
from src.metrics import MODEL_CALL_FAILURES
from src.prompt_loader import load_prompt
from src.schema import Alternative, ClassificationResult, Ticket

logger = logging.getLogger(__name__)

# Load the prompt at import so the version is fixed for the process lifetime.
_PROMPT = load_prompt("PR-CLASSIFY-01")
_PROMPT_VERSION = f"PR-CLASSIFY-01@{_PROMPT.version}"

# Closed set of 22 known intent codes plus the 'unknown' fallback.
# Source: data/development_tickets.json labels.intent Counter (see
# docs/intent_classes.md v1.2, Sources & provenance table).
KNOWN_INTENTS: frozenset[str] = frozenset(
    {
        "account_access",
        "api_key_issue",
        "api_usage_question",
        "authentication_failure",
        "billing_query",
        "compliance_request",
        "configuration_help",
        "data_export",
        "data_residency",
        "database_issue",
        "deployment_failure",
        "feature_request",
        "integration_help",
        "onboarding",
        "performance_degradation",
        "quota_or_overage",
        "rate_limit",
        "rollback_request",
        "security_incident",
        "sso_configuration",
        "unclear_request",
        "webhook_issue",
        "unknown",
    }
)
VALID_URGENCIES: frozenset[str] = frozenset({"high", "medium", "low"})


# A pluggable model-call signature so tests can inject a stub without any
# network access. Production wires _openrouter_call in.
ModelCall = Callable[[str, str, int], str]
"""(system_prompt, user_prompt, seed) -> raw model response as a string."""


def _openrouter_call(system: str, user: str, seed: int = 0) -> str:
    """Call OpenRouter via the OpenAI SDK. Raises on any I/O or auth failure.

    The caller catches whatever this raises and converts it into the FR-05
    unknown-fallback path.
    """
    from openai import OpenAI  # imported lazily so unit tests don't need the pkg

    require_key()
    # Bounded on purpose: the SDK default is a 600s read timeout with 2
    # retries, so one unresponsive call can occupy ~30 minutes and stall an
    # unattended run (A9). See MODEL_TIMEOUT_SECONDS in src/config.py.
    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        seed=seed,
        response_format={"type": "json_object"},
    )
    return completion.choices[0].message.content or ""


def classify(
    ticket: Ticket,
    seed: int = 0,
    call_model: Optional[ModelCall] = None,
) -> ClassificationResult:
    """Classify a ticket. See FR-04 and FR-05.

    Args:
        ticket: the normalised Ticket produced by ingest.
        seed: deterministic seed for the model call (default 0).
        call_model: optional injectable model-call function; defaults to
            _openrouter_call. Tests pass a stub; production leaves it None.

    Returns:
        A ClassificationResult. On any failure (network error, non-JSON
        output, schema violation, out-of-range confidence, unknown intent
        code), returns an unknown-fallback with ``error`` populated.
        Never raises.
    """
    caller = call_model or _openrouter_call

    raw: Optional[str] = None
    try:
        # FR-04 v2: only channel/subject/body reach the model. Segment fields
        # (customer_tier, customer_region, customer_name, language_fluency)
        # deliberately never appear in the user prompt. Rendering sits inside
        # the try so a template fault falls back rather than escaping A11.
        user_prompt = _PROMPT.render_user(
            channel=ticket.channel,
            subject=ticket.subject,
            body=ticket.body,
        )
        raw = caller(_PROMPT.system, user_prompt, seed)
        result = _parse_response(raw)
    except Exception as exc:  # broad on purpose — FR-05 / A11
        MODEL_CALL_FAILURES.labels(
            stage="classification", error_type=type(exc).__name__
        ).inc()
        logger.warning(
            "classify.failure",
            extra={
                "ticket_id": ticket.ticket_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
                # The model answered but we could not use it: keep the text.
                # Without this the evidence is gone and a model that starts
                # emitting prose instead of JSON looks like a network fault.
                "raw_response_head": (raw[:500] if raw is not None else None),
            },
        )
        result = ClassificationResult.unknown_fallback(
            error=f"{type(exc).__name__}: {exc}"
        )

    decision_id = log_decision(
        ticket_id=ticket.ticket_id,
        stage="classification",
        prediction=result.intent,
        confidence=result.confidence,
        alternatives=[[a.intent, a.confidence] for a in result.alternatives],
        prompt_version=_PROMPT_VERSION,
        requirement_ids=["FR-04", "FR-05"],
        model_name=MODEL_NAME,
        action_taken="classified" if result.error is None else "fallback",
        reason=(
            result.error
            if result.error is not None
            else f"intent={result.intent} urgency={result.urgency}"
        ),
        input_summary=(
            f"channel={ticket.channel} "
            f"subject_len={len(ticket.subject)} body_len={len(ticket.body)}"
        ),
    )
    if decision_id is None:
        # The classification happened but was not recorded, so FR-20 is unmet
        # for this ticket. log_decision has already logged the cause and bumped
        # the failure counter; our job is to make the gap visible downstream so
        # the router escalates instead of auto-responding (see D-06, EV-M5).
        result.decision_logged = False

    return result


def _parse_response(raw: str) -> ClassificationResult:
    """Parse and validate the model's JSON output. Raises on any invalidity.

    The classifier caller catches the raise and converts it to the FR-05
    unknown-fallback. Keeping the raises here (rather than returning a bad
    result silently) makes the failure inspectable in tests and via the
    decision log's `reason` column.
    """
    # Some model gateways wrap JSON in ```json ... ``` fences even when we
    # asked for pure JSON. Strip them defensively.
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    stripped = stripped.strip()
    if not stripped:
        raise ValueError("empty response from model")

    data = json.loads(stripped)  # ValueError on malformed JSON

    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON must be an object, got {type(data).__name__}")

    intent = data.get("intent")
    urgency = data.get("urgency")
    confidence = data.get("confidence")
    alternatives_raw = data.get("alternatives", [])
    reasoning = data.get("reasoning", "")

    if intent not in KNOWN_INTENTS:
        raise ValueError(f"unknown intent code: {intent!r}")
    if urgency not in VALID_URGENCIES:
        raise ValueError(f"invalid urgency: {urgency!r}")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError(f"confidence not numeric: {type(confidence).__name__}")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence out of range: {confidence}")
    if not isinstance(alternatives_raw, list):
        raise ValueError("alternatives is not a list")

    alternatives: list[Alternative] = []
    for i, alt in enumerate(alternatives_raw):
        if not isinstance(alt, dict):
            raise ValueError(f"alternative {i} is not a JSON object")
        alt_intent = alt.get("intent")
        alt_conf = alt.get("confidence")
        if alt_intent not in KNOWN_INTENTS:
            raise ValueError(f"alternative {i} has unknown intent code: {alt_intent!r}")
        if not isinstance(alt_conf, (int, float)) or isinstance(alt_conf, bool):
            raise ValueError(f"alternative {i} confidence not numeric")
        alt_conf = float(alt_conf)
        if not 0.0 <= alt_conf <= 1.0:
            raise ValueError(f"alternative {i} confidence out of range: {alt_conf}")
        alternatives.append(Alternative(intent=alt_intent, confidence=alt_conf))

    # Per PR-CLASSIFY-01: alternatives should be non-empty when confidence < 0.9.
    # We log this as a soft observation rather than a hard failure — the
    # classification is still usable, just missing the calibration signal.
    if confidence < 0.9 and not alternatives:
        logger.info(
            "classify.no_alternatives_below_09",
            extra={"confidence": confidence, "intent": intent},
        )

    if not isinstance(reasoning, str):
        reasoning = ""

    return ClassificationResult(
        intent=intent,
        urgency=urgency,
        confidence=confidence,
        alternatives=alternatives,
        reasoning=reasoning,
        error=None,
    )
