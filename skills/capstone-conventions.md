---
name: capstone-conventions
description: Load the shared conventions for Alok's FDE Capstone project (CloudServe support automation). Use whenever starting or resuming any capstone task — writing requirements, prompts, code, tests, ADRs, docs, or evaluation. Names the ID space, file paths, traceability rules, and the cost-nothing constraint that keep every session on-model.
---

# FDE Capstone — Conventions

The Forward Deployed AI Engineering capstone for CloudServe Solutions (fictional client). Individual project. Deadline 13 September 2026, 23:59.

Load this at the top of every capstone session before other capstone skills. The other five capstone skills assume these are in play.

## The one-line thesis

The client asked for a chatbot. The job is to fix the support function. Every deliverable is judged against whether it addresses the real problem, not the requested mechanism.

## Project location

Local repo: `/Users/alokkulkarni/Documents/Claude/Projects/fde-capstone/`
Project overview doc: `claude/capstone_overview.md` in the FDE Capstone project.

Read `workbooks/discovery_notes.md` first if you haven't seen this project's evidence.

## Layout

```
src/            ingest, classify, retrieve, route, generate, guardrails, logging_store, api, index_docs
prompts/        build/  evaluation/  README.md (register)
tests/          pytest suite
evaluation/     harness.py  results/
docs/           architecture.md + reference docx from the pack
data/           4 JSON files (documentation, dev_tickets, validation_tickets, ground_truth_responses)
workbooks/      5 stage workbooks + Effort_Log.docx + discovery_notes.md
storage/        runtime (gitignored)
.github/workflows/ci.yml
```

## The ID space — used across all artefacts

| Prefix | What it identifies | Where it lives |
|--------|---------------------|----------------|
| `EV-<initial><n>` | Evidence from a stakeholder or from ticket data | `workbooks/discovery_notes.md`, Stage 1 workbook |
| `FR-<nn>` | Functional requirement | Stage 2 PRD |
| `NFR-<nn>` | Non-functional requirement | Stage 2 PRD |
| `PR-<COMPONENT>-<nn>` | Prompt (e.g. `PR-CLASSIFY-01`) | `prompts/` + register |
| `D-<nn>` | Architecture / design decision (ADR) | `docs/architecture.md` decision table |
| `R-<nn>` | Risk register entry | Governance workbook |
| `DL-<uuid>` | Runtime decision log entry | `storage/decisions.db` |
| `T-<component>-<nn>` | Test case | `tests/` |
| `A<n>` | Acceptance criterion (A1–A12) | Build Specification |

## Traceability rules (this is where marks live)

- Every **FR** references at least one **EV** in its `Trace:` line.
- Every **NFR** references at least one **EV** or a Build Spec criterion (`A<n>`).
- Every **prompt** references at least one **FR** in its `Requirement:` line.
- Every **component** (`src/*.py`) declares which **FR**s it satisfies in its module docstring.
- Every **ADR** names the **FR**s it constrains and the **PR**s or `src/*` files it affects.
- Every **runtime decision log entry** carries the `prompt_version` and `requirement_ids` fields.
- Every **risk (R-)** names its mitigation as an FR, an ADR, or a guardrail.

If a chain breaks anywhere, the requirement isn't done.

## Twelve acceptance criteria (short form — keep in mind for every design decision)

- **A1** Runs from a clean checkout via README.
- **A2** All four channels ingested + normalised.
- **A3** Every ticket classified with numeric confidence [0,1].
- **A4** Retrieval returns identifiable source passages.
- **A5** Routing deterministic. Same input → same decision.
- **A6** Citations resolve to actually retrieved passages.
- **A7** At least one guardrail can BLOCK (not warn).
- **A8** Every decision written to persistent log; reconciles vs tickets processed.
- **A9** Full evaluation set processed unattended in one command. Harness takes `--input --output` paths.
- **A10** That run produces a metrics report without further manual work.
- **A11** Degrades gracefully on outage / rate limit / retrieval miss / malformed input.
- **A12** Tests pass with one documented command.

## The cost-nothing rule

Every dependency and every service is free / free-tier. Never suggest a paid service; if you find yourself needing one, that's a design smell — cache, backoff, or rework instead. Stack:

- Python 3.10+, venv
- LangChain 0.1 + LangGraph, Chroma, sentence-transformers (`all-MiniLM-L6-v2`)
- OpenRouter free tier, model `meta-llama/llama-3.1-8b-instruct`
- FastAPI + uvicorn
- SQLite for decision log, no PostgreSQL unless justified
- Prometheus + Grafana for metrics
- GitHub Actions for CI

## The three things easiest to lose marks on

1. **Traceability broken** — a component that satisfies no FR, a prompt with no FR link, a decision log entry without `prompt_version`. Auto-fail on audit.
2. **Guardrail that doesn't block** — logs a warning instead of refusing. A7 fail.
3. **Harness with hardcoded input path** — fails on the hidden 120-ticket set. A9 fail.

## Style

- No emojis anywhere in code, docs, or workbooks unless the pack itself uses them (it doesn't).
- Requirements written in verifiable language: "the system SHALL", never "the system should try to".
- Numbers reported with their uncertainty. Never quote a metric without stating what data it came from.
- The word "chatbot" appears only when referring to what the client asked for. What we're building is a "support automation system".

## When resuming a session

1. Read `claude/capstone_overview.md` in the project.
2. Read `workbooks/discovery_notes.md` in the local repo.
3. Check the Effort Log for what happened last.
4. Ask the user what they want to work on rather than assuming.
