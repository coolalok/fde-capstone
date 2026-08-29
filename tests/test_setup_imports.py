"""Import smoke tests — cheap check that every src module loads."""
import importlib

import pytest


@pytest.mark.parametrize("module", [
    "src.config",
    "src.logging_store",
    "src.metrics",
])
def test_import(module: str) -> None:
    importlib.import_module(module)


def test_decision_log_init(tmp_path, monkeypatch) -> None:
    """Init the DB in a temp dir and confirm the schema is there."""
    import sqlite3
    monkeypatch.setattr(
        "src.logging_store._DB_PATH",
        tmp_path / "test_decisions.db",
    )
    from src.logging_store import init_db
    init_db()
    with sqlite3.connect(tmp_path / "test_decisions.db") as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='decisions'"
        ).fetchall()
        assert rows == [("decisions",)]


def test_log_decision_writes_row(tmp_path, monkeypatch) -> None:
    import sqlite3
    monkeypatch.setattr(
        "src.logging_store._DB_PATH",
        tmp_path / "test_decisions.db",
    )
    from src.logging_store import init_db, log_decision
    init_db()
    decision_id = log_decision(
        ticket_id="TEST-01",
        stage="classification",
        action_taken="auto_respond",
        reason="ok",
        confidence=0.9,
    )
    assert decision_id.startswith("DL-")
    with sqlite3.connect(tmp_path / "test_decisions.db") as c:
        row = c.execute("SELECT ticket_id, action_taken FROM decisions").fetchone()
        assert row == ("TEST-01", "auto_respond")
