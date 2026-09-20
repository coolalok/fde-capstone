# D-06a — The Self-RAG critic as built: structural in the loop, semantic after it

**Status:** Accepted. Amends D-06 (the retry loop's critic). D-06's Router pattern, retry cap and termination rules stand.
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-13, FR-14, FR-17
**Affects:** `src/generate.py` (`_structural_critic`), `src/guardrails.py` (`GroundingGuardrail`), `docs/architecture.md`

## Context

D-06 says the in-loop critic checks that "any factual claim" in the draft is supported by the retrieved passages, and retries once with the unsupported claims flagged. The code does something different, and this record is written after the fact to say so.

- The critic inside the retry loop is `_structural_critic` in `src/generate.py`. It checks shape only: `unknown` agrees with an empty answer and empty citations, a real answer carries citations, and every citation is a `doc_id` that was retrieved. It does not read the answer against the passage text. A draft that cites the right article and misstates what it says passes.
- The semantic check is `GroundingGuardrail` (FR-17, PR-GUARDRAIL-GROUNDING-01), which runs after generation as a post-hoc guardrail. A failure blocks the reply. It does not trigger a retry.

The `_structural_critic` docstring anticipated "a B-13 semantic critic can be composed on top". That composition was never built.

## Options considered

**A. Semantic critic in the loop, as D-06 describes.** One extra model call per ticket, then the grounding guardrail runs a second semantic check on the same draft. Recovers drafts that fail grounding on the first try.

**B. Structural critic in the loop, semantic check as a blocking guardrail (as built).** No extra model call. An ungrounded draft is blocked and the ticket goes to a person; it is never corrected.

**C. Feed the grounding guardrail's verdict back into the retry loop.** Reuses the one semantic call. Needs the guardrail to run inside `generate()` or the harness to re-enter generation, which changes the stage order every decision-log row assumes.

## Chosen

**Option B**, recorded as the system that exists.

## Rationale

Measured on the 80-ticket local run (`evaluation/results/b21_local_80_20260919`): the grounding guardrail blocked 3 of 80 drafts. Option A or C could at best recover those 3 tickets, at the cost of one more model call per ticket (A) or a restructured pipeline (C) on the submission day. The safety property that matters, that an ungrounded draft is never sent, holds under B because the guardrail blocks.

## Consequences

- Positive: one fewer model call per ticket than D-06 budgeted; the semantic check is still applied to every draft that has passages.
- Negative: "Self-RAG" in D-06 overstates what the loop does. The loop catches fabricated and missing citations, not misstated facts. A misstated fact is caught by the guardrail and costs the ticket an automated reply instead of being corrected.
- The report and the video must describe the loop as a citation-structure self-check plus a blocking grounding guardrail, not as semantic Self-RAG.

## Revisit trigger

If the grounding guardrail blocks more than 10% of drafts on a validation run, recovering them becomes worth a model call: build Option C.

## Supersedes / superseded by

Amends D-06 on the critic only.
