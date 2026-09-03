# D-03b — What happens when a decision-log write fails (extends D-03)

**Status:** Accepted. Extends D-03.
**Date:** 2026-09-03
**Decider:** Alok Kulkarni
**Constrains:** FR-20 (one decision-log record per decision), A8 (reconciliation), A11 (graceful degradation)
**Affects:** `src/logging_store.py`, `src/classify.py`, `src/schema.py` (`ClassificationResult.decision_logged`), `src/route.py` (B-15, must consume the flag)

## Context

D-03 chose SQLite at `storage/decisions.db` as the decision-log store. It did not say what the pipeline does when a write to that store fails.

Until 2026-09-03 the answer was accidental rather than designed: `log_decision` had no error handling and `classify()` called it outside its own try/except, so any log failure propagated out of a function whose docstring promised it never raised. On a fresh checkout nothing called `init_db()`, so the very first ticket died with `sqlite3.OperationalError: no such table: decisions`. That is an A1 failure (clean checkout) and an A11 failure (graceful degradation) reached by the same defect.

Fixing the crash forces the underlying question. Three things can be true at once and only two of them can be satisfied:

1. FR-20 requires a log row for every decision.
2. A11 requires the pipeline not to crash on an infrastructure failure.
3. EV-M5 requires every action the system takes to be explainable to the autumn compliance review.

If the log is unavailable, we cannot have all three. Something must give.

## Options considered

**A. Raise — a log failure kills the ticket.**
Maximally faithful to FR-20: no decision is ever taken without a record. But it converts a transient SQLite lock into a failed ticket, and in a harness run one locked write aborts the run. Fails A11 for a condition that is by definition recoverable.

**B. Swallow silently — log the failure to stderr and carry on.**
Maximally faithful to A11: nothing takes the pipeline down. But the decision still gets acted on, and if that action is `auto_respond` a reply reaches a customer with no record that the system ever made a choice. That is precisely the artefact the compliance review asks for and cannot be reconstructed after the fact. Also hides the failure from A8, which would report a gap at end of run with no diagnostic trail.

**C. Swallow, report, and mark the decision as unlogged so the router refuses to auto-respond on it.**
The write failure is non-fatal, so the run continues (A11). The failure is recorded at ERROR level and counted in `decision_log_write_failures_total{stage}` so A8 gaps are diagnosable rather than mysterious. And because the decision carries a flag saying its governance record is missing, the router escalates it to a human instead of sending an unlogged automated reply — so FR-20's *purpose* is preserved even when its mechanism failed.

## Chosen

**Option C.** Concretely:

- `log_decision` returns `Optional[str]` — the `decision_id`, or `None` when the write failed. It absorbs operational failures only (`sqlite3.OperationalError`, `OSError`).
- A programming error (`sqlite3.ProgrammingError` from a malformed statement, `TypeError` from an unserialisable field) still raises. Per `capstone-component-impl`, a malformed record is a defect to fix, not a runtime condition to degrade around; A11 covers the latter only.
- `ClassificationResult.decision_logged: bool` is `False` when the row did not land.
- `src/route.py` (B-15) MUST treat `decision_logged is False` as a forced escalation, evaluated before the confidence threshold.
- The schema is created lazily on first connection, so a clean checkout works with no setup step (A1).

## Rationale

The failure policy belongs in `logging_store`, not at each call site. Four components will call `log_decision` (classify, route, generate, guardrails); four copies of the same try/except is four chances to get the governance rule wrong, and a component that forgets it fails silently in the direction that sends unlogged replies to customers.

Option C is the only one of the three that keeps the property the log exists for. FR-20 is not an end in itself — it exists so that EV-M5's auditor can reconstruct any action the system took. Option A protects that property by refusing to run; option B abandons it; option C preserves it by degrading the *action* (escalate instead of auto-respond) rather than the *record*.

The narrow exception tuple matters more than it looks. `except Exception` here would have absorbed our own bugs — a mistyped column list, a non-serialisable object in `alternatives` — and reported them as infrastructure trouble while silently dropping every row. The A8 reconciliation would then fail at end of run with a cause that had already been swallowed 120 times.

## Consequences

- Positive: a clean checkout runs (A1). A transient lock degrades one ticket to escalation instead of aborting a run (A11). Unlogged decisions cannot reach a customer as automated replies (EV-M5, FR-20's purpose).
- Positive: the failure is visible — ERROR log plus a Prometheus counter, which is the first real consumer of `src/metrics.py`.
- Negative: `log_decision` now has two success-ish return states, and every caller must check for `None`. Missing that check is a silent governance hole. Mitigated by the flag living on the result object, so the router reads it rather than each caller re-deriving it.
- Negative: a sustained log outage silently converts the system into escalate-everything. That is the correct failure direction, but it looks like a quality regression rather than an infrastructure one until someone reads the counter. The metrics dashboard needs the counter on it (B-25).
- Carried debt: `route.py` does not exist yet, so the `decision_logged` flag currently has no consumer. B-15's definition of done must include it or this ADR is only half-implemented.

## Evidence

- **EV-M5** — "a compliance review is coming in the autumn; every action the system takes has to be explainable" (Marcus, `workbooks/discovery_notes.md`). This is what rules out option B.
- **A8 / A11** — Build Specification acceptance criteria; the two constraints in tension here.
- **`capstone-component-impl`**, logging_store section — "missing required fields are a programming error and should raise (this is not user-facing A11 territory)". This is what sets the boundary of the exception tuple.

## Revisit trigger

- If `decision_log_write_failures_total` is non-zero on any full validation run, the SQLite configuration (WAL, busy timeout) is inadequate for the harness's concurrency and the store choice in D-03 itself should be reopened.
- If a harness run ever completes with `reconciles: true` while the failure counter is non-zero, the reconciliation query is not scoped correctly and this ADR's assumption that A8 catches unlogged decisions is wrong.
- If the router's forced-escalation rule causes escalation rate to exceed the 56.2% historical baseline (EV-DATA-01) during a run with no log failures, the flag is being set spuriously.

## Supersedes / superseded by

None. Extends D-03, which stays in force on the store choice itself.
