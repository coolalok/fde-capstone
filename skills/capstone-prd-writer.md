---
name: capstone-prd-writer
description: Write or revise a functional or non-functional requirement for Alok's FDE Capstone PRD. Use when: adding a requirement, tightening a requirement, filling in Stage 2 PRD Template, checking traceability of requirements to evidence, or reviewing draft requirements from earlier. Assumes capstone-conventions is loaded.
---

# Capstone PRD Writer

Requirements are how discovery becomes code. Every mark in the Requirements & Traceability band (10%) and roughly half of the Discovery band (15%) depends on this being tight. Under-specified requirements are the single biggest cause of thin PRDs and mid-build rewrites in this project.

## Format — every requirement uses this shape

```
FR-<nn>  <Short imperative title, ≤10 words>
Trace:   <EV-M1, EV-S3, …>          # one or more evidence tags
Priority: MUST | SHOULD | COULD | WON'T
Statement:
  The system SHALL <verifiable behaviour>. <One sentence max.>

Acceptance:
  - <Observable check 1>
  - <Observable check 2>
  - <…>

Verification: <How this is checked — unit test / harness metric / manual review>
Component:    <src/ module this lands in — e.g. classify.py>
Out of scope: <What this requirement does NOT cover, if there's a plausible confusion>
```

NFRs use `NFR-<nn>` and the same shape, with `Statement:` phrased as a constraint or quality attribute rather than an action.

## The verifiable-language rule

Every `Statement:` line must pass this test: could someone else write a test that says "this is met" or "this is not met" without asking me? If not, rewrite.

**Reject** and rewrite these:
- "The system should be fast" → NFR-XX: "p95 end-to-end latency SHALL be ≤ 4.0s over the validation set"
- "Retrieval should return good passages" → FR-XX: "Retrieval SHALL return the passage whose `doc_id` is in `expected_doc_ids` within its top-3 results on ≥85% of dev tickets where `answerable_from_docs=true`"
- "The system should handle bad input" → FR-XX + FR-YY (split): one for empty body, one for unusual chars

**Accept:**
- "The system SHALL classify every ticket with an intent from the closed set of 22 classes and a confidence in [0,1]." (A3, verifiable)
- "The system SHALL route to escalation any ticket where `labels.must_not_auto_respond=true` regardless of confidence." (guardrail-adjacent)
- "The confidence score of the classifier SHALL be calibrated such that, in the 0.80–0.90 band, empirical accuracy is 0.80 ± 0.05 on the validation set." (from Evaluation Framework §3 calibration)

## Traceability discipline

- Every FR/NFR needs at least one **EV-*** tag pulled from `workbooks/discovery_notes.md` or from the ticket data (write `EV-DATA-<n>` for ticket-data-derived findings and add them to the discovery notes).
- If you can't find an evidence tag, the requirement doesn't have a home. Two paths:
  1. The evidence exists but isn't logged → go tag it in discovery_notes.md first, then write the requirement.
  2. The evidence doesn't exist → this is a wish, not a requirement. Drop it or mark it as an **assumption** in the PRD's Assumptions section.
- The reverse check runs weekly: every strong EV should appear in at least one FR or NFR. Orphan evidence is either something we deliberately don't address (note it in Out-of-Scope) or something we forgot.

## Priority rules (MoSCoW, calibrated to the acceptance criteria)

- **MUST** — required for A1–A12 or for the gate. If the FR isn't met, we fail the criterion.
- **SHOULD** — required for a strong evaluation. If absent, the number drops but we still ship.
- **COULD** — nice-to-have, gets deferred first when time runs out per the Stage 4 sprint plan.
- **WON'T** — explicitly out of scope for this version. Documented so it's not silently missing.

Every FR marked MUST has to link to at least one **A<n>** in its Verification line.

## Common FR shapes for this project

Use these as starting templates; each still needs its Trace, Acceptance and Verification.

- **Ingest FR**: "The system SHALL accept tickets from `{email | chat | docs_comment | forum}` and produce one normalised `Ticket` object with `channel`, `body`, `received_at`, and all `labels.*` fields preserved."
- **Classification FR**: "The classifier SHALL return `{intent, urgency, confidence, alternatives[]}` for every ticket, where `intent` is one of the 22 known classes plus `unknown`."
- **Retrieval FR**: "The retriever SHALL return zero passages when no passage's similarity score exceeds threshold `RETRIEVAL_THRESHOLD` (env-configurable), rather than returning the top-K regardless."
- **Routing FR**: "The router SHALL escalate any ticket where `must_not_auto_respond=true`, where confidence < `CONFIDENCE_THRESHOLD`, or where retrieval returned zero passages."
- **Generation FR**: "The generator SHALL produce output whose `citations` field lists only `doc_id`s that were in the retrieved passage set for this ticket."
- **Guardrail FR**: "The PII guardrail SHALL BLOCK any response containing an email address, API key pattern, or account number that is not the customer's own."
- **Logging FR**: "The system SHALL persist one decision-log record per ticket, containing all fields in the decision log schema, before the response is sent."

## Non-functional shapes

- **Latency**: "p95 end-to-end response time SHALL be ≤ 4.0s across the validation set."
- **Reliability**: "The system SHALL complete a full validation-set run without crashing on any single ticket, given the model provider returns HTTP 200 for at least 80% of calls."
- **Explainability**: "Every routing decision SHALL include a human-readable `reason` field a support manager could act on."
- **Fairness**: "Answer quality (rubric-scored) SHALL not vary by more than 15 percentage points across `language_fluency` segments on the validation set."
- **Determinism**: "Given identical input and identical `RANDOM_SEED`, two runs of the classifier SHALL produce identical output."

## RAG quality — three separate NFRs, never conflated

2026 practice (Openlayer, Braintrust, and evals literature) decomposes RAG quality into three orthogonal dimensions. Score each separately in the evaluation report; a single "answer quality" number hides where the failure lives. Every RAG-adjacent NFR names which of the three it constrains.

- **NFR-Xa Context relevance** (retrieval): "For tickets flagged `answerable_from_docs=true`, at least one of the top-K retrieved passages SHALL be from a `doc_id` in `expected_doc_ids` on ≥ 85% of the validation set." — measures whether retrieval brought back material that could support an answer, independent of what generation did with it.
- **NFR-Xb Groundedness** (generation faithfulness): "For every factual claim in a generated response, a supporting span SHALL be present in the retrieved passages set; groundedness rate SHALL be ≥ 95% on judge-scored samples." — measures hallucination directly. This is the one that determines whether we embarrass the client.
- **NFR-Xc Answer relevance** (question addressal): "Generated responses SHALL address the ticket's asked question, scored ≥ 4/5 on a 1-5 rubric by an LLM-as-judge calibrated to ≥ 0.85 agreement with human raters." — a grounded answer to the wrong question still fails the customer.

The three are independent: high context relevance + low groundedness = model ignored retrieval and made things up. High groundedness + low answer relevance = model cited faithfully but answered a different question. High answer relevance + low context relevance = model happened to know the answer without retrieval (impressive but non-reproducible and off-thesis for our project).

## The traceability audit pass — REQUIRED before saving any PRD version

The single most common way this rule gets broken is: you finish writing FRs, save, and only later discover some FRs don't trace to any discovery evidence. Prevent it by running an explicit audit pass before saving. It's mechanical and takes five minutes.

### Two-direction audit

1. **Forward:** for every FR/NFR, list the discovery evidence tags it carries. Any requirement with zero EV-*, `#N`, or `R-XX` reference is broken — either find the trace or delete the requirement.
2. **Reverse:** for every EV-* tag in `workbooks/discovery_notes.md` and `workbooks/discovery_notes_thursday.md`, list the FR/NFR IDs that reference it. Any EV with zero references is orphan evidence: either write a requirement that addresses it, mark it explicitly out-of-scope in Table 6, or add a note in the risk register acknowledging you deferred it.

### Reference categories the audit accepts

- `EV-<initial><n>` — interview evidence, e.g. `EV-M3`, `EV-S5`, `EV-I2`
- `EV-DATA-<nn>` — ticket-data evidence, e.g. `EV-DATA-10`
- `#N` with a specific row reference — e.g. "#2, channel split row"
- `R-<nn>` — risk register entry from Stage 1 Table 12
- A named artefact of Stage 1 discovery (Q3 pilot findings, etc.)

### Reference categories the audit REJECTS as evidence

- `A1`..`A12` — those are pack acceptance criteria, not discovery. They go in the **Acceptance criteria** column of Table 4.
- References to Governance Framework, Evaluation Framework, Build Specification — those are pack constraints, not discovery evidence.
- References to any capstone skill file (`capstone-prompt-writer`, `avoid-ai-writing`, etc.) — those are process guides authored during the project, not evidence gathered from CloudServe.

Mixing categories is what caused the v1 PRD's "Discovery evidence" column to contain `A5`, `A7`, `Governance Framework guardrail table`, and skill names — a category error corrected in the traceability revision.

### Running the audit

Use `scripts/traceability_audit.py` (checked into the repo). It:

- Extracts EV-* and R-* tags from both discovery notes and the Stage 1 workbook
- Reads Table 4 of `Stage_2_PRD_Template.docx` and lists every FR's Discovery evidence cell
- Reports the two failure modes: FRs without evidence, and orphan EV tags
- Exits non-zero if anything is missing

Run it as `python -m scripts.traceability_audit`. In CI, wire it as a pre-commit for anything in `workbooks/` or `docs/adr/`.

## When revising a requirement (Stage 5)

Write the revision as:

```
FR-<nn>  <title>  (v2 — revised 2026-09-08)
Was:      <one-sentence summary of v1 statement>
Now:      <one-sentence summary of v2 statement>
Trigger:  <what discovery during the build prompted the change>
Impact:   <which prompts, tests, docs need to change too>
```

Then update the FR body. The `Trigger` field is what the Stage 5 workbook and the report's Revision section live on — never leave it empty or vague ("we changed our minds" isn't a trigger).

## What to hand back

When drafting one or more requirements:

1. Write them in the format above.
2. Print a short "traceability check" table underneath showing every EV tag used and every A<n> touched.
3. Flag any EV in `discovery_notes.md` that still has zero requirement coverage.
4. If you introduced an assumption to bridge missing evidence, list it separately for the PRD's Assumptions section.
