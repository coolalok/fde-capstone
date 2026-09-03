"""Persistent decision log — SQLite by default.

Schema mirrors the Governance Framework's minimum record, flattened to
columns for query simplicity. Alternatives, sources_used, guardrail_results
and requirement_ids are stored as JSON strings inside single columns.

Every autonomous decision writes exactly one row here. The harness at
end-of-run reconciles logged decisions against tickets processed (A8).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from src.config import DATABASE_URL, DECISION_LOG_TIMEOUT_SECONDS
from src.metrics import DECISION_LOG_FAILURES

logger = logging.getLogger(__name__)

# Strip the sqlite:/// prefix for the raw path
_DB_PATH = Path(DATABASE_URL.replace("sqlite:///", ""))

# Paths whose schema has been created in this process. Keyed by path rather
# than a single boolean so a test that repoints _DB_PATH still gets its schema
# created on the new path.
_initialised: set[Path] = set()

# Operational failures: the log is momentarily unavailable. These are swallowed
# and reported (see log_decision). Everything else — sqlite3.ProgrammingError
# from a malformed statement, TypeError from an unserialisable field — is a
# programming error and MUST surface, per capstone-component-impl's rule that
# missing or malformed required fields are not A11 territory.
_OPERATIONAL_ERRORS = (sqlite3.OperationalError, OSError)

# The run_id stamped on every decision written in this process.
#
# The harness (evaluation/harness.py, B-19) calls set_run_id() once at the
# start of an invocation. All log_decision calls that follow inherit that
# value. Reconciliation queries scope by it, so a fresh harness run against
# a persistent decisions.db (the grading condition) counts only its own rows
# and not the dev+validation rows already in the file. Was Bug 2: reconcile
# saw every historical ticket and failed A8 on arrival.
_CURRENT_RUN_ID: Optional[str] = None

# Per-process fallback used when a caller (tests, ad-hoc scripts) writes
# without calling set_run_id() first. Generated once per process so all
# unscoped writes within the process collide into one bucket rather than
# spreading into many. Includes the PID and start timestamp for legibility.
_FALLBACK_RUN_ID = (
    f"unscoped-{os.getpid()}-"
    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id      TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    run_id           TEXT NOT NULL DEFAULT 'legacy',  -- scopes reconciliation; see set_run_id
    ticket_id        TEXT NOT NULL,
    -- stage is the pipeline step (classification / routing / generation / validation)
    stage            TEXT NOT NULL,
    input_summary    TEXT,
    model_name       TEXT,
    model_version    TEXT,
    prediction       TEXT,
    confidence       REAL,
    alternatives     TEXT,           -- JSON list
    sources_used     TEXT,           -- JSON list of {doc_id, score}
    threshold_applied REAL,
    -- action_taken carries either a routing outcome (auto_respond / escalate /
    -- block) or a stage outcome (classified / fallback / retrieved / generated
    -- / blocked). One column, two vocabularies, distinguished by `stage`.
    action_taken     TEXT NOT NULL,
    reason           TEXT NOT NULL,
    guardrail_results TEXT,          -- JSON dict
    prompt_version   TEXT,
    requirement_ids  TEXT            -- JSON list
);

CREATE INDEX IF NOT EXISTS idx_decisions_ticket ON decisions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_decisions_stage  ON decisions(stage);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action_taken);
-- NOTE: the run_id index is created in _migrate, not here — it must run AFTER
-- the ALTER TABLE that adds the column on a legacy DB. Putting it in SCHEMA
-- would fail on a pre-Bug-2 DB because the column doesn't exist yet when
-- executescript runs.
"""


def _migrate(c: sqlite3.Connection) -> None:
    """Bring a pre-Bug-2 decisions.db up to the current schema.

    On a legacy DB (created before Bug 2 was fixed): ALTER TABLE adds the
    run_id column with DEFAULT 'legacy' so historical rows can never collide
    with a real harness run.

    On a fresh DB (created by the SCHEMA above): the column already exists;
    the ALTER is skipped; only the index gets created.

    Both paths converge to the same final schema. Safe to call every open —
    both branches are idempotent.
    """
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(decisions)").fetchall()}
    if "run_id" not in existing_cols:
        c.execute(
            "ALTER TABLE decisions ADD COLUMN run_id TEXT NOT NULL DEFAULT 'legacy'"
        )
    # Idempotent index creation; covers the fresh-DB path too where the ALTER
    # is skipped but the index still needs to exist for the reconcile query.
    c.execute("CREATE INDEX IF NOT EXISTS idx_decisions_run ON decisions(run_id)")


def init_db() -> None:
    """Create the decisions table if it doesn't exist.

    Kept as an explicit entry point for scripts/verify_setup.py. Callers no
    longer have to remember it: _conn() creates the schema on first use of a
    path, so a fresh checkout works without a setup step.
    """
    with _conn():
        pass


def new_run_id(prefix: str = "run") -> str:
    """Generate a fresh run_id in the form ``<prefix>-<UTC>-<uuid>``.

    Format decisions worth calling out:
    - UTC timestamp keeps runs sortable in the log; a viewer sees runs in
      chronological order without a JOIN.
    - The trailing UUID slug means two runs kicked off in the same second
      (a CI matrix, say) don't collide.
    - Prefix lets a report separate harness runs from ad-hoc backfills:
      ``new_run_id("harness")``, ``new_run_id("backfill")``, etc.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def set_run_id(run_id: str) -> str:
    """Stamp every subsequent log_decision in this process with ``run_id``.

    The harness calls this once at the start of an invocation::

        run_id = set_run_id(new_run_id("harness"))
        # ... process tickets ...
        reconcile(ticket_ids, run_id=run_id)

    Returns the id so the caller can log or report it. Tests that need a
    fresh scope per case can call this in a fixture with a unique id.
    """
    global _CURRENT_RUN_ID
    _CURRENT_RUN_ID = run_id
    return run_id


def current_run_id() -> str:
    """Return the run_id log_decision will stamp on the next write.

    Falls back to the per-process ``_FALLBACK_RUN_ID`` when the harness
    hasn't called set_run_id() yet. That fallback is stable within the
    process, so ad-hoc scripts still get a consistent scope to reconcile
    against.
    """
    return _CURRENT_RUN_ID or _FALLBACK_RUN_ID


def clear_run_id() -> None:
    """Forget the current run_id. Mostly for tests; harness rarely needs this."""
    global _CURRENT_RUN_ID
    _CURRENT_RUN_ID = None


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Open the decision log, creating its schema on first use of the path."""
    path = _DB_PATH  # read at call time so tests can repoint the module global
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=DECISION_LOG_TIMEOUT_SECONDS)
    try:
        if path not in _initialised:
            # WAL lets the harness read while a write is in flight. Set before
            # executescript, which opens a transaction; journal_mode cannot
            # change inside one. CREATE ... IF NOT EXISTS makes this safe to
            # race with another process doing the same thing.
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            _migrate(c)  # brings a pre-Bug-2 DB up to the current schema
            # Commit the schema + migration explicitly. Without this, they sit
            # inside the caller's implicit transaction and would be rolled back
            # if the caller's INSERT raises (e.g. because the ALTER hadn't been
            # committed yet — the exact bug this comment exists to prevent).
            c.commit()
            _initialised.add(path)
        yield c
        c.commit()
    finally:
        c.close()


def log_decision(
    *,
    ticket_id: str,
    stage: str,
    action_taken: str,
    reason: str,
    run_id: Optional[str] = None,
    input_summary: str = "",
    model_name: str = "",
    model_version: str = "",
    prediction: str = "",
    confidence: float = 0.0,
    alternatives: list | None = None,
    sources_used: list | None = None,
    threshold_applied: float = 0.0,
    guardrail_results: dict | None = None,
    prompt_version: str = "",
    requirement_ids: list | None = None,
) -> Optional[str]:
    """Persist one decision. Returns the decision_id, or None if the write failed.

    Operational failure (locked database, full disk, unreadable path) returns
    None rather than raising: an unavailable log must not take the pipeline
    down with it. A programming error — a malformed statement, an
    unserialisable field — still raises, because that is a defect to fix, not
    a runtime condition to degrade around (A11 covers the latter only).

    But a None return is not nothing: FR-20 requires one row per decision, so
    None means the governance invariant was NOT met for this decision. The
    caller must not auto-respond on it — an unlogged reply is exactly what the
    autumn compliance review (EV-M5) has to be able to reconstruct. Callers
    signal this downstream; see ClassificationResult.decision_logged.
    """
    decision_id = f"DL-{uuid.uuid4()}"
    effective_run_id = run_id if run_id is not None else current_run_id()
    try:
        with _conn() as c:
            c.execute(
                """INSERT INTO decisions (
                decision_id, created_at, run_id, ticket_id, stage,
                input_summary, model_name, model_version,
                prediction, confidence, alternatives,
                sources_used, threshold_applied,
                action_taken, reason,
                guardrail_results, prompt_version, requirement_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    datetime.now(timezone.utc).isoformat(),
                    effective_run_id,
                    ticket_id, stage,
                    input_summary, model_name, model_version,
                    prediction, confidence, json.dumps(alternatives or []),
                    json.dumps(sources_used or []), threshold_applied,
                    action_taken, reason,
                    json.dumps(guardrail_results or {}), prompt_version,
                    json.dumps(requirement_ids or []),
                ),
            )
    except _OPERATIONAL_ERRORS as exc:
        # Deliberately NOT `except Exception`. A ProgrammingError (bad statement)
        # or TypeError (unserialisable field) is a defect in our code, and
        # capstone-component-impl is explicit that those must raise rather than
        # be absorbed as A11 degradation. Only "the log is briefly unavailable"
        # is swallowed here.
        logger.error(
            "decision_log.write_failed",
            extra={
                "ticket_id": ticket_id,
                "stage": stage,
                "action_taken": action_taken,
                "run_id": effective_run_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        DECISION_LOG_FAILURES.labels(stage=stage).inc()
        return None
    return decision_id


def reconcile(ticket_ids: list[str], run_id: Optional[str] = None) -> dict:
    """Count logged decisions against processed tickets, scoped to a run.

    A8 requires every ticket the harness processed to have a log row. This
    function reports the reconciliation for one run (the harness invocation
    that just finished processing ``ticket_ids``).

    ``run_id`` defaults to the current run_id (``set_run_id`` or the
    per-process fallback), which is what the harness wants after a normal
    invocation. Pass an explicit value to reconcile a past run.

    Was Bug 2: the pre-fix query was ``GROUP BY ticket_id`` with no scope,
    so on the grading machine (which loads its own persistent decisions.db
    across every test) the counts would include every dev and validation
    ticket the author had ever processed. Extras would flood the report
    and A8 would fail on arrival.
    """
    scope = run_id if run_id is not None else current_run_id()
    with _conn() as c:
        cur = c.execute(
            "SELECT ticket_id, COUNT(*) FROM decisions "
            "WHERE run_id = ? "
            "GROUP BY ticket_id",
            (scope,),
        )
        logged = dict(cur.fetchall())
    processed = set(ticket_ids)
    missing = [tid for tid in processed if tid not in logged]
    extra = [tid for tid in logged if tid not in processed]
    return {
        "run_id": scope,
        "tickets_processed": len(processed),
        "tickets_with_log": len(logged),
        "missing_from_log": missing,
        "extra_in_log": extra,
        "reconciles": len(missing) == 0 and len(extra) == 0,
    }
