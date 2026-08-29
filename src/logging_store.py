"""Persistent decision log — SQLite by default.

Schema mirrors the Governance Framework's minimum record, flattened to
columns for query simplicity. Alternatives, sources_used, guardrail_results
and requirement_ids are stored as JSON strings inside single columns.

Every autonomous decision writes exactly one row here. The harness at
end-of-run reconciles logged decisions against tickets processed (A8).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.config import DATABASE_URL

# Strip the sqlite:/// prefix for the raw path
_DB_PATH = Path(DATABASE_URL.replace("sqlite:///", ""))

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id      TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    ticket_id        TEXT NOT NULL,
    stage            TEXT NOT NULL,  -- classification | routing | generation | validation
    input_summary    TEXT,
    model_name       TEXT,
    model_version    TEXT,
    prediction       TEXT,
    confidence       REAL,
    alternatives     TEXT,           -- JSON list
    sources_used     TEXT,           -- JSON list of {doc_id, score}
    threshold_applied REAL,
    action_taken     TEXT NOT NULL,  -- auto_respond | escalate | block
    reason           TEXT NOT NULL,
    guardrail_results TEXT,          -- JSON dict
    prompt_version   TEXT,
    requirement_ids  TEXT            -- JSON list
);

CREATE INDEX IF NOT EXISTS idx_decisions_ticket ON decisions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_decisions_stage  ON decisions(stage);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action_taken);
"""


def init_db() -> None:
    """Create the decisions table if it doesn't exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    try:
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
) -> str:
    """Persist one decision. Returns the decision_id."""
    decision_id = f"DL-{uuid.uuid4()}"
    with _conn() as c:
        c.execute(
            """INSERT INTO decisions (
                decision_id, created_at, ticket_id, stage,
                input_summary, model_name, model_version,
                prediction, confidence, alternatives,
                sources_used, threshold_applied,
                action_taken, reason,
                guardrail_results, prompt_version, requirement_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                datetime.now(timezone.utc).isoformat(),
                ticket_id, stage,
                input_summary, model_name, model_version,
                prediction, confidence, json.dumps(alternatives or []),
                json.dumps(sources_used or []), threshold_applied,
                action_taken, reason,
                json.dumps(guardrail_results or {}), prompt_version,
                json.dumps(requirement_ids or []),
            ),
        )
    return decision_id


def reconcile(ticket_ids: list[str]) -> dict:
    """Count logged decisions against processed tickets. A8 reconciliation."""
    with _conn() as c:
        cur = c.execute(
            "SELECT ticket_id, COUNT(*) FROM decisions GROUP BY ticket_id"
        )
        logged = dict(cur.fetchall())
    processed = set(ticket_ids)
    missing = [tid for tid in processed if tid not in logged]
    extra = [tid for tid in logged if tid not in processed]
    return {
        "tickets_processed": len(processed),
        "tickets_with_log": len(logged),
        "missing_from_log": missing,
        "extra_in_log": extra,
        "reconciles": len(missing) == 0 and len(extra) == 0,
    }
