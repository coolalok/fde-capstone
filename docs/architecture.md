# Architecture

*The system architecture for CloudServe Draft. Where the PRD (`workbooks/Stage_2_PRD_Template.docx`) says what the system must do, this document says how the pieces fit together. Every design choice below has an ADR file in `docs/adr/` that explains what else was considered and what would make us change our minds.*

## The high-level shape

Six components, one after the other, with three cross-cutting concerns that touch several of them. The overall pattern is called a **Router** agent: the classifier reads the ticket and hands it off to one of three outcomes — `auto_respond`, `escalate`, or `block`. On the reply-drafting step, the system also runs a self-check to catch any claim in the draft that isn't supported by a retrieved help article (that's the Self-RAG groundedness check — see ADR D-06). If the self-check fails once, one retry. If it still fails, the ticket escalates.

```
INGEST → CLASSIFY → RETRIEVE → ROUTE → GENERATE → VALIDATE
                     |           |         |          |
                     └─ decision log · metrics · guardrails ─┘
```

## Design decisions at a glance

Every non-obvious design choice gets a row here. Read the linked ADR for what else we considered, why we picked what we picked, and what would make us change our minds later.

| ID   | Decision                       | Options we considered                                          | What we picked                                   | Why (one sentence)                                                                                              | Date       |
|------|--------------------------------|----------------------------------------------------------------|--------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|------------|
| [D-01](adr/D-01-model-provider.md)  | AI model provider           | OpenRouter free tier · Groq free tier · Local Ollama          | OpenRouter (Llama 3.1 8B)                        | Setup Guide default; broadest model catalog on a single API key; nothing to install on the assessment machine.  | 2026-08-30 |
| [D-02](adr/D-02-embedding-model.md) | Search-embedding model      | `all-MiniLM-L6-v2` · `BAAI/bge-small-en-v1.5` · TF-IDF fallback | `all-MiniLM-L6-v2` (verified 2026-08-31)          | Verified in B-07 against 357 dev tickets — 91.0% top-3 hit rate, within 3 points of the TF-IDF baseline, better on non-fluent English (fairness win). See `workbooks/d02_findings.md`. | 2026-08-30; verified 2026-08-31 |
| [D-03](adr/D-03-decision-log-store.md) | Where the decision log lives | SQLite · PostgreSQL · JSONL                                 | SQLite at `storage/decisions.db`                  | No database service to run; standard library only; reconciliation is a single SELECT; PostgreSQL would be extra setup for no benefit at this scale. | 2026-08-30 |
| D-04 | How articles are split into chunks | Fixed 800 chars, 120 overlap · Section-aware, 1500 cap · Sentence-boundary | *Provisionally fixed 800/120 — final ADR is backlog item B-08* | Q3 pilot: fixed 800/120 gave 93.6% top-3, section-aware gave 92.4%. Final ADR can now be written now that B-07 has cleared the dense-retrieval measurement. | (B-08, this week) |
| [D-05](adr/D-05-confidence-threshold.md) | Confidence threshold above which the system auto-replies | 0.80 fixed · 0.85 · 0.70 · Set by measurement | Set by measurement (data-driven sweep); provisional value 0.80 until B-16 | Project Brief mandates that this be set from data; the precision-first constraint (≥0.95) comes from EV-M3 (Marcus: "I would rather it said nothing than said something wrong"). | 2026-08-30 |
| [D-06](adr/D-06-agent-architecture-pattern.md) | Overall agent pattern | Router · ReAct · Plan-and-Execute · Self-RAG · Hybrid | Router with an inline Self-RAG self-check on the draft; retry cap 1 | Q3 pilot showed search is essentially a solved problem on this corpus; the engineering value shifts to the draft-and-safety-check layer sitting on top. | 2026-08-30 |

D-04 gets its own ADR file this week (backlog item B-08). Now that the dense-retrieval measurement is in, the chunking decision can be finalised on the same evidence base.

## The six components — what each one does

### 1. Ingest — FR-01, FR-02, FR-03
- **What it does:** takes the raw ticket from any of the four channels (email, chat, docs_comment, forum) and turns it into one internal shape the rest of the pipeline can work with.
- **Inputs:** the raw ticket record.
- **Outputs:** a normalised `Ticket` object. Keeps `original_body`, `channel`, `received_at`, and all the customer-segment fields.
- **Edge cases it handles:** empty subject (every chat ticket has this by design — 155 of 155 in the dev set, per EV-DATA-11); unusual characters; empty body (unseen in the dev data but possible in the hidden test set). If anything is wrong, the ingest step adds an entry to `Ticket.warnings` rather than throwing an exception.

### 2. Classify — FR-04, FR-05
- **What it does:** reads the ticket and returns three things — the ticket type (one of 22), how urgent it is, and how confident the classifier is in its answer.
- **Outputs:** a `ClassificationResult` object with `intent`, `urgency`, `confidence` (a number between 0 and 1), and `alternatives` (up to two other plausible ticket types).
- **The 22 ticket types:** listed in `docs/intent_classes.md`.
- **What the classifier deliberately doesn't see:** `customer_tier`, `customer_region`, `customer_name`, `language_fluency`. This is a fairness decision — see `prompts/build/PR-CLASSIFY-01.md`, "What the classifier sees, and what it does NOT" section. Tier-aware policy lives in the router, not the classifier.
- **What happens if the AI model fails:** the classifier returns `intent='unknown'`, `confidence=0.0` and an `error` field describing what went wrong. It never lets an exception surface (FR-05).

### 3. Retrieve — FR-06, FR-07, FR-08
- **What it does:** takes a ticket body, searches the 29 help articles, and returns the top matching passages with their scores.
- **Design settings:** chunks of 800 characters with 120-character overlap (D-04, provisional), embeddings from `all-MiniLM-L6-v2` (D-02, verified 2026-08-31).
- **When search finds nothing:** if no passage scores above the `RETRIEVAL_THRESHOLD` set in the config, the retriever returns an empty list. Downstream, that means the router will escalate the ticket to a human.

### 4. Route — FR-09, FR-10, FR-11, FR-12
- **What it does:** looks at the classifier's confidence, the retrieval result, and the guardrail outcomes, then decides one of three things — `auto_respond`, `escalate`, or `block`.
- **Deterministic:** the same input always produces the same decision and the same reason. D-06 keeps this true by using `temperature=0.0` on the AI model calls.
- **On escalate:** the router passes along the retrieved passages, the classifier's top three alternatives, any draft the system produced, and tier 1's flag of what wasn't clear. That closes the missing-context loop Daniel complained about in the interviews (EV-D1).

### 5. Generate — FR-13, FR-14, FR-15
- **What it does:** takes the ticket and the retrieved passages, and writes a reply that cites its sources. Returns JSON with `answer`, `citations[]`, `confidence`, and an `unknown` flag.
- **Safety:** the ticket text is wrapped in markers (`<<TICKET_START>>` / `<<TICKET_END>>`); any instructions inside those markers are ignored, per FR-15.
- **Self-check (D-06):** once the draft is written, a critic step reads it against the retrieved passages and checks that every factual claim has a supporting passage. If any claim isn't supported, one retry, with the failed claims flagged. If it still isn't supported after the retry, the grounding guardrail (FR-17) blocks the reply and the ticket escalates.

### 6. Validate (guardrails) — FR-15 through FR-19
Five safety checks. All of them block, never just warn.

- **PII guardrail (FR-16):** blocks replies containing emails, API keys, phone numbers, account numbers, or other customers' names.
- **Grounding guardrail (FR-17):** every factual claim in the reply must have a supporting passage in the retrieved articles.
- **Instruction integrity (FR-18):** blocks replies where the ticket text managed to redirect the system.
- **Tone and scope (implicit):** blocks commitments about refunds, timelines, or the product roadmap.
- **Confidence floor (FR-19):** overrides auto-respond when the confidence is missing or below the threshold.

A blocked reply routes to escalate. The reason it was blocked gets recorded in the decision log.

## Cross-cutting concerns

### Decision log — FR-20
SQLite database at `storage/decisions.db` (D-03). The schema matches the minimum record required by the Governance Framework. Every decision writes one row before the reply is sent. At the end of a harness run, a reconciliation query counts `decisions_by_ticket_id` against `tickets_processed`. Any gap fails acceptance criterion A8.

### Metrics — FR-22
Prometheus counters and histograms exposed at `:8001/metrics`. What we track: tickets by outcome, response latency, guardrail activations by type, and the distribution of confidence scores (so we can watch whether the classifier's confidence is calibrated — 90% should mean right 90% of the time).

### Guardrails
See section 6 above. Each guardrail is a `Guardrail` class with one method — `.check(response, context) → GuardrailResult{passed, reason, blocking}`. Every guardrail in this project blocks (per FR-16 through FR-19); none are warn-only.

## Layers

- **Application** — the FastAPI service (`src/api.py`) and the evaluation harness command-line tool (`evaluation/harness.py`).
- **Domain** — the six components (`src/ingest.py`, `classify.py`, `retrieve.py`, `route.py`, `generate.py`, `guardrails.py`).
- **Persistence** — the SQLite decision log, the Chroma vector store, and the Prometheus metrics endpoint.

## What's still pending

- **D-04 (chunking):** provisionally fixed 800/120; the final ADR is backlog item B-08 this week, now that dense-retrieval measurement is in.
- **D-05b:** the confidence-threshold sweep result, backlog item B-16 (Friday).
- **PR-EVAL-JUDGE-01:** the three-dimensional RAG rubric prompt for the evaluation harness (backlog item B-17, Week 3).

## Changelog

- 2026-08-30 — first version, six components + decision table.
- 2026-08-31 — updated the D-02 decision-table row to reflect the measured verdict from backlog item B-07 (91.0% top-3 hit rate, within 3 points of the TF-IDF baseline, better on non-fluent English). Added the "verified" date to the D-02 row. Added a note to the Classify component describing what the classifier deliberately doesn't see (fairness decision, see PR-CLASSIFY-01). Removed `docs/intent_classes.md` from the pending list (it's now written — see the file). Updated D-04's row to note that B-07 has cleared the way for the final ADR (backlog item B-08). Rewrote the document in plainer language throughout; all requirement IDs, ADR IDs, file paths, and numeric claims preserved.
