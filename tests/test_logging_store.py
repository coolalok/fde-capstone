"""Tests for src/logging_store — the decision log's run scoping and A8 reconciliation.

Specifically covers the Bug 2 fix: reconcile() must scope to the current run,
so a fresh harness invocation on a persistent decisions.db (the grading
condition) counts only its own rows and not the dev + validation rows that
were already in the file.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import logging_store as ls
from src.logging_store import (
    clear_run_id,
    current_run_id,
    init_db,
    log_decision,
    new_run_id,
    reconcile,
    set_run_id,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point _DB_PATH at a fresh SQLite file and reset the process-level run_id state."""
    path = tmp_path / "decisions.db"
    monkeypatch.setattr("src.logging_store._DB_PATH", path)
    monkeypatch.setattr("src.logging_store._initialised", set())
    monkeypatch.setattr("src.logging_store._CURRENT_RUN_ID", None)
    init_db()
    return path


def _write(ticket_id: str, run_id=None, stage: str = "classification") -> None:
    """Write one decision — keeps each test's boilerplate small."""
    log_decision(
        ticket_id=ticket_id,
        stage=stage,
        action_taken="classified",
        reason="ok",
        run_id=run_id,
    )


# ─── run_id API ──────────────────────────────────────────────────────


def test_new_run_id_is_unique_and_carries_prefix(db):
    """new_run_id returns a distinct id each call and prefixes are preserved.

    Not asserting lexical-order-matches-creation-order here: three calls in the
    same second share their timestamp portion, so ordering falls to the random
    UUID suffix. Uniqueness plus the prefix contract are what callers rely on.
    """
    ids = [new_run_id("harness") for _ in range(3)]
    assert len(set(ids)) == 3
    assert all(i.startswith("harness-") for i in ids)


def test_set_run_id_is_read_back_by_current_run_id(db):
    rid = set_run_id("harness-test-001")
    assert rid == "harness-test-001"
    assert current_run_id() == "harness-test-001"


def test_current_run_id_falls_back_when_unset(db):
    """Ad-hoc scripts and tests that never call set_run_id() still get a stable id."""
    clear_run_id()
    fallback = current_run_id()
    # Fallback carries the process id so it's inspectable when someone finds it in the log.
    assert fallback.startswith("unscoped-")
    # Stable within the process.
    assert current_run_id() == fallback


# ─── reconcile is scoped ─────────────────────────────────────────────


def test_reconcile_only_counts_current_run(db):
    """The Bug 2 reproduction: two 'harness' invocations against the same DB.

    Reconcile after run 2 must NOT surface run 1's ticket ids as extra_in_log.
    """
    # Run 1 — dev tickets
    run1 = set_run_id("harness-run-1")
    _write("DEV-0001")
    _write("DEV-0002")

    r1_report = reconcile(["DEV-0001", "DEV-0002"], run_id=run1)
    assert r1_report["reconciles"] is True
    assert r1_report["extra_in_log"] == []
    assert r1_report["missing_from_log"] == []
    assert r1_report["run_id"] == run1

    # Run 2 — hidden set, same persistent DB
    run2 = set_run_id("harness-run-2")
    _write("HIDDEN-A")
    _write("HIDDEN-B")

    r2_report = reconcile(["HIDDEN-A", "HIDDEN-B"], run_id=run2)
    assert r2_report["reconciles"] is True, (
        "Bug 2 regression: reconcile is not scoping to run_id"
    )
    assert r2_report["extra_in_log"] == []
    assert r2_report["missing_from_log"] == []
    assert r2_report["run_id"] == run2


def test_reconcile_defaults_to_current_run(db):
    """Called without an explicit run_id, reconcile scopes to the currently-set one."""
    rid = set_run_id("harness-default-scope")
    _write("T-1")
    _write("T-2")
    report = reconcile(["T-1", "T-2"])  # no run_id argument
    assert report["reconciles"] is True
    assert report["run_id"] == rid


def test_reconcile_finds_missing_within_the_scoped_run(db):
    """A ticket the harness said it processed but never got a log row → missing_from_log."""
    rid = set_run_id("harness-missing-check")
    _write("T-1")
    # T-2 skipped on purpose
    report = reconcile(["T-1", "T-2"], run_id=rid)
    assert report["reconciles"] is False
    assert report["missing_from_log"] == ["T-2"]
    assert report["extra_in_log"] == []


def test_reconcile_flags_extras_only_within_the_scoped_run(db):
    """An extra ticket in the log within THIS run (not from a previous run) shows up as extra."""
    set_run_id("harness-extras-in-scope")
    _write("T-1")
    _write("T-STRAY")  # written in the same run but not in the expected list
    report = reconcile(["T-1"])
    assert report["reconciles"] is False
    assert report["extra_in_log"] == ["T-STRAY"]


def test_reconcile_ignores_a_completely_different_run(db):
    """A cross-run reconcile against the wrong scope reports no matches — evidence
    that the scoping is a filter, not an ordering."""
    set_run_id("harness-A")
    _write("A-1")
    set_run_id("harness-B")
    _write("B-1")

    report_wrong_scope = reconcile(["A-1"], run_id="harness-B")
    assert report_wrong_scope["reconciles"] is False
    assert report_wrong_scope["missing_from_log"] == ["A-1"]
    assert report_wrong_scope["extra_in_log"] == ["B-1"]


# ─── legacy DB migration ─────────────────────────────────────────────


def test_legacy_db_migration_adds_run_id_column(tmp_path, monkeypatch):
    """A decisions.db that predates Bug 2 (no run_id column) is upgraded on next open."""
    legacy_path = tmp_path / "legacy.db"

    # Build a decisions table that mirrors the exact pre-Bug-2 schema — every
    # column current code writes, minus run_id. A test that used a stripped
    # subset would exercise a migration on a schema that never existed in the
    # wild and would fail here for the wrong reason.
    with sqlite3.connect(legacy_path) as c:
        c.executescript(
            """
            CREATE TABLE decisions (
                decision_id      TEXT PRIMARY KEY,
                created_at       TEXT NOT NULL,
                ticket_id        TEXT NOT NULL,
                stage            TEXT NOT NULL,
                input_summary    TEXT,
                model_name       TEXT,
                model_version    TEXT,
                prediction       TEXT,
                confidence       REAL,
                alternatives     TEXT,
                sources_used     TEXT,
                threshold_applied REAL,
                action_taken     TEXT NOT NULL,
                reason           TEXT NOT NULL,
                guardrail_results TEXT,
                prompt_version   TEXT,
                requirement_ids  TEXT
            );
            INSERT INTO decisions (
                decision_id, created_at, ticket_id, stage,
                action_taken, reason
            ) VALUES (
                'DL-old-1', '2026-08-30T00:00:00Z', 'OLD-1',
                'classification', 'classified', 'ok'
            );
            """
        )

    # Point the module at the legacy DB and force _conn to re-initialise.
    monkeypatch.setattr("src.logging_store._DB_PATH", legacy_path)
    monkeypatch.setattr("src.logging_store._initialised", set())
    monkeypatch.setattr("src.logging_store._CURRENT_RUN_ID", None)

    # First open triggers _migrate.
    set_run_id("harness-post-migration")
    _write("NEW-1")

    # Now verify: the legacy row got run_id='legacy'; the new row got the harness id.
    with sqlite3.connect(legacy_path) as c:
        rows = dict(
            c.execute("SELECT ticket_id, run_id FROM decisions").fetchall()
        )
    assert rows == {
        "OLD-1": "legacy",
        "NEW-1": "harness-post-migration",
    }

    # And a reconcile scoped to the harness run does NOT surface the legacy row.
    report = reconcile(["NEW-1"], run_id="harness-post-migration")
    assert report["reconciles"] is True
    assert report["extra_in_log"] == []


# ─── log_decision picks up current_run_id when no run_id is passed ──


def test_log_decision_uses_current_run_id_by_default(db):
    """A classify()-style call that doesn't pass run_id stamps the current one."""
    rid = set_run_id("harness-picks-up-default")
    _write("T-DEFAULT")
    with sqlite3.connect(db) as c:
        stored = c.execute(
            "SELECT run_id FROM decisions WHERE ticket_id = ?", ("T-DEFAULT",)
        ).fetchone()
    assert stored == (rid,)


def test_log_decision_explicit_run_id_wins_over_current(db):
    """A caller can pass an explicit run_id (e.g. a backfill) and it overrides the current."""
    set_run_id("harness-A")
    _write("T-BACKFILL", run_id="backfill-2026-09")
    with sqlite3.connect(db) as c:
        stored = c.execute(
            "SELECT run_id FROM decisions WHERE ticket_id = ?", ("T-BACKFILL",)
        ).fetchone()
    assert stored == ("backfill-2026-09",)
