---
name: capstone-conventions
description: Load the shared conventions for Alok's FDE Capstone project (CloudServe support automation). Use whenever starting or resuming any capstone task — writing requirements, prompts, code, tests, ADRs, docs, or evaluation. Names the ID space, file paths, traceability rules, evidence tag families, data fidelity discipline, and the cost-nothing constraint that keep every session on-model.
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

## Evidence tag families — external prior art

Added 2026-09-03 after Masterclass 3 / Masterclass 4 / RAG_demo audit. Beyond `EV-<initial><n>` (stakeholder / discovery evidence) and `EV-DATA-<n>` (dataset-derived), FRs / NFRs / ADRs / backlog rows MAY cite the following prior-art tag families. The traceability audit accepts these; treat them as first-class evidence.

| Family | Source | Example uses |
|--------|--------|--------------|
| `EV-MC3-<slug>` | Masterclass 3 — Agentic AI Industry Practices | `EV-MC3-CUSTOPS` (Customer Ops industry example, slide 36); `EV-MC3-DECISION` (five-step decision framework); `EV-MC3-COST` (Token & Cost Monitoring section). |
| `EV-MC4-<slug>` | Masterclass 4 — LLMOps & Production Readiness | `EV-MC4-TRACE` (slide 13 production trace fields); `EV-MC4-SAFETY` (slide 8 four-layer safety); `EV-MC4-EVAL` (slide 6 layered evaluation); `EV-MC4-PILLARS` (slide 6 five pillars). |
| `EV-RAGD-<slug>` | RAG_demo reference implementation | `EV-RAGD-INJ` (prompt-injection regex list); `EV-RAGD-PII` (PII patterns); `EV-RAGD-CONF` (retrieval-confidence hard block); `EV-RAGD-CHUNK` (tiktoken splitter config); `EV-RAGD-PROMPT` (generate prompt template); `EV-RAGD-GUARD` (GuardrailResult interface). |

When `capstone-component-impl` builds against an FR / DoD row carrying any of these tags, the skill MUST consult the cited source before generating code and align the implementation with it. Deviation from the cited source is a design decision that requires an ADR.

When `capstone-adr` writes an ADR, prior-art tags belong in the *alternatives considered* or *evidence* sections — never fabricated into the decision itself. A prior-art tag is evidence *that a pattern exists*, not evidence that our system must adopt it.

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

## Data fidelity — REQUIRED

Added after a Week 2 D1 failure: I paraphrased a DEV-0008 ticket body in a test case for `PR-CLASSIFY-01`, adding an MFA-in-body sentence that was not in the real ticket (the subject mentioned MFA; the body did not). The paraphrase read as plausible but was fabrication — exactly the shape of failure the assessor is graded on catching. User caught it.

### Rule 1 — Quote dataset content byte-for-byte

When a prompt file, test case, ADR, or PRD row quotes a specific ticket, article passage, or ground-truth response, the quoted text MUST be the verbatim string from the source file. Re-read the source before pasting. Never reconstruct from memory. Never combine two fields (e.g. subject + body) into one quoted string without labelling each field.

The check is mechanical: `python3 -c "import json; d=[t for t in json.load(open('data/development_tickets.json')) if t['ticket_id']=='DEV-0008'][0]; print(repr(d['body']))"`. If the printed string does not match what's in the artefact character-for-character, the artefact is wrong.

### Rule 2 — Mark paraphrase as paraphrase

Sometimes a shortened or hypothetical version of a ticket is genuinely useful — for a schema-shape example, for an adversarial case that isn't in the dataset (injection attempts), or in prose. Then say so explicitly:

- "**Source:** synthetic. Injection attempts are not present in the 500-ticket dev set."
- "**Paraphrase for illustration** — the real body is different; see DEV-0008 in `data/development_tickets.json` for the verbatim text."

The fabrication failure was not that a paraphrase existed — it was that a paraphrase was presented as if verbatim.

### Rule 3 — Cite the source location for every quote

Every dataset quote in a durable artefact carries its identifier: `DEV-0008`, `DOC-AUTH-001`, `data/ground_truth_responses.json → response_id GT-042`. Without the identifier, the quote cannot be verified and the artefact isn't defensible in the report.

### Rule 4 — When in doubt, read the file

If I'm not 100% sure a phrase is in the source, I re-read the source before writing the artefact — not after. "Close enough" is the shape of the failure this section exists to prevent.

## Sequencing discipline — REQUIRED

Two rules the assistant MUST follow. These were added mid-project after three failures — writing Setup Guide code before the PRD (Week 1 Wed), populating PRD Discovery evidence with pack acceptance criteria instead of EV-* tags (Week 1 Sat), running the D-02 revisit check before the sprint plan authorised it (Week 1 Sun). Each failure had the same shape: reaching for what was available instead of what was on the plan.

### Rule 1 — Never propose a task that isn't in a written plan

If the task isn't in `workbooks/Stage_4_Sprint_Plan.docx` (backlog Table 3 or a daily plan Table 4/5) OR named in a PRD Open Questions row (Table 9) with a target date matching today, don't start it. Don't offer to start it. Don't hint that it's "next available."

The correct response to a not-on-plan task is: **"That task isn't in the sprint plan. Do you want to add it, or defer until it is?"**

Exception: work the user directly asks for by name in this turn overrides the plan for this turn only, but the assistant flags it: "That's not on the plan; I'll do it now and note it in the daily check-in."

### Rule 2 — When the user asks "what's next?", the answer MUST cite the plan row

Not "the environment is warm." Not "the script is ready." Not "we just finished X, so Y is available."

The answer format is:

> "Per Stage 4 Table 4 (Week 2 daily plan), today (Mon 31 Aug) has: **B-07** (D-02 revisit check, 1h) and **B-03** (PR-CLASSIFY-01 prompt, 2h). Starting with B-07 because it unblocks B-05 and B-08."

Or, when the plan is silent:

> "Stage 4 doesn't have anything queued for today. The next unblocked backlog item is **B-14** which depends on B-12 and B-13. Do you want to slot it into today, or is there something else?"

### The trap this closes

When a tool has a lot of capability and the environment is already set up, "what could I do next?" produces an infinite list of plausible things. The AI reaches for the nearest one. The result looks like productivity but hides that no sequencing discipline exists — because if the AI is always picking the next thing, the user never has to look at the plan.

The Effort Log Table 7 reflection question captured this in Week 1: *"I under-estimate discipline overhead — the time spent making sure requirements trace to evidence, ADRs record alternatives, and sections don't drift between documents. Actual writing of an FR takes 5 minutes; the audit + trace + rewrite loop takes another 5 minutes per FR and I didn't budget for it."*

The two rules above are the specific correction to that budgeting failure.

## When resuming a session

1. Read `claude/capstone_overview.md` in the project.
2. Read `workbooks/discovery_notes.md` in the local repo.
3. Check the Effort Log for what happened last.
4. Ask the user what they want to work on rather than assuming.
