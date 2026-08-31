# D-05 — Confidence threshold for auto-respond routing

**Status:** Provisional (initial value; final value set from data in Week 2)
**Date:** 2026-08-30
**Decider:** Alok Kulkarni
**Constrains:** FR-10, FR-19; NFR-07
**Affects:** `src/route.py`, `src/config.py` (`CONFIDENCE_THRESHOLD`), `evaluation/harness.py`

## Context

The router auto-responds when classifier confidence exceeds a threshold. Below it, the ticket becomes a tier-one draft-assist case, and further below, an escalation. Setting the threshold too high means the system escalates work it could have handled (defeats the FCR target). Setting it too low means the system sends confident-but-wrong answers to customers (violates EV-M3 — Marcus's #1 fear). The Project Brief is explicit:

> "The figure shows a confidence threshold of 0.80. That number is illustrative. Part of your work is to determine what the threshold should actually be, using your evaluation data, and to be able to explain the trade-off you accepted when you chose it."

## Options considered

**A. Fixed threshold at 0.80.**
Setup Guide default. Round number.

**B. Fixed threshold at 0.85.**
More conservative. Fewer auto-responses, fewer wrong sends.

**C. Fixed threshold at 0.70.**
More aggressive. Higher FCR, higher risk of confident-wrong.

**D. Sweep threshold on validation set; choose the value that maximises FCR subject to auto-respond precision ≥ 0.95.**
Data-driven. The Project Brief explicitly asks for this.

## Chosen

**Option D — data-driven sweep. Initial value 0.80 pending the sweep.**

Provisional 0.80 stays in `.env.example` for Week 1 so the code paths work end-to-end. The final value is determined by a threshold-sweep script run at the end of Week 2 against the validation set. The chosen value replaces 0.80 in `.env.example` and gets a D-05b ADR that records the sweep result.

## Rationale

- The Project Brief is unambiguous: the number must come from data, not from setup-guide convention.
- Precision-first constraint (`≥ 0.95` auto-respond precision) directly encodes Marcus's "rather nothing than wrong" (EV-M3).
- FCR is the maximisation objective because it's Marcus's actual reported measure (EV-M2), even though the SLA tracks reply time.
- Constraint of `must_not_auto_respond=false` and `answerable_from_docs=true` is applied before the confidence threshold, so the sweep is over the auto-responsible sub-population only.
- Sweeping is cheap: at 80 validation tickets, running the classifier once per ticket at each threshold in 0.05 steps from 0.5 to 0.95 is 10 runs × 80 tickets = 800 classifications. Fits comfortably in the free-tier budget with caching.

## Consequences

- Positive: honest data-driven choice, defensible in the video and in the compliance review.
- Negative: initial 0.80 may misrepresent the final routing shape during Week 1 demos. Video demos happen in Week 3, after the sweep.
- Mitigation: the harness config takes the threshold from `CONFIDENCE_THRESHOLD` env var, so the final value swaps in without code changes.

## Revisit trigger

- Threshold-sweep script runs at the end of Week 2 with real classifier output on validation set. If the chosen value differs materially from 0.80, D-05b records the new value and the sweep evidence.
- If classifier calibration (NFR-07) shifts across model versions, sweep again.

## Supersedes / superseded by

D-05b (Week 2, data-driven final value) will supersede this provisional ADR when written.
