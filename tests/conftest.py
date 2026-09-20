"""Shared pytest fixtures.

Cross-cutting fixtures live here rather than in one component's test file, per
capstone-test-writer. Every component writes to the decision log, so the two
decision-log fixtures below are needed by test_classify, and will be needed by
test_route, test_generate and test_guardrails as those land.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_shared_model_cache(tmp_path, monkeypatch):
    """Every test runs with the model-response cache OFF.

    Two reasons, both found the hard way when the cache landed. A test that
    stubs the provider would otherwise WRITE its fake reply into
    storage/model_cache, where a later live run could serve it as if the model
    had said it. And tests that assert "the provider was called with X" start
    failing as soon as an earlier test has cached the same prompt, which showed
    up as 6 to 25 failures depending on test order.

    Tests about the cache itself opt back in via their own fixture.
    """
    import src.model_cache as model_cache

    monkeypatch.setattr(model_cache, "MODEL_CACHE_DISABLED", True)
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DIR", str(tmp_path / "model_cache"))


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
