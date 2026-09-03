# Stage 4 Sprint Plan — Table 3 backlog amendments

Paste the additions into the DoD / Scope cell of each named row. Do NOT create new B-XX rows.

---

## B-07 — D-02 embedding revisit check (Mon 31 Aug)

*Status: if already closed, this becomes a Stage 5 revision-log entry instead — see `stage5_revision_log_entry.md`.*

**Add to Scope:**
> Second axis: chunking strategy. In addition to `all-MiniLM-L6-v2` vs TF-IDF baseline (EV-Q3), benchmark the current fixed 800-char / 120-overlap split (D-04 provisional) against a token-aware `RecursiveCharacterTextSplitter` (1000 tokens, 150 overlap, `tiktoken` `cl100k_base` length function, separators `["\n\n", "\n", ". ", " ", ""]`, per EV-RAGD-CHUNK). Report hit@3 for the 2×2. Result feeds D-04 final ADR at B-08.

---

## B-08 — D-04 final chunking ADR (Wed 2 Sep)

**Add to Scope:**
> D-04 alternatives-considered section MUST include tiktoken token-aware `RecursiveCharacterTextSplitter` (EV-RAGD-CHUNK) with the B-07 benchmark result as the deciding evidence. If tiktoken wins by ≥2 percentage points on hit@3, adopt it; otherwise keep 800/120 char and record why.

---

## B-11 — `src/guardrails.py` implementation

**Replace DoD with:**
> Module implements FR-GUARD-01..04 (see PRD Stage 2 §Guardrails). Public interface:
> ```python
> @dataclass
> class GuardrailResult:
>     allowed: bool
>     reason: Optional[str] = None
>     flags: List[str] = field(default_factory=list)
>     sanitized_text: Optional[str] = None
>
> def validate_input(question: str) -> GuardrailResult: ...
> def validate_output(answer: str, retrieved_context: str, max_relevance_score: float) -> GuardrailResult: ...
> ```
> Both functions emit one decision-log row per invocation (per D-03a schema). All four FRs unit-tested with ≥90% branch coverage; `tests/test_guardrails.py` already carries the contract (written 2026-09-03). Adversarial fixtures cover at least one hit per FR-GUARD-02 regex pattern and one hit per FR-GUARD-03 PII label.
> **Evidence:** EV-RAGD-GUARD, EV-RAGD-INJ, EV-RAGD-PII, EV-RAGD-CONF, EV-MC4-SAFETY, D-05a.

---

## B-15 — `src/generate.py` implementation

**Add to Scope:**
> Loads PR-GENERATE-01 v1.0.0 from `prompts/build/PR-GENERATE-01.md` via `prompt_loader`. Template ported from EV-RAGD-PROMPT. Response validated against `generate_response_v1` JSON schema (see prompt file). On abstain, sets `route_taken="insufficient_context"` upstream; on grounded answer, records `groundedness_score` in decision log (per D-03a).

---

## B-16 — Confidence threshold sweep

**Replace with 2-D sweep spec:**
> Per D-05a, sweep two thresholds:
> - `MIN_RELEVANCE_SCORE` (hard floor for FR-GUARD-04): candidate values 0.10 / 0.20 / 0.25 / 0.30 / 0.35.
> - `ROUTE_CONFIDENCE_THRESHOLD` (D-05 router boundary): candidate values 0.70 / 0.75 / 0.80 / 0.85 / 0.90.
> Constraint: `MIN_RELEVANCE_SCORE < ROUTE_CONFIDENCE_THRESHOLD`.
> Metrics per cell: (a) auto-respond precision (must be ≥ 0.95 per EV-M3), (b) FCR proxy (auto-respond recall on answerable-from-docs subset), (c) false-block rate on ground truth answerable set (measures over-blocking by the floor).
> **New (from Masterclass 4 slide 6, EV-MC4-EVAL):** add LLM-as-judge faithfulness scoring on the answer set at each cell using PR-EVAL-JUDGE-01 (or a v0 draft if PR-EVAL-JUDGE-01 lands after B-16). Chosen cell must satisfy: precision ≥ 0.95 AND faithfulness ≥ 0.90 AND false-block ≤ 0.05.
> Result recorded in D-05b (post-hoc ADR).

---

## B-19 — `src/logging_store.py` extension (or new row B-11-b if you prefer separate ticket)

*Note: B-19 originally sized for reconcile fix. Extending here to include D-03a schema migration adds ~1h.*

**Add to Scope:**
> Extend `decisions` table with the columns listed in D-03a (`model_id`, `model_fallback`, `latency_p95_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `guardrail_checks_passed`, `guardrail_checks_blocked`, `guardrail_flags_json`, `groundedness_score`, `retrieval_max_score`, `route_taken`, `min_relevance_score`, `route_confidence_threshold`). Migration script `scripts/migrate_decisions_002_trace_fields.py`, idempotent, runs from `init_db`. New tests in `tests/test_logging_store_trace_schema.py`.
