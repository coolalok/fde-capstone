# D-05a — Confidence threshold: router signal AND guardrail floor

**Status:** Provisional. Extends D-05.
**Date:** 2026-09-03
**Decider:** Alok Kulkarni
**Constrains:** FR-19, NFR-07

> **Note 2026-09-03:** the original Constrains line also cited `FR-GUARD-04 (new)`. That reference was removed after PRD Table 9 Q7 resolved 2026-09-03 that FR-GUARD-01..04 are deferred to Week 3 candidate (see Stage 5 revision log). The dual-role reasoning of this ADR — routing vs floor — still applies to FR-19 alone; the "floor" role is not implemented as a separate guardrail in the Week 2 build. `src/guardrails.py` gains only the FR-16..19 validators; the `MIN_RELEVANCE_SCORE` construct proposed here stays unbuilt until Q7 revisits.
**Affects:** `src/guardrails.py`, `src/route.py`, `src/config.py`, `evaluation/harness.py`

## Context

D-05 sets a single confidence threshold governing routing between auto-answer / draft-to-tier-1 / escalate-to-tier-2. Review of the RAG_demo reference implementation (`backend/guardrails.py` line 107, EV-RAGD-CONF) and Masterclass 4 slide 8 "Output Validation" layer (EV-MC4-SAFETY) both use the same retrieval-relevance score at a *lower* floor as a hard "withhold generation" guardrail — defense in depth beneath the router's routing decision.

Our D-05 currently has one threshold with one role. The reference architecture uses two thresholds with two roles: a hard *floor* below which no generation happens at all, and a *routing boundary* above the floor that decides auto vs draft vs escalate. Collapsing both into one threshold either (a) sets it high enough that the router loses its middle band, or (b) sets it low enough that generation runs on effectively-irrelevant context. Neither is defensible.

## Options considered

**A. Single threshold — status quo (D-05).**
One value. Simplest. Loses the defense-in-depth floor: nothing prevents generation on a top-hit score of 0.05 if the router happens to send that path to "auto".

**B. Two thresholds, hard floor + routing boundary.**
`MIN_RELEVANCE_SCORE` gates generation (guardrail). `ROUTE_CONFIDENCE_THRESHOLD` gates auto-answer vs draft (router). Requirement: floor strictly less than routing boundary.

**C. Move all confidence logic into the router; drop the floor.**
Trust the router. Rejected: A7 requires at least one guardrail that BLOCKS, and no other guardrail covers "the answer would be ungrounded because retrieval failed" as cleanly.

## Chosen

**Option B — two thresholds.**

- `MIN_RELEVANCE_SCORE` (this ADR): hard floor. Below this, `validate_output` returns `allowed=False` with `flags=["low_retrieval_confidence"]`; no generation call happens; ticket escalates on route `insufficient_context`. Provisional value: **0.25** (RAG_demo default, to be re-fit against our corpus in B-16).
- `ROUTE_CONFIDENCE_THRESHOLD` (D-05): router decision boundary between auto-answer and tier-one draft. Provisional value: **0.80**.
- Invariant: `MIN_RELEVANCE_SCORE < ROUTE_CONFIDENCE_THRESHOLD`. Enforced in `src/config.py` at load time.
- B-16 becomes a two-dimensional sweep. Report both thresholds and both frontiers (precision surface for the router; false-block rate for the floor).

## Rationale

- Matches EV-RAGD-CONF and EV-MC4-SAFETY.
- Preserves the router's three-way routing behaviour (Marcus's precision-first constraint, EV-M3, still gates auto-answer via 0.80).
- Gives the system an explicit "we don't know" state that isn't a confident-wrong. Directly addresses R-01 (hallucination on out-of-scope input).
- Keeps the decision auditable: `decisions.db` records `retrieval_max_score`, both thresholds, and the outcome, so any withheld answer is defensible.

## Consequences

- `src/guardrails.py` gains only the FR-16..19 validators for the Week 2 build. The `validate_output(answer, retrieved_context, max_relevance_score)` shape proposed here is unbuilt until PRD Table 9 Q7 revisits (deferred 2026-09-03).
- `src/route.py` structure unchanged; the router only sees turns that already cleared the floor.
- `src/config.py` gains `MIN_RELEVANCE_SCORE` (default 0.25) and startup assertion for the invariant.
- Decision log records both thresholds and both outcomes (see D-03a).
- B-16 time-box impact: ~+45 min. Still fits its slot.

## Evidence

- EV-RAGD-CONF — RAG_demo `backend/guardrails.py` lines 107-112.
- EV-MC4-SAFETY — Masterclass 4 slide 8, four-layer safety model.
- EV-Q3 — retrieval baseline (TF-IDF hit@3 = 93.6%) establishing that below ~0.25 the retriever is essentially returning noise.
- EV-M3 — Marcus's "rather nothing than wrong" (Stakeholder Interview).

## Follow-up

- B-16 sweep produces D-05b (records the sweep result and locks both values).
- Add `test_retrieval_confidence_hard_block_below_floor` and `test_route_confidence_threshold_boundary` to `tests/test_guardrails.py` and `tests/test_route.py` respectively.
