# D-03 — Decision log store

**Status:** Accepted
**Date:** 2026-08-30
**Decider:** Alok Kulkarni
**Constrains:** FR-20; NFR-04, NFR-08, NFR-09
**Affects:** `src/logging_store.py`, `src/config.py`, `evaluation/harness.py`

## Context

Every autonomous decision (classify, route, generate, validate) writes one record to a persistent log so that A8 reconciliation passes and NFR-04 (explainability) holds: a compliance auditor months later must be able to reconstruct why a specific response was sent. The store must be free, requires no service to run on the assessment machine, and must accept the pack's decision-log schema from the Governance Framework.

## Options considered

**A. SQLite (file-based).**
Standard-library. Setup Guide default. No service to start. Single file lives at `storage/decisions.db`. Full SQL over the schema, indexes on `ticket_id`, `stage`, `action_taken`.

**B. PostgreSQL.**
Concurrent-write support. Richer JSON operators for `alternatives`, `sources_used`, `guardrail_results` columns. Adds a service dependency on the assessment machine (either Docker or a local install). Setup Guide states: "Use PostgreSQL only if you have a specific reason."

**C. Append-only JSONL file.**
Trivially simple. No SQL, no queries. Reconciliation is a full-file scan. Fine at 700 tickets; scales poorly for later.

## Chosen

**Option A — SQLite at `storage/decisions.db`.**

## Rationale

- Setup Guide default; assessment machine has SQLite in the Python stdlib.
- Reconciliation (A8) is one SELECT query against an indexed table.
- Governance Framework's mandated schema (`decision_id`, `stage`, `prediction`, `confidence`, `sources_used JSON`, `guardrail_results JSON`, `prompt_version`, `requirement_ids`) fits SQLite comfortably; JSON columns are stringified.
- No service, no port, no credentials — nothing for the assessment machine to fail on.
- Under NFR-08 (free tier / cost-nothing), SQLite has zero infrastructure cost.

## Consequences

- Positive: no service dependency, minimal setup burden, easy to inspect in the report or video with a one-line `sqlite3 storage/decisions.db "SELECT..."`.
- Negative: single-writer. If we ever move to a concurrent-worker harness, we'll hit `SQLITE_BUSY`.
- Mitigation: harness is single-threaded per FR-21 ("unattended in one command"). Concurrency is a Week 2/3 optimization, not a Week 1 requirement.

## Revisit trigger

- If we adopt a multi-worker harness for latency reasons.
- If the decision log grows beyond ~1GB (unlikely; each row is a few KB, 700 tickets ~ 3MB).
- If the compliance officer requires a specific enterprise database for audit retention.

## Supersedes / superseded by

None.
