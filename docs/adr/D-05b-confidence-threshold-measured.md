# D-05b — Confidence threshold, measured (completes D-05)

**Status:** Accepted, with the precision constraint UNMET. Completes D-05.
**Date:** 2026-09-04
**Decider:** Alok Kulkarni
**Constrains:** FR-10, FR-19, NFR-07
**Affects:** `src/config.py` (`CONFIDENCE_THRESHOLD`), `.env.example`, `src/route.py`, PRD Table 9 Q6

## Context

D-05 deferred the confidence threshold to a measured sweep and kept 0.80 as a placeholder: *"the number is yours to set and yours to defend."* B-16 is that sweep. The rule D-05 set was: **maximise the FCR proxy subject to auto-respond precision ≥ 0.95**, where the 0.95 floor encodes EV-M3 (Marcus: "I would rather it said nothing than said something wrong").

`evaluation/d05_threshold_sweep.py` runs 0.50–0.95 in 0.05 steps against the 80-ticket validation set. Each ticket is classified, retrieved and generated for real (238 live model calls, zero failures). Guardrails are excluded — see Consequences.

## The result

**No threshold reaches precision 0.95.** The selection rule D-05 specified cannot be applied.

| Threshold | Auto-responded | TP | FP | Precision | Recall | FCR proxy | Escalation rate |
|---|---|---|---|---|---|---|---|
| 0.50–0.80 | 64 | 46 | 18 | 0.719 | 0.958 | 0.575 | 0.200 |
| **0.85** | **50** | **38** | **12** | **0.760** | **0.792** | **0.475** | **0.375** |
| 0.90 | 38 | 28 | 10 | 0.737 | 0.583 | 0.350 | 0.525 |
| 0.95 | 13 | 11 | 2 | 0.846 | 0.229 | 0.138 | 0.838 |

Two features of that curve matter more than the individual numbers.

**It is flat, then it collapses.** Precision moves 0.719 → 0.760 across the entire 0.50–0.85 range — four percentage points for a 35-point move in the threshold — while recall falls from 0.958 to 0.792. It is also non-monotonic: 0.90 scores *lower* precision than 0.85. A control that barely moves its target while destroying the thing it trades against is not the binding constraint.

**The binding constraint is answerability, not confidence.** Of the 18 false positives at 0.80, **17 are `answerable_from_docs=false`** and 14 of 18 were classified *correctly*. The classifier is right and confident; the documentation simply cannot answer the ticket. No confidence threshold can detect that, because confidence measures "is this the right intent", not "can the docs answer it". This is the failure D-02a predicted: at the 0.25 retrieval floor only about one non-answerable ticket in ten returns zero passages, so a non-empty passage list is not evidence of answerability.

## Why FR-14 did not save it

FR-14's `unknown` branch is the control designed for exactly this case — passages present, but they do not support an answer. Measured on the same run:

| | count |
|---|---|
| Unanswerable tickets in the validation set | 27 |
| ...that the generator flagged `unknown` | 8 |
| ...that the generator **answered anyway** | **19** |
| Of the 8 flagged, how many had zero passages (the trivial PR-GENERATE-02 path) | 7 |
| **Unknowns earned by judgement (passages present, declined anyway)** | **1 of 26** |
| Answerable tickets wrongly flagged unknown (over-abstention) | 2 of 53 |

The plumbing is correct — B-11 verified the branch, the schema and the routing. The *prompt* is not calibrated. PR-GENERATE-01's grounding section instructs the model to set `unknown` when the passages do not support an answer; in practice it does so once in twenty-six opportunities. It is not over-abstaining either (2 of 53), so this is not a threshold-of-caution problem — the model is simply answering from loosely-related passages rather than declining.

That is R-01 (confidently incorrect answers) reproducing under measurement, and it is the single most important finding of this sweep.

## Chosen

**`CONFIDENCE_THRESHOLD = 0.85`, provisionally, with the precision constraint recorded as unmet.**

D-05's rule selects nothing, so this is a documented judgement rather than a derived value. 0.85 is the local precision maximum before the collapse: it buys 4.1 points of precision over the old 0.80 for 16.6 points of recall. 0.95 reaches 0.846 precision but answers 13 of 80 tickets — an FCR proxy of 0.138 fails the business case that motivates the project (EV-M2), and a system that abstains from six tickets in seven is not the deflection Marcus asked for.

**The threshold is not where this gets fixed.** The remediation is the generator declining more honestly, and the untested control is FR-17.

## PRD Table 9 Q6 — should the threshold be tier-differentiated?

**No, not on this evidence.**

| Tier | n | Precision @0.80 | Precision @0.85 |
|---|---|---|---|
| standard | 42 | 0.677 | 0.731 |
| business | 30 | 0.741 | 0.778 |
| enterprise | 8 | 0.833 | 0.833 |

The apparent 15.6-point spread at 0.80 narrows to 10.2 points at 0.85 and rests on an enterprise cell of **n=8** — one ticket moves that figure by 12.5 points. There is no measurable tier signal here, only a small-sample artefact.

There is also a reason not to do it even if the signal were real: a tier-differentiated threshold means a standard-tier customer needs a higher bar to receive an automated answer than an enterprise customer with an identical ticket. That is a fairness property NFR-05 exists to constrain, and it would need its own justification rather than falling out of a sweep. Q6 is answered: single threshold, all tiers.

## Consequences

- `CONFIDENCE_THRESHOLD` moves 0.80 → 0.85 in `src/config.py` and `.env.example`.
- **The precision-first constraint from EV-M3 is not met at any threshold.** This must be stated in the report and the video rather than presented as a solved parameter. The measured ceiling is 0.760 at a usable operating point.
- Guardrails were excluded from this sweep, and one of them is the untested control that directly targets the failure. FR-17's grounding guardrail checks whether each claim is supported by a *cited* passage — which is precisely what a fabricated answer over loosely-related passages fails. Its effect on auto-respond precision is unmeasured and is the most likely route to the 0.95 floor.
- Escalation rate at 0.85 is 0.375 against a historical baseline of 56.2%, so the system still deflects more than the status quo even at the higher bar.

## Evidence

- `evaluation/results/d05_threshold_sweep.json` — full sweep, per-ticket detail, 80 tickets, 238 live calls, 0 classifier failures.
- `evaluation/results/d05_threshold_sweep_no_generation.json` — the generation-free baseline, kept because the contrast is what showed generation is not the lever either (precision 0.727 → 0.719 at 0.80).
- **EV-M3** — the 0.95 precision floor this sweep fails to reach.
- **EV-M2** — FCR as the maximisation objective, which is why 0.95 was rejected despite its higher precision.
- **D-02a** — the measurement showing a non-empty passage list is not evidence of answerability.
- Classifier health on this run: 82.5% intent accuracy against true labels, 1 `unknown`, 0 call failures.

## Revisit trigger

- **Re-run this sweep with guardrails enabled.** If FR-17's grounding guardrail lifts auto-respond precision to ≥ 0.95, the threshold should be re-optimised for FCR underneath that floor and will likely come *down* from 0.85, recovering recall. This is the first thing to do after B-21.
- If PR-GENERATE-01 is revised to abstain more readily, re-run: the judgement-based unknown rate of 1-in-26 is the number to watch, and any prompt change targeting it invalidates this sweep.
- If the hidden-set run shows auto-respond precision below 0.70, the threshold is not holding and the system should escalate everything pending investigation.
- If a future validation set carries more than ~25 enterprise tickets, revisit Q6 — the tier question is currently unanswerable rather than answered negatively.

## Supersedes / superseded by

Completes D-05, which deferred this value. Does not supersede it — D-05's reasoning about *why* the number must come from data stands.
