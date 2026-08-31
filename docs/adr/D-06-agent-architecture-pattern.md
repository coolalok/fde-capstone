# D-06 — Agent architecture pattern

**Status:** Accepted
**Date:** 2026-08-30
**Decider:** Alok Kulkarni
**Constrains:** FR-04 through FR-24 (all pipeline behaviour); NFR-01a, NFR-01b, NFR-02, NFR-03, NFR-08
**Affects:** All eight `src/*.py` components; harness orchestration in `evaluation/harness.py`

## Context

The Build Specification describes a six-component pipeline (Ingest → Classify → Retrieve → Route → Generate → Validate) with three cross-cutting concerns (decision log, metrics, guardrails). That's a *shape*, not a *pattern*. The 2026 agent-architecture literature (Brightter, Openlayer, dev.to survey) has stabilised around four composable patterns: Router, ReAct, Plan-and-Execute, Self-RAG. This ADR names which pattern the pipeline instantiates, so every subsequent design decision (retries, budgets, loops) inherits a consistent shape.

## Options considered

**A. Router (classifier decides the pipeline).**
Native fit for the pack. One classification call chooses `auto_respond` / `escalate` / `block`. Deterministic (A5). One retrieval call, one generation call. Total: 3 model calls per ticket in the worst case (classify + generate + judge for evaluation).

**B. ReAct (think-retrieve-observe loop).**
Overkill for bounded intents. Multi-hop retrieval doesn't earn its keep on a 29-doc corpus where TF-IDF already hits 93.6% top-3. Requires step budget or costs run away. 3–8 model calls per ticket.

**C. Plan-and-Execute (planner + N executor steps).**
Not a fit. Our tickets don't decompose into sub-queries whose results feed each other. Planner overhead earns nothing back.

**D. Self-RAG (generate → self-critique for groundedness → re-retrieve if unsupported).**
Adds one critic call per ticket, plus one potential re-generation. Turns the guardrail from a post-hoc block into an in-line correction. Cost per ticket: 4–5 model calls in the worst case.

**E. Hybrid: Router with a Self-RAG groundedness check inline, iteration cap 1.**
Router as the outer pattern (classify → route → auto_respond / escalate / block), with Self-RAG applied only to the `generate` stage: after the model produces a draft, a groundedness check runs; if any factual claim isn't supported by the retrieved passages, the generator gets one retry with the ungrounded claims flagged. Total cost: 3 model calls (classify + generate + groundedness-critic) plus at most one re-generate.

## Chosen

**Option E — Router with inline Self-RAG groundedness on `generate`, retry cap 1.**

## Rationale

- Router is native to the pack's architecture and to the workflow support agents already use.
- Q3 pilot (`workbooks/q3_findings.md`) proved retrieval is essentially solved at 93.6% top-3. Adding multi-hop ReAct on top gains nothing but token cost.
- Self-RAG's groundedness self-check is what the guardrail rule needs anyway (FR-17 blocks unsupported claims). By running the check inline with a retry, we convert about half of the would-be blocks into a corrected answer — directly attacking Marcus's "rather nothing than wrong" concern (EV-M3) without turning every marginal case into an escalation.
- Retry cap 1 preserves determinism (FR-09): same input + same seed → at most one retry, → same output.
- Total cost per ticket: 3 model calls baseline + at most one re-generate. Fits inside the free-tier budget for a full validation run.

## Iteration budget (mandatory for any loop-based pattern per `capstone-adr` skill)

- **Step budget:** exactly 1 retry per ticket. Hard cap: 1.
- **Cost cap:** 4 model calls per ticket in the worst case × 120 hidden tickets = 480 calls per grading run. At OpenRouter free-tier 10 req/min: 48 minutes wall-clock worst case. Fits.
- **Termination condition:** the groundedness critic returns `passed=True`, OR the retry has been used, OR the retry returns identical unsupported claims (no progress).
- **Determinism preservation:** groundedness critic uses `temperature=0.0`. The re-generate uses the same seed as the original. Two runs with the same input produce the same output.

## Consequences

- Positive: cleanest fit to the pack's shape, addresses A6/A7 in a way that recovers value rather than dropping tickets, deterministic under a fixed seed.
- Negative: worst-case latency per ticket is ~2× baseline (extra critic + re-generate on failure cases). Under NFR-02 (p95 ≤ 4s), this is tight — needs measurement.
- Mitigation: cache the classifier output between ticket runs; skip the groundedness critic entirely when retrieval returned zero passages (that ticket is escalating regardless).

## Revisit trigger

- If groundedness failure rate exceeds 5% on the validation set AND the single retry doesn't recover them (measured after Week 2 harness runs), consider a full Reflection loop with 2+ retries.
- If the free-tier budget analysis shows the extra critic call blows the token allowance, drop Self-RAG's inline check and revert to post-hoc guardrail blocking.
- If Router's confidence threshold (D-05) can be tuned high enough that groundedness failures become rare (< 1%), the Self-RAG overhead may not earn its cost.

## Supersedes / superseded by

None. This is the first agent-architecture decision.
