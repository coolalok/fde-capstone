---
name: capstone-component-impl
description: Implement or extend one of the eight src/ modules for Alok's FDE Capstone (ingest, classify, retrieve, route, generate, guardrails, logging_store, api). Use when writing production code for the CloudServe support automation system. Assumes capstone-conventions is loaded.
---

# Capstone Component Implementation

Eight components in `src/`. Each has a narrow contract, hooks into the decision log, and degrades gracefully. Nothing here is where the interesting research goes — the interesting research is in the prompts and the evaluation. Code is where consistency and boring correctness live.

## The invariants — every component obeys these

1. **Type-hinted.** Every public function has full type hints. `mypy --strict src/` should pass eventually (not blocking, but aim for it).
2. **Config from env, not literals.** Every threshold, path, model name, timeout comes from `os.environ` via a small `src/config.py` loader. Literals in code are an ADR-worthy exception.
3. **Prompts by ID, not inline.** See `capstone-prompt-writer`. No f-strings that build system prompts.
4. **Decision log hook.** Every component that takes an autonomous decision writes one record via `logging_store.log_decision(...)` before returning. Reconciling the log against tickets processed is A8.
5. **Structured logging.** Use `structlog` or `python-json-logger` — never bare `print()` in production code. Log level from env.
6. **Failure policy per A11.** No component raises out of the pipeline. Failure is a returned value with `error` set, so the router / harness can choose to escalate rather than crash.
7. **Deterministic where possible.** Any component that uses randomness accepts a `seed` argument. Same input + same seed → identical output (A5).
8. **No credentials in code, ever.** Keys come from `.env`. A repo scan for keys is part of grading.

## Standard module shape

```python
"""<component>.py — <one-sentence purpose>.

Satisfies: FR-<nn>, FR-<mm>, NFR-<kk>
Prompts:   PR-<COMPONENT>-<nn>
"""

from __future__ import annotations

import structlog
from typing import Optional

from src.config import settings
from src.logging_store import log_decision
from src.schema import Ticket, ClassificationResult  # pydantic models

logger = structlog.get_logger(__name__)


def classify(ticket: Ticket, seed: int = 0) -> ClassificationResult:
    """Classify a ticket's intent and urgency.

    Satisfies FR-04, FR-05. Uses PR-CLASSIFY-01.

    Returns a ClassificationResult with:
      - intent: one of the 22 codes plus 'unknown'
      - urgency: high | medium | low
      - confidence: float in [0, 1]
      - alternatives: list of (intent, confidence) tuples
      - error: None on success, str on failure (never raises)
    """
    try:
        result = _call_model(ticket, seed=seed)
    except Exception as e:  # broad, on purpose — A11
        logger.warning("classify.failure", ticket_id=ticket.ticket_id, error=str(e))
        result = ClassificationResult.unknown_fallback(error=str(e))

    log_decision(
        ticket_id=ticket.ticket_id,
        stage="classification",
        prediction=result.intent,
        confidence=result.confidence,
        alternatives=[(a.intent, a.confidence) for a in result.alternatives],
        prompt_version="PR-CLASSIFY-01 v1.2",
        requirement_ids=["FR-04", "FR-05"],
        action_taken="classified" if result.error is None else "fallback",
        reason=result.error or "ok",
    )
    return result
```

## Per-component pointers

### ingest.py (FR-01 → FR-03)
- One `normalise(raw: dict) -> Ticket` function per channel, plus a `normalise_any(raw)` dispatcher.
- Preserve raw text under `Ticket.original_body`; expose cleaned text as `Ticket.body`.
- Empty body / missing subject / unusual chars → return the `Ticket` with the fields populated as best possible, plus `Ticket.warnings: list[str]`. Never raise.

### classify.py (FR-04, FR-05)
- Uses `PR-CLASSIFY-01`.
- Returns `ClassificationResult` with `alternatives`, not just the winner. Alternatives feed the calibration check in evaluation.
- Fallback on failure: `intent="unknown"`, `confidence=0.0`, `error=<str>`. Never a partial guess.

### retrieve.py (FR-06 → FR-08)
- One-time index build in `index_docs.py`, not on every retrieve.
- `retrieve(query, top_k=5, threshold=<from env>) -> list[Passage]`. Return empty list, not `None`, when nothing crosses threshold. Empty is a valid answer.
- Every `Passage` carries `doc_id`, `score`, `text`, `title`. Callers cite by `doc_id`.

### route.py (FR-09, FR-10)
- Pure function of `(classification, retrieval_result, ticket)`. No side effects except the decision log.
- Deterministic: `Route.decision in {"auto_respond", "escalate", "block"}` with a `reason: str` field written for a support manager to read.
- Escalate when: `must_not_auto_respond=True` (from labels), confidence < threshold, retrieval returned empty, or a guardrail blocked upstream.

### generate.py (FR-11, FR-12)
- Uses `PR-GENERATE-01` (has answer) or `PR-GENERATE-02` (retrieval empty / low confidence).
- Output is JSON: `{"answer": str, "citations": list[str], "confidence": float, "unknown": bool}`.
- Citations must be a subset of the `doc_id`s in the retrieval result. Enforce this after generation, before returning.

### guardrails.py (FR-13 → FR-17)
- Every guardrail is a `Guardrail` class with `.check(response, context) -> GuardrailResult`.
- `GuardrailResult` has `passed: bool`, `reason: str`, `blocking: bool`. **All guardrails in this project are blocking.**
- `run_all(response, context) -> list[GuardrailResult]` runs every guardrail. If any `blocking=True` and `passed=False`, the response is blocked and the ticket escalates with the reasons attached.

### logging_store.py (FR-18)
- SQLite table matching the pack's decision-log schema: `decision_id, timestamp, ticket_id, stage, input_summary, model, prediction, confidence, alternatives (JSON), sources_used (JSON), threshold_applied, action_taken, reason, guardrail_results (JSON), prompt_version, requirement_ids (JSON)`.
- `log_decision(**kwargs)` is a thin wrapper. Every field is required except where the schema allows null; missing required fields are a programming error and should raise (this is not user-facing A11 territory).
- Add a `reconcile(ticket_ids: list[str]) -> ReconciliationReport` helper — it's what the harness calls at the end to satisfy A8.

### api.py (FR-19, FR-20)
- FastAPI app with one main endpoint: `POST /ticket` → accepts a ticket JSON, returns a response JSON.
- Prometheus metrics exposed at `/metrics`.
- Health check at `/healthz` that verifies model provider reachable, Chroma reachable, SQLite writable. Returns detailed status.

## Anti-patterns — do not do these

- **Wrapping the whole pipeline in one giant try/except.** Each component handles its own failures. The harness only catches the surprise ones.
- **Silently returning a default when the model fails.** Log the failure to the decision log with `action_taken="fallback"` and `reason=<error>`.
- **Reading the ticket labels during production.** Labels are for evaluation only. Production code sees `channel`, `subject`, `body`, timestamps, customer fields. Confusing this trains the system on ground truth it won't have at inference.
- **Passing prompts as string literals into function args.** Load by ID from `prompts/`.
- **Writing tests inside the src file.** They live in `tests/`.

## What to hand back

When implementing a component:

1. Write the module in `src/<component>.py` following the shape above.
2. Add pydantic models for its inputs/outputs to `src/schema.py` if they don't exist.
3. List the FRs it satisfies and confirm each links back to at least one EV.
4. Call out any decision worth an ADR (threshold values, model choice, chunking strategy).
5. Stub the pytest file at `tests/test_<component>.py` with the three cases: happy, adversarial, degraded — the actual test bodies go through capstone-test-writer.
