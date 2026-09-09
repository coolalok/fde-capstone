# D-07 — How the router knows a ticket must never be auto-answered

**Status:** Accepted
**Date:** 2026-09-04
**Decider:** Alok Kulkarni
**Constrains:** FR-10 (routing escalation triggers), FR-09 (determinism)
**Affects:** `src/route.py`, `src/schema.py`, Stage 2 PRD FR-10 (revised to v2 by this ADR)

## Context

FR-10 v1 said the router SHALL escalate any ticket where `labels.must_not_auto_respond = true`.

That cannot be implemented. `must_not_auto_respond` lives in the `labels.*` block, which is evaluation ground truth. FR-01 v2 (revised 2026-09-03) removed `labels.*` from the `Ticket` entirely, precisely so production code cannot read answers it will not have at inference time. Reading the flag at runtime would reintroduce the leak FR-01 v2 closed, and would make every routing metric optimistic in a way the hidden set would expose.

So the router needs a runtime signal that stands in for the flag. The only comparable signal it has is the classifier's `intent`.

## Options considered

**A. Read `labels.must_not_auto_respond` directly.**
Trivially correct on labelled data, and worthless — the hidden evaluation set is scored on tickets whose labels the system must not consult, and the pack's Dataset Guide is explicit that labels are held out. Reintroduces the FR-01 v2 leak.

**B. Fixed policy list of intents that never auto-answer.**
The router escalates whenever the classified intent is in a named set. Deterministic, inspectable, and cheap. Depends on the classifier being right about those intents.

**C. Train or prompt a separate "is this automatable?" classifier.**
A second model call per ticket, another prompt to version and calibrate, another failure surface — for a decision that option B appears to make correctly. Cost without evidence of benefit.

## Chosen

**Option B — a fixed policy list of four intents.**

```
NEVER_AUTO_RESPOND = {
    "compliance_request",
    "security_incident",
    "feature_request",
    "unclear_request",
}
```

FR-10 is revised to v2 to name this policy instead of the label.

## Rationale

The four intents reproduce the ground-truth flag exactly on every labelled ticket we hold:

| Set | n | Flagged | Policy predicts | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|---|---|
| Development | 500 | 87 | 87 | 87 | 0 | 0 | 1.000 | 1.000 |
| Validation | 80 | 14 | 14 | 14 | 0 | 0 | 1.000 | 1.000 |

This is not a coincidence of sampling. EV-DATA-10 established that the flag is *driven by* ticket type: `compliance_request` (26), `security_incident` (26), `feature_request` (20) and `unclear_request` (15) are each 100% flagged, and 26+26+20+15 = 87, the entire flagged population. The label is a function of the intent, so a policy on intent is not an approximation of the label — it is the same rule, expressed in a field the router is allowed to see.

**The important caveat.** Those figures are measured against the *true* intent. In production the router sees the *classifier's* intent, so real recall is bounded by classifier recall on these four classes, not by this policy. A security incident misclassified as `account_access` will not trigger the policy.

Two things mitigate that, and neither is a substitute for measuring it:

- The confidence threshold is a partial backstop. A ticket the classifier gets wrong on these classes will often be one it was unsure about, and FR-10's confidence rule escalates it anyway — by a different route, with a different reason.
- `unclear_request` is the intended sink for tickets with no clear signal, so the ambiguous cases the classifier cannot place tend to land inside the policy rather than outside it.

## Consequences

- Positive: FR-10 becomes implementable without reading ground truth. The router stays a pure function of runtime-available fields (FR-09, A5).
- Positive: the policy is one named constant, so a support manager can read the escalation rule and an auditor can check it (EV-M5).
- Negative: correctness now depends on classifier accuracy for four intents, which is a coupling FR-10 v1 did not have. If the classifier degrades on `security_incident`, the routing safety property degrades silently with it.
- Negative: the policy is coarser than Daniel's stated do-not-automate list. EV-DATA-10 records that he named billing disputes and data location, but the labels do not separate billing *disputes* from billing *queries*, and 72% of `data_residency` tickets are answerable from docs. Those two categories are deliberately **not** in the policy for the Week 2 build.

## Evidence

- **EV-DATA-10** — the flag is driven by four ticket types, each 100% flagged, together accounting for all 87 flagged tickets.
- **EV-D4** — Daniel's do-not-automate list (security, billing disputes, data location); partially adopted, with the gap recorded above.
- **EV-M3** — "rather nothing than wrong"; the policy fails toward escalation in every ambiguous case.
- **FR-01 v2** (Stage 5 revision log, 2026-09-03) — the decision that removed `labels.*` from the Ticket and made option A unavailable.

## Revisit trigger

- Measure per-intent classifier recall on the four policy intents at B-21. If recall on any of them falls below 0.90, the policy's effective coverage is materially worse than the 1.000 measured here and this ADR should be reopened — the mitigation would be to widen the policy or lower the threshold for those intents specifically.
- If any ticket in the hidden run is flagged `must_not_auto_respond` in the released answers but was auto-answered, this policy has a false negative that the dev and validation sets did not contain.
- If the billing-dispute or data-residency question from EV-DATA-10 is resolved, revisit for inclusion.

## Supersedes / superseded by

None. Revises FR-10 to v2; does not supersede another ADR.
