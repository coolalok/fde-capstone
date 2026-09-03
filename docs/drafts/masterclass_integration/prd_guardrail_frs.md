# PRD Stage 2 — new §Guardrails FR block

Paste under Table 4 (Functional Requirements) — Guardrails section. Bump the FR numbering to fit the next available slot; the placeholders below assume FR-GUARD-01..04 sit adjacent to existing guardrail FRs.

---

**FR-GUARD-01 — Input length and emptiness.**
The system SHALL reject empty questions and questions exceeding `MAX_QUESTION_CHARS` (default 2000) before invoking retrieval, returning a `GuardrailResult(allowed=False, reason, flags=["empty"|"too_long"])`.
*Trace:* EV-RAGD-GUARD (RAG_demo `backend/guardrails.py` lines 62-73), A7.

**FR-GUARD-02 — Prompt-injection heuristics.**
The system SHALL reject inputs matching the following case-insensitive regex patterns before invoking retrieval, returning `GuardrailResult(allowed=False, flags=["possible_prompt_injection"])`:

- `ignore (all|any|the)?\s*(previous|prior|above)\s*(instructions|prompts?)`
- `disregard (all|any|the)?\s*(previous|prior|above)\s*(instructions|prompts?)`
- `you are now`
- `system prompt`
- `reveal your (instructions|prompt|system message)`
- `act as (?!a helpful)`
- `jailbreak`
- `do anything now`
- `\bDAN\b`

Note: this is a heuristic layer, not a substitute for a classifier. Every adversarial input that bypasses these patterns during evaluation SHALL be added to the adversarial regression suite (per EV-MC4-EVAL, Masterclass 4 slide 6 "Adversarial suite").
*Trace:* EV-RAGD-INJ, EV-MC4-EVAL, A7.

**FR-GUARD-03 — Output PII redaction.**
The system SHALL redact matches of the following patterns from generated answers before returning them, replacing each match with `[REDACTED_<LABEL>]` and flagging each hit as `pii_redacted:<label>`:

- `email:  [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- `phone:  \b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b`
- `ssn:    \b\d{3}-\d{2}-\d{4}\b`
- `credit_card: \b(?:\d[ -]*?){13,16}\b`

*Trace:* EV-RAGD-PII (RAG_demo `backend/guardrails.py` lines 45-50), Governance Framework §PII, A7.

**FR-GUARD-04 — Retrieval-confidence hard block.**
If the top retrieved chunk's relevance score is below `MIN_RELEVANCE_SCORE` (per D-05a), the system SHALL withhold generation, log `route_taken="insufficient_context"`, and return `GuardrailResult(allowed=False, flags=["low_retrieval_confidence"])`. This check runs independent of the router's routing decision (defense in depth).
*Trace:* EV-RAGD-CONF, EV-MC4-SAFETY, D-05a, A7.
