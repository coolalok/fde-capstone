---
name: capstone-adr
description: Write an architecture decision record (ADR) for Alok's FDE Capstone project. Use whenever a design decision has more than one plausible option and the choice needs to be defensible in the report or the video. Feeds the docs/architecture.md decision table and the Stage 5 revision log. Assumes capstone-conventions is loaded.
---

# Capstone ADR — Architecture Decision Records

Every non-obvious decision gets an ADR. Non-obvious means: more than one plausible option, tradeoffs, and the reason for the choice would not survive being asked "why?" six weeks from now.

The video will be marked partly on whether you can answer "why did you do it that way?" without hesitating. ADRs are how you'll still be able to.

## Where they live

Two-tier storage:

1. **`docs/architecture.md`** — the decision table. One row per ADR, always up-to-date. Skimmable in the video and report.
2. **`docs/adr/D-<nn>-<slug>.md`** — the full record. One file per ADR, immutable once accepted (edits go into a new ADR that supersedes it).

## Format — the full record

```
# D-04 — Chunk size for the documentation corpus

**Status:** Accepted
**Date:** 2026-09-03
**Decider:** Alok
**Constrains:** FR-06, FR-08
**Affects:** src/index_docs.py, src/retrieve.py, PR-RETRIEVE-01

## Context

The 29 KB articles each have a fixed internal structure (title, applies-to, symptoms,
causes, numbered resolution, notes). A single article averages ~1200 tokens. We chunk
before embedding because retrieving whole articles dilutes the passage that answers a
specific ticket. Chunk size affects retrieval hit rate on `expected_doc_ids` and answer
grounding rate downstream.

## Options considered

**A. Fixed 500-token chunks with 100-token overlap.**
Simple. Splits resolution steps arbitrarily.

**B. Fixed 800-token chunks with 120-token overlap.** (matches the Setup Guide sample)
Simple. Whole numbered resolutions usually stay together. Some symptom-resolution pairs split.

**C. Section-aware chunks: one chunk per internal section (symptoms, causes, resolution, notes), keeping the resolution as one chunk regardless of length.**
Respects article structure. Variable chunk size complicates similarity scoring.
Harder to embed.

## Chosen

**Option C** — section-aware chunking, with a hard 1500-token cap on any single chunk (splits only if a resolution exceeds it).

## Rationale

Measured retrieval hit rate on `labels.expected_doc_ids` across 100 dev tickets:
A: 0.71, B: 0.78, C: 0.86.

The gain is concentrated on multi-step deployment resolutions, where fixed chunks
routinely split step 3 from step 4 and the ticket phrases match step 3 while the answer
depends on step 4. This is exactly the case Ines described in the interviews (EV-I2 —
"my deployment keeps dying" ↔ "resolving container health check failures").

## Consequences

- Positive: retrieval accuracy up, answers more likely to be complete.
- Negative: Chroma similarity scoring on variable-length chunks less directly comparable.
- Mitigation: normalise scores by chunk length in `retrieve.py` before ranking.

## Revisit trigger

If retrieval hit rate on the validation set falls below 0.75, or if a new article type
appears that doesn't follow the six-section template, revisit. Also revisit if we
switch embedding models (chunk size sensitivity is model-dependent).

## Supersedes / superseded by

None. This is the first chunking decision.
```

## The decision table in `docs/architecture.md`

One row per ADR, in this shape. The `docs/architecture.md` skeleton in the repo already has the header.

```
| # | Decision | Options considered | Chosen | Rationale (one sentence) | Date |
|---|----------|-------------------|--------|--------------------------|------|
| D-01 | Model provider | OpenRouter free tier vs Groq free tier vs local Ollama | OpenRouter | Highest free-tier throughput on Llama 3.1 8B during pilot. | 2026-08-28 |
| D-02 | Embedding model | all-MiniLM-L6-v2 vs bge-small-en-v1.5 | all-MiniLM-L6-v2 | Setup guide default; hit rate difference on our 100-ticket pilot was within noise. | 2026-08-29 |
| D-03 | Decision log store | SQLite vs PostgreSQL | SQLite | Free, file-based, no service to run; sufficient at scale. | 2026-08-29 |
| D-04 | Chunk size for KB corpus | 500 fixed / 800 fixed / section-aware | Section-aware, 1500 cap | Retrieval hit rate 0.86 vs 0.78 on 100 dev tickets. | 2026-09-03 |
```

## The five ADRs to write in Week 1

These are the decisions that shape everything downstream, and they need to be recorded before the code that depends on them:

1. **D-01 — Model provider.** OpenRouter vs Groq vs local. Measure throughput on the free tier before choosing.
2. **D-02 — Embedding model.** MiniLM (setup default) vs BGE. Small test on 100 dev tickets tells you.
3. **D-03 — Decision log store.** SQLite (default) vs PostgreSQL (only if there's a real reason).
4. **D-05 — Confidence threshold for routing.** The 0.80 in `.env.example` is illustrative. The Project Brief is explicit: "the number is yours to set and yours to defend." Set it after Thursday's data pass — a threshold sweep on the validation set with (auto-respond precision, escalation rate) as the axes.
5. **D-06 — Primary agent architecture pattern.** Pick one consciously. See below.

D-04 (chunking) comes in Week 2 after we have the retrieval loop running.

## D-06 — Choosing the agent architecture pattern

The 2026 agent-architecture literature (Brightter, Openlayer, LangGraph community) has stabilised around four composable patterns. The pack's stated architecture is a Router variant. That's the default, but it's a *decision*, not an obligation — and if we adopt it we still record it as an ADR so the reasoning is defensible.

Score each against this project's constraints:

| Pattern | How it fits CloudServe | Free-tier cost | Best-case A11 (graceful) |
|---------|------------------------|----------------|--------------------------|
| **Router** (classifier decides pipeline) | Native fit: classify → auto_respond / escalate / block, deterministic (A5). | 1 classification + 1 generation per ticket. Lowest. | Excellent — one failure mode per stage. |
| **ReAct** (think-retrieve-observe loop) | Overkill for bounded intents. Useful only if we need multi-hop retrieval, which the 29-doc corpus rarely rewards. Requires strict step cap or costs run away. | 3–8 model calls per ticket. High. | Fragile — every extra hop is an extra failure surface. |
| **Plan-and-Execute** (planner + N executor steps) | Not a fit: our tickets don't decompose into sub-queries whose results feed each other. Planner overhead earns nothing back. | 1 planner + N executor. Middle. | OK if plan is short. |
| **Self-RAG** (generate → self-critique for support → re-retrieve if unsupported) | Strong fit for A6 (citations resolve) and NFR-groundedness. Adds one critic call per ticket. Turns the guardrail into an in-line correction rather than a block. | 1 classify + 1 generate + 1 critic (+ 1 re-generate if critic fails). Highest. | Needs iteration cap = 1 retry, no more. |

The pack's default is a Router with post-hoc guardrails (block, not correct). Self-RAG upgrades that to a Router with in-line groundedness self-check. Whichever we choose is the D-06 ADR.

If we adopt any pattern with a loop (Self-RAG re-retrieve, Reflection redraft, ReAct), the ADR MUST state:

- **Step budget.** Maximum iterations per ticket (usually 1 retry, hard cap 3). Records to the decision log per iteration.
- **Cost cap.** Model calls per ticket must remain within free-tier budget for a full validation run — 80 tickets × N calls. If N > 4 we can't complete the gate run.
- **Termination condition.** What causes the loop to stop besides hitting the cap. "Critic says grounded" or "retrieved passages unchanged from last iteration" or similar.
- **Determinism preservation.** Same seed → same iteration count → same output (A5).

An agent loop without these four is how the "runaway ReAct agent that ran uncontrolled for 11 days" (industry cautionary tale, dev.to 2026) happens.

## Discipline

- **Write it before the code.** An ADR written after the code is a rationalisation, not a decision. Draft the ADR, sit with it for an hour, then implement.
- **Two options is the minimum.** "We chose X because it was obvious" is not an ADR. If it's truly obvious, it's not an ADR-worthy decision.
- **Measurement beats reasoning where measurement is cheap.** For chunk size, embedding model, threshold — the pilot is faster than the debate. Cite the numbers in the rationale.
- **Immutable once accepted.** Later thinking creates a new ADR that supersedes the old one (`Status: Superseded by D-XX`). The old one stays visible because "we tried this and it didn't work" is often the more valuable record.
- **Revisit trigger is required.** Every ADR names the observation that would cause it to be reopened. An ADR without a revisit trigger has no exit criterion and never gets revisited when it should be.

## Common ADR-worthy topics for this project

- Model provider (D-01)
- Embedding model (D-02)
- Decision log store (D-03)
- Chunking strategy (D-04)
- Routing threshold (D-05)
- Response schema for `generate.py`
- Guardrail order and short-circuit behaviour
- Retry / backoff policy for the model provider (A11 territory)
- Chroma persistence strategy (in-memory for tests vs persisted for production)
- What "unknown" means and how the system signals it
- API surface: single endpoint vs per-stage vs streaming

## When Stage 5 rolls around

Every ADR that got revised during the build becomes an entry in the Stage 5 PRD Revision Log. Cross-link: the revision log entry names the D-XX that changed, and the new ADR names the FR(s) whose meaning shifted.

## What to hand back

When writing an ADR:

1. Write the full record at `docs/adr/D-<nn>-<slug>.md`.
2. Add a row to `docs/architecture.md`.
3. If the decision affects existing code, list the files to update and either update them or open a note in `docs/architecture.md` under "Pending code changes from ADRs".
4. Confirm the revisit trigger names an observation (a metric, a symptom), not a date.
