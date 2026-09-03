# D-03a — Decision log trace schema (extends D-03)

**Status:** Provisional. Extends D-03.
**Date:** 2026-09-03
**Decider:** Alok Kulkarni
**Constrains:** NFR-observability (Stage 2 PRD), A8

> **Note 2026-09-03:** the original Constrains line also cited `FR-GUARD-04`. That reference was removed after PRD Table 9 Q7 resolved 2026-09-03 that FR-GUARD-01..04 are deferred to Week 3 candidate (see Stage 5 revision log). The substance of this ADR (the trace-schema fields for the decision log) is unaffected. The `groundedness_score` and `retrieval_max_score` fields the schema adds are still worth carrying — they are observability, independent of whether a guardrail acts on them.
**Affects:** `src/logging_store.py`, `src/api.py` trace hook, Governance Framework §Decision Log Schema

## Context

D-03 chose SQLite at `storage/decisions.db` as the decision-log store and defined a minimum record set (decision_id, prompt_version, requirement_ids, sources_used, guardrail_results, alternatives). That set is sufficient for A8 reconciliation but does not carry the fields Masterclass 4 slide 13 (EV-MC4-TRACE) presents as the professional-standard production trace shape: model identity, prompt version, latency percentile, tokens in/out, cost per interaction, guardrail check pass/block counts, groundedness score, retrieval max score.

Without these, common production questions cannot be answered from the log alone — "what did this cost?", "which prompt version served this?", "was the answer well-grounded?". The Evaluation Framework's five-pillar go-live gate (EV-MC4-PILLARS) requires all of these observable. Adding them now (Week 2) is far cheaper than retrofitting after B-21 (harness run) exposes what's missing.

## Options considered

**A. Keep the current schema. Reconstruct missing fields at reporting time.**
Rejected: reconstruction is lossy (model fallback events, guardrail flag arrays cannot be reconstructed after the fact) and defeats "the log is the single source of truth" (D-03 rationale).

**B. Additive migration: extend the existing `decisions` table with the missing columns.**
Chosen (below).

**C. Second table `decision_traces` keyed by decision_id.**
Rejected: the fields are per-decision, one-to-one. A join buys nothing except query complexity.

## Chosen

**Option B — additive column extension.**

New columns added to `decisions`:

| Column | Type | Notes |
|---|---|---|
| `model_id` | TEXT | e.g. `meta-llama/llama-3.1-8b-instruct` (per D-01) |
| `model_fallback` | TEXT NULL | populated only if primary provider call failed and fallback fired |
| `latency_p95_ms` | INTEGER NULL | rolling window computed per-run at reconcile time |
| `tokens_in` | INTEGER | prompt tokens |
| `tokens_out` | INTEGER | completion tokens |
| `cost_usd` | REAL | tokens × price table; free-tier rows carry 0.0 |
| `guardrail_checks_passed` | INTEGER | count of guardrail checks that returned `allowed=True` |
| `guardrail_checks_blocked` | INTEGER | count of guardrail checks that returned `allowed=False` |
| `guardrail_flags_json` | TEXT | JSON array of every flag string emitted this turn |
| `groundedness_score` | REAL NULL | Self-RAG check output, 0–1; NULL for non-generate stages |
| `retrieval_max_score` | REAL NULL | top hit's relevance score at retrieval time; NULL for non-retrieve stages |
| `route_taken` | TEXT | one of `auto`, `tier1_draft`, `tier2_escalate`, `hard_escalate`, `insufficient_context` |
| `min_relevance_score` | REAL | value of `MIN_RELEVANCE_SCORE` in effect (per D-05a) |
| `route_confidence_threshold` | REAL | value of `ROUTE_CONFIDENCE_THRESHOLD` in effect (per D-05) |

All additive. Existing rows get NULL for new columns via `ALTER TABLE ADD COLUMN`. Migration script `scripts/migrate_decisions_002_trace_fields.py` runs idempotently on startup (see `logging_store.init_db`).

## Rationale

- Direct mapping to EV-MC4-TRACE. Every field on slide 13 has a home.
- Additive: no existing test breaks. `test_logging_store.py`'s Bug 2 reconcile fix (run_id scoping) is unaffected because none of the new columns are involved in reconcile's WHERE clauses.
- Enables cost-per-resolved-ticket reporting for the Stage 2 PRD business success measure without a separate accounting pass.
- Enables B-21 to emit the Masterclass 4 "sample production trace" table directly from the log — good demo material.

## Consequences

- `src/logging_store.py`: extend SCHEMA, add columns to `log_decision` signature (all keyword-only, default None or 0), extend `record_turn`.
- `src/api.py`: threads model_id, tokens, latency, cost per call into `log_decision`.
- `src/guardrails.py`: returns counts + flag list per turn; the caller aggregates for the log.
- Cost table: initially all zeros for OpenRouter free tier. `src/config.py` gets `PRICE_TABLE` dict (per-provider, per-model, in/out) that stays at 0.0 for `meta-llama/llama-3.1-8b-instruct` — future models slot in without code change.
- Reporting: new `evaluation/report_trace_summary.py` emits the slide-13-style table from the log for a given run_id.

## Evidence

- EV-MC4-TRACE — Masterclass 4 slide 13 (sample production trace).
- EV-RAGD-TRACE — RAG_demo `@traceable` pattern (`backend/retrieval.py`, `backend/guardrails.py`) as a shape reference; not adopted as tracing backend.
- EV-MC4-PILLARS — Masterclass 4 slide 6, five pillars of go-live readiness (Observability).

## Follow-up

- Migration script + tests in `tests/test_logging_store_trace_schema.py`.
- Update Governance Framework §Decision Log Schema to reflect the extended set.
- Update `capstone-component-impl` skill to reference D-03a when building or extending logging code.
