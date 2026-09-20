# D-14 — A confidence-floor failure escalates; only a safety failure blocks

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-10, FR-12, FR-19
**Affects:** `src/route.py` (`_decide`, `_build_bundle`), `tests/test_route.py`, `docs/architecture.md` §5 and §6

## Context

The router has six ordered rules, first match wins: unlogged decision, guardrail block, the D-07 policy list, empty retrieval, generator-unknown, confidence floor. Rule 2 returns `block`; the rest return `escalate`.

The FR-19 confidence-floor guardrail restates rule 6 as a guardrail — D-05a's defence-in-depth, so that a confidence below the floor stops an auto-respond "regardless of upstream router decision". Both read `classification.confidence` against `CONFIDENCE_THRESHOLD`. In the shipped pipeline they are the same test, and the guardrail's verdict reaches the router at rule 2, four rules ahead of rule 6.

Two consequences, neither intended:

1. **Rule 6 is unreachable whenever the guardrails run.** A ticket below the floor always fails the guardrail, so rule 2 matches first. `trigger="low_confidence"` appears nowhere in either recorded run.
2. **A ticket the classifier was unsure about is reported as a safety block.** On `b21_openai_gemini_80_d12_20260920` (80 validation tickets) 33 decisions were `block`, and 17 of those had the confidence floor as their only failing check. The run's own summary reads "7 escalated by routing and 33 blocked by a guardrail", which puts a low-confidence hold in the same bucket as a PII leak.

The rule order was chosen to say something: governance outranks safety, safety outranks policy, policy outranks the quality signals. The confidence floor is the last of the quality signals, and routing it through rule 2 gives it the highest precedence of all and the wrong outcome name.

The PRD is unambiguous about which outcome it expects. FR-10: "The router SHALL escalate ... OR classifier confidence < CONFIDENCE_THRESHOLD". FR-19's acceptance criterion: "If a synthetic scenario sets classifier confidence to None but router says auto_respond, the guardrail overrides to escalate."

## Options considered

**A. Leave the code and document it.** Amend `docs/architecture.md` to say the confidence floor surfaces as `block`, and record the deviation from FR-10 and FR-19 in the Stage 5 log. Costs nothing, changes no recorded run. Leaves rule 6 dead, leaves the reviewer's block queue holding two kinds of ticket, and leaves the documented rule order describing a precedence the code does not apply.

**B. Hold the confidence floor back from rule 2, so it lands on rule 6.** The router partitions the failing blocking guardrails: anything except the confidence floor is a safety failure and returns `block`; a confidence-floor failure falls through the remaining rules and returns `escalate` with `trigger="low_confidence"`. Matches FR-10 and FR-19 as written, revives rule 6, and lets the D-07 policy and empty-retrieval rules take the tickets they were written for.

**C. Make the confidence floor non-blocking, or delete it.** Removes the duplication outright and leaves rule 6 as the single home of the threshold. Rejected: it gives up D-05a's defence-in-depth for no gain, and FR-19 is a Should-priority requirement that says the check blocks the action.

## Chosen

**Option B.** `route._decide` splits the failing blocking guardrails into safety failures and the confidence floor (`COVERAGE_GUARDRAILS`). Rule 2 reads the safety failures alone. Rule 6 fires on the router's own threshold or on the guardrail's verdict, whichever says the confidence is short, and returns `escalate` with `trigger="low_confidence"`. `_build_bundle` uses the same split, so `draft_blocked` stays False when nothing found a fault in the draft.

## Rationale

- **`block` and `escalate` mean different things to the person who receives the ticket.** `block` says a draft exists and must not be sent because something was found wrong with it. The confidence floor is the one blocking check that never reads the draft: it reads the classifier's confidence, which was known before a word was generated. Nothing about the draft is being asserted, so the outcome that says "this draft is unsafe" is the wrong one.
- **It restores the precedence the document describes.** Replaying the 17 floor-only blocks from `b21_openai_gemini_80_d12_20260920` through the amended rules: 7 match the D-07 policy list (rule 3) and 10 match the confidence floor (rule 6). The 7 are `compliance_request` / `security_incident` / `feature_request` / `unclear_request` tickets that FR-10 v2 and D-07 say escalate on the policy, at any confidence — they were being reported as guardrail blocks because the classifier also happened to be unsure.
- **No measured figure moves.** `routing_outcomes` and `results_table` score `auto_respond` against everything else (`evaluation/harness.py::routing_outcomes`), so precision, recall, the FCR proxy and the escalation rate are identical either way. The 80-ticket counts go from 40 auto / 33 block / 7 escalate to 40 auto / 16 block / 24 escalate, with the same 50.0% escalation rate.
- **Verified on local models, not only by replay.** `evaluation/results/b21_local_d14_10_20260920` — the first 10 validation tickets, `llama3.1-8b-ctx8k` drafting and `qwen2.5-7b-ctx8k` judging through Ollama, 323 s, A8 reconciles. VAL-0003 and VAL-0007 moved from `block` to `escalate` with trigger `never_auto_respond_intent`: both are `unclear_request` at 0.0 confidence, so rule 3 takes them and the D-07 policy is what gets reported rather than a guardrail. Replaying the run's own guardrail verdicts through the old rule changes those two decisions and no others. (VAL-0006 also differs from the 19 Sep local record, at `b21_local_record_10_20260920`, but no guardrail failed it on either rule — the local model drafted differently and the grounding judge passed it this time. That one is run-to-run variation, not this change.)

- **FR-19's defence-in-depth survives.** The guardrail still blocks the auto-respond action, and it is still the guardrail's verdict the router reads — not a second evaluation of the threshold. A run that injects a different router threshold (the D-05b sweep) still cannot auto-send a draft the guardrail held.

## Consequences

- Positive: `trigger="low_confidence"` becomes reachable and appears in the decision log, so the confidence threshold's live cost can be counted from the log instead of by reading guardrail arrays. The block queue holds only tickets where a check found a fault.
- Positive: the reason string still names the cause, so FR-12 holds. Where the guardrail is what fired, the reason quotes its own sentence.
- Negative: decision labels on the committed evidence runs are now one version behind the code. The runs stay as recorded — they are evidence of what the code did on that date — and `evaluation/results/b21_local_d14_10_20260920/` is the run made under the amended rule.
- Negative: `route.py` now names one guardrail (`confidence_floor`) in a module constant. The coupling is real but small, and a guardrail that is a restatement of a routing rule is the only kind that belongs in that set.
- FR-16's acceptance criterion ("The ticket routes to escalate") still describes a PII block as an escalation. That wording predates the three-outcome router and is not changed by this ADR; a safety failure still returns `block`. Recorded in the Stage 5 revision log.

## Revisit trigger

A second guardrail is added that does not read the draft — it belongs in `COVERAGE_GUARDRAILS` and the set stops being about one special case. Or: a run where `low_confidence` escalations carry drafts a reviewer sends unchanged, which would say the floor is holding back sendable replies rather than uncertain classifications.

## Supersedes / superseded by

None. Amends the rule-2 behaviour recorded in D-05a (confidence threshold as both router signal and guardrail floor) without changing that decision.
