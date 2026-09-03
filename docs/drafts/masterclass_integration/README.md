# Masterclass 3 / Masterclass 4 / RAG_demo — integration drafts

**Date:** 2026-09-03 (Thu, Week 2 Day 4)
**Author:** Alok Kulkarni (assisted)
**Status:** Drafts. Nothing pasted into workbooks yet.

## What this folder is

Ready-to-paste text for the parts of the Masterclass integration that live inside `.docx` files I cannot edit directly. The parts that live in code, ADRs, tests, and prompt-library markdown files have already been written to their canonical locations — see the *Applied directly* section below.

## Applied directly (nothing for you to do here)

| Change | File |
|---|---|
| New ADR: dual-role confidence threshold | `docs/adr/D-05a-confidence-threshold-dual-role.md` |
| New ADR: decision-log trace schema extension | `docs/adr/D-03a-decision-log-trace-schema.md` |
| New test contract for FR-GUARD-01..04 (skips until B-11 lands) | `tests/test_guardrails.py` |
| New prompt: PR-GENERATE-01 (B-09 target) | `prompts/build/PR-GENERATE-01.md` |
| Skill update: EV-MC3-* / EV-MC4-* / EV-RAGD-* evidence tag families | `skills/capstone-conventions.md` (also proposed via propose_skills for account) |

## Needs pasting

1. `prd_guardrail_frs.md` → Stage 2 PRD, §Guardrails FR block.
2. `backlog_amendments.md` → Stage 4 Sprint Plan Table 3 (backlog).
3. `governance_schema_extension.md` → Governance Framework §Decision Log Schema.
4. `stage5_revision_log_entry.md` → Stage 5 PRD Revision Log.
5. `prompts_register_update.md` → `prompts/README.md` register table (optional; can wait until B-09 formally closes).

## Sequencing note

Per capstone-conventions Rule 1: none of the above adds a new B-XX row to Stage 4. They amend existing rows (B-07, B-09, B-11, B-15, B-16), add supporting ADRs, and pre-write the test contract. If you'd rather add a new backlog row (e.g. B-28: LLM-as-judge for the confidence sweep) instead of enriching B-16's DoD, tell me and I'll re-draft.

Creating `prompts/build/PR-GENERATE-01.md` today starts B-09's authoring early (was slotted for Wed Sep 2). Flagging per Rule 1 — this is a user-authorised override. The register update in `prompts/README.md` should happen when B-09 formally closes, not now.
