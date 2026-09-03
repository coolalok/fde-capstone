# Governance Framework — §Decision Log Schema update

Paste under the existing §Decision Log Schema section (Table X) after the current minimum-record listing.

---

## Extended trace schema (D-03a)

Per D-03a and EV-MC4-TRACE (Masterclass 4 slide 13), the `decisions` table additionally records the following columns. All are additive; existing rows carry NULL for these fields until migration runs.

| Column | Type | Purpose |
|---|---|---|
| `model_id` | TEXT | The model that served this turn. Per D-01, default `meta-llama/llama-3.1-8b-instruct`. |
| `model_fallback` | TEXT NULL | Populated only when the primary provider call failed and a fallback served the response. |
| `latency_p95_ms` | INTEGER NULL | Rolling p95 latency, computed at reconcile time per run. |
| `tokens_in` | INTEGER | Prompt tokens (provider count where available; local tokenizer estimate otherwise). |
| `tokens_out` | INTEGER | Completion tokens. |
| `cost_usd` | REAL | Tokens × price table. Zero for OpenRouter free tier. Auditable per Masterclass 3 "Token & Cost Monitoring" (EV-MC3-COST). |
| `guardrail_checks_passed` | INTEGER | Count of guardrail checks in this turn that returned `allowed=True`. |
| `guardrail_checks_blocked` | INTEGER | Count of guardrail checks in this turn that returned `allowed=False`. |
| `guardrail_flags_json` | TEXT | JSON array of every flag string emitted by any guardrail this turn. |
| `groundedness_score` | REAL NULL | Self-RAG faithfulness score in [0, 1]. NULL for non-generate stages. |
| `retrieval_max_score` | REAL NULL | Top-hit relevance score at retrieval time. NULL for non-retrieve stages. |
| `route_taken` | TEXT | One of `auto`, `tier1_draft`, `tier2_escalate`, `hard_escalate`, `insufficient_context`. |
| `min_relevance_score` | REAL | Value of `MIN_RELEVANCE_SCORE` (per D-05a) in effect for this turn. |
| `route_confidence_threshold` | REAL | Value of `ROUTE_CONFIDENCE_THRESHOLD` (per D-05) in effect for this turn. |

Reporting: `evaluation/report_trace_summary.py` emits the slide-13-style per-turn trace card from these columns for any given `decision_id`.

Evidence: EV-MC4-TRACE, EV-MC4-PILLARS (Observability pillar), EV-MC3-COST.
