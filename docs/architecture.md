# Architecture

*This is CloudServe Draft's system architecture. It is derived from the PRD (`workbooks/Stage_2_PRD_Template.docx`) and refined by the ADRs in `docs/adr/`. Every design decision here has an ADR file explaining the alternatives, the choice, and the revisit trigger.*

## High-level

Six components in sequence, three cross-cutting concerns. The system implements a **Router** agent pattern (classifier decides `auto_respond` / `escalate` / `block`) with **Self-RAG's groundedness check inline** on the generate stage (retry cap 1). See **D-06** for the pattern decision.

```
INGEST → CLASSIFY → RETRIEVE → ROUTE → GENERATE → VALIDATE
                     |           |         |          |
                     └─ decision log · metrics · guardrails ─┘
```

## Decision table

Every non-obvious design choice gets a row. Read the linked ADR for context, options considered, and revisit trigger.

| ID   | Decision                       | Options considered                                                | Chosen                                            | Rationale (one sentence)                                                                                        | Date       |
|------|--------------------------------|--------------------------------------------------------------------|---------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|------------|
| [D-01](adr/D-01-model-provider.md)  | Model provider              | OpenRouter free tier · Groq free tier · Local Ollama              | OpenRouter (Llama 3.1 8B)                          | Setup Guide default; broadest model catalog on a single API key; zero infrastructure on the assessment machine.  | 2026-08-30 |
| [D-02](adr/D-02-embedding-model.md) | Embedding model             | `all-MiniLM-L6-v2` · `BAAI/bge-small-en-v1.5` · TF-IDF fallback   | `all-MiniLM-L6-v2`                                 | Setup Guide default; Q3 pilot's TF-IDF baseline at 93.6% top-3 is the bar the dense embedder needs to meet.      | 2026-08-30 |
| [D-03](adr/D-03-decision-log-store.md) | Decision log store         | SQLite · PostgreSQL · JSONL                                       | SQLite at `storage/decisions.db`                    | No service to run, standard-library, reconciliation is one SELECT; PostgreSQL would add setup burden without benefit at this scale. | 2026-08-30 |
| D-04 | Chunking strategy              | Fixed 800/120 · Section-aware, 1500 cap · Sentence-boundary        | *Provisionally fixed_800_120* — final in Week 2   | Q3 pilot: fixed_800_120 hit@3=93.6% vs section_aware 92.4%; final ADR after dense-retrieval measurement.         | (Week 2)   |
| [D-05](adr/D-05-confidence-threshold.md) | Auto-respond confidence threshold | 0.80 fixed · 0.85 · 0.70 · Data-driven sweep                 | Data-driven sweep; provisional 0.80 for Week 1    | Project Brief mandates the threshold be set from data; precision-first constraint (≥0.95) encodes EV-M3.        | 2026-08-30 |
| [D-06](adr/D-06-agent-architecture-pattern.md) | Agent architecture pattern | Router · ReAct · Plan-and-Execute · Self-RAG · Hybrid    | Router with inline Self-RAG on generate; retry cap 1 | Q3 pilot shows retrieval is essentially solved; the engineering value shifts to grounded generation with self-correction. | 2026-08-30 |

D-04 gets its own file in Week 2 after the dense embedder is running and we can compare against TF-IDF on the same corpus.

## Components (contracts)

### 1. Ingest — FR-01, FR-02, FR-03
- **Responsibility:** normalise tickets from all four channels into one internal representation.
- **Inputs:** raw ticket payload (email, chat, docs_comment, forum).
- **Outputs:** normalised `Ticket` object; preserves `original_body`, `channel`, `received_at`, all customer segment fields.
- **Edge cases:** empty subject (155/155 chat tickets have this by design per EV-DATA-11), unusual chars, empty body (unseen in dev but possible in hidden). Populates `Ticket.warnings` list rather than raising.

### 2. Classify — FR-04, FR-05
- **Responsibility:** intent + urgency + calibrated confidence.
- **Outputs:** `ClassificationResult{intent, urgency, confidence ∈ [0,1], alternatives[]}`.
- **Intent classes:** the 22 known classes plus `unknown`. Enumerated in `docs/intent_classes.md` (to be written).
- **Fallback:** on provider failure or malformed output, returns `intent='unknown'`, `confidence=0.0`, `error=<str>`. Never raises.

### 3. Retrieve — FR-06, FR-07, FR-08
- **Responsibility:** ranked passages from the 29-article corpus with scores.
- **Design decision:** fixed 800/120 chunking (D-04, provisional), `all-MiniLM-L6-v2` embeddings (D-02).
- **Retrieval threshold:** empty list returned when no passage crosses `RETRIEVAL_THRESHOLD` env var. Downstream, this triggers escalation via the router.

### 4. Route — FR-09, FR-10, FR-11, FR-12
- **Responsibility:** deterministic decision — `auto_respond` / `escalate` / `block`.
- **Determinism:** same input → same decision + same reason (D-06 preserves this via `temperature=0.0`).
- **Escalation bundle:** on escalate, carries the retrieved passages, classifier top-3 alternatives, any draft produced, and the T1 uncertainty flag.

### 5. Generate — FR-13, FR-14, FR-15
- **Responsibility:** grounded answer with citations. JSON output: `{answer, citations[], confidence, unknown}`.
- **Safety:** ticket text delimited by markers; injection ignored per FR-15.
- **Self-RAG groundedness check (D-06):** after generation, a critic verifies every factual claim has a supporting span in the retrieved passages. If any claim is unsupported, one retry with the failed claims flagged. After the retry, if still unsupported, the guardrail (FR-17) blocks and the ticket escalates.

### 6. Validate (Guardrails) — FR-15 through FR-19
- **PII guardrail** (FR-16): blocks emails, API keys, phone numbers, account numbers, other-customer names.
- **Grounding guardrail** (FR-17): every factual claim must have a supporting span in the retrieved passages.
- **Instruction integrity** (FR-18): blocks responses where the ticket text redirected the system.
- **Tone/scope** (implicit): blocks commitments about refunds, timelines, roadmap.
- **Confidence floor** (FR-19): overrides auto-respond when confidence is missing or below threshold.

All guardrails **block, never warn**. A blocked response routes to escalate with the failure reason recorded in the decision log.

## Cross-cutting concerns

### Decision log — FR-20
SQLite at `storage/decisions.db` (D-03). Schema matches Governance Framework's minimum record. Every decision writes one row before the response is sent. Reconciliation query at end of harness run: count decisions_by_ticket_id vs tickets_processed. Any gap fails A8.

### Metrics — FR-22
Prometheus counters and histograms exposed at `:8001/metrics`. Metrics tracked: tickets by outcome, latency histogram, guardrail activations by type, confidence distribution (for calibration monitoring).

### Guardrails
See section 6 above. Each guardrail is a `Guardrail` class with `.check(response, context) → GuardrailResult{passed, reason, blocking}`. All blocking in this project (per FR-16 through FR-19).

## Layers

- **Application** — FastAPI (`src/api.py`), harness CLI (`evaluation/harness.py`)
- **Domain** — the six components (`src/ingest.py`, `classify.py`, `retrieve.py`, `route.py`, `generate.py`, `guardrails.py`)
- **Persistence** — SQLite decision log, Chroma vector store, Prometheus metrics endpoint

## Pending items

- **D-04 (chunking):** provisional fixed_800_120; final ADR Week 2 after dense-retrieval measurement.
- **D-05b:** confidence threshold sweep result, Week 2.
- **`docs/intent_classes.md`:** the closed list of 22 intents with descriptions, extracted from `data/development_tickets.json` labels.intent enum.
- **PR-EVAL-JUDGE-01:** the three-dimensional RAG rubric prompt for the evaluation harness.
