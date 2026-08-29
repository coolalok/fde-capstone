# Architecture

*Filled in during Week 1 (design decisions) and refined during Week 2 (implementation).*

## High-level

Six components in sequence, three cross-cutting concerns.

```
INGEST → CLASSIFY → RETRIEVE → ROUTE → GENERATE → VALIDATE
                     |          |         |          |
                     └────── decision log, metrics, guardrails ──────┘
```

## Components

### 1. Ingest
- **Responsibility:** normalise tickets from all four channels into one internal representation.
- **Inputs:** raw ticket payload (email, chat, docs_comment, forum).
- **Outputs:** normalised `Ticket` object with original text and channel preserved.
- **Edge cases:** missing fields, unusual characters, empty bodies.

### 2. Classify
- **Responsibility:** intent + urgency + calibrated confidence.
- **Outputs:** `{intent, urgency, confidence, alternatives[]}`.

### 3. Retrieve
- **Responsibility:** ranked passages from the docs corpus with scores.
- **Design decision:** chunk size and overlap — to be measured.

### 4. Route
- **Responsibility:** decide auto-respond vs. escalate.
- **Determinism:** same input → same decision. Threshold set from data, not hardcoded.

### 5. Generate
- **Responsibility:** grounded answer with citations, structured output.
- **Safety:** prompt injection separation between ticket text and instructions.

### 6. Validate
- **Responsibility:** guardrails that BLOCK.
- **Checks:** PII, grounding, instruction integrity, tone/scope, confidence floor.

## Cross-cutting

### Decision log
Every decision persisted with the schema in `docs/decision_log_schema.md`.

### Metrics
Prometheus counters/histograms for tickets processed, latency, guardrail activations.

### Guardrails
See §6 above.

## Layers

- **Application** — FastAPI, harness CLI
- **Domain** — the six components
- **Persistence** — SQLite decision log, Chroma vector store, metrics endpoint

## Design decisions (as they're taken)

| # | Decision | Options considered | Chosen | Rationale | Date |
|---|----------|-------------------|--------|-----------|------|
| D1 |          |                   |        |           |      |
