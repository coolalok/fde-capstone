"""Shared pytest fixtures.

Cross-cutting fixtures live here rather than in one component's test file, per
capstone-test-writer. Every component writes to the decision log, so the two
decision-log fixtures below are needed by test_classify, and will be needed by
test_route, test_generate and test_guardrails as those land.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the decision log at a temp SQLite db and initialise the schema."""
    db_path = tmp_path / "decisions.db"
    monkeypatch.setattr("src.logging_store._DB_PATH", db_path)
    from src.logging_store import init_db

    init_db()
    return db_path


@pytest.fixture
def uninitialised_db(tmp_path, monkeypatch):
    """A decision-log path whose schema has deliberately NOT been created.

    This is the state of a fresh checkout: nothing on the production path calls
    init_db(). Do not add an init_db() call here — that is what this fixture
    exists to reproduce.
    """
    db_path = tmp_path / "fresh" / "decisions.db"
    monkeypatch.setattr("src.logging_store._DB_PATH", db_path)
    return db_path
