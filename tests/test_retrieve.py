"""Tests for src/retrieve.py — Chroma-backed passage retrieval.

Coverage per Sprint Plan B-06 definition of done:
  - happy path: returns ranked Passages with doc_id + score above threshold
  - empty list on: empty query, threshold filters everything, search fails
  - top_k respected
  - score ordering preserved (descending)
  - decision log written for every call (both retrieved and empty branches)
  - deterministic: same query + same stub -> same passages
  - Passage shape carries doc_id/score/text/title/category/chunk_text
"""
from __future__ import annotations

import sqlite3

import pytest

from src.retrieve import retrieve
from src.schema import Passage


# ─── helpers ─────────────────────────────────────────────────────────


def _stub(hits: list[tuple[str, dict, float]]):
    """Return a search stub that returns the given (text, metadata, score) list."""

    def _call(query: str, k: int) -> list[tuple[str, dict, float]]:
        return list(hits)[:k]

    return _call


def _raiser(exc: Exception):
    def _call(query: str, k: int) -> list[tuple[str, dict, float]]:
        raise exc

    return _call


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Fresh SQLite for the decision log; reset run_id state."""
    db_path = tmp_path / "decisions.db"
    monkeypatch.setattr("src.logging_store._DB_PATH", db_path)
    monkeypatch.setattr("src.logging_store._initialised", set())
    monkeypatch.setattr("src.logging_store._CURRENT_RUN_ID", None)
    from src.logging_store import init_db

    init_db()
    return db_path


# ─── happy path ──────────────────────────────────────────────────────


def test_returns_passages_ranked_by_score(db):
    """FR-06: passages come back with doc_id + score, ordered highest first."""
    hits = [
        ("**Auth failure guide** (authentication)\n\nSteps...", {
            "doc_id": "DOC-AUTH-001", "title": "Auth failure guide",
            "category": "authentication", "chunk_index": 0, "chunk_text": "Steps..."
        }, 0.92),
        ("**Password reset** (account)\n\nHow to...", {
            "doc_id": "DOC-ACCT-002", "title": "Password reset",
            "category": "account", "chunk_index": 0, "chunk_text": "How to..."
        }, 0.71),
    ]
    passages = retrieve("Cannot log in", ticket_id="T-1", search=_stub(hits), threshold=0.35)
    assert len(passages) == 2
    assert isinstance(passages[0], Passage)
    assert passages[0].doc_id == "DOC-AUTH-001"
    assert passages[0].score == 0.92
    assert passages[0].title == "Auth failure guide"
    assert passages[0].category == "authentication"
    assert passages[0].chunk_text == "Steps..."
    # Score-descending order preserved
    assert passages[0].score > passages[1].score


# ─── FR-07 threshold ────────────────────────────────────────────────


def test_below_threshold_passages_are_dropped(db):
    """FR-07: any passage below RETRIEVAL_THRESHOLD is filtered out."""
    hits = [
        ("A", {"doc_id": "DOC-A"}, 0.90),
        ("B", {"doc_id": "DOC-B"}, 0.40),
        ("C", {"doc_id": "DOC-C"}, 0.20),  # below 0.35 floor
    ]
    passages = retrieve("q", ticket_id="T-2", search=_stub(hits), threshold=0.35)
    doc_ids = [p.doc_id for p in passages]
    assert "DOC-C" not in doc_ids
    assert doc_ids == ["DOC-A", "DOC-B"]


def test_all_below_threshold_returns_empty_list(db):
    """FR-07: empty list — not None — when nothing crosses the threshold."""
    hits = [
        ("A", {"doc_id": "DOC-A"}, 0.10),
        ("B", {"doc_id": "DOC-B"}, 0.05),
    ]
    passages = retrieve("q", ticket_id="T-3", search=_stub(hits), threshold=0.35)
    assert passages == []
    assert isinstance(passages, list)  # not None


# ─── edge cases ──────────────────────────────────────────────────────


def test_empty_query_returns_empty_list(db):
    called = {"count": 0}

    def _tracking(query, k):
        called["count"] += 1
        return []

    passages = retrieve("", ticket_id="T-4", search=_tracking)
    assert passages == []
    # Empty query short-circuits before the search runs.
    assert called["count"] == 0


def test_whitespace_only_query_returns_empty_list(db):
    passages = retrieve("   \n\t  ", ticket_id="T-5", search=_stub([]))
    assert passages == []


def test_search_failure_returns_empty_list(db):
    """A11: any exception in the search path returns [] and logs, never raises."""
    passages = retrieve("q", ticket_id="T-6", search=_raiser(ConnectionError("boom")))
    assert passages == []


def test_top_k_respected_by_the_search_stub(db):
    """top_k is passed through to the search callable."""
    captured = {}

    def _spy(query, k):
        captured["k"] = k
        return []

    retrieve("q", top_k=3, ticket_id="T-7", search=_spy)
    assert captured["k"] == 3


# ─── decision log side effect ────────────────────────────────────────


def test_retrieval_writes_a_decision_log_row(db):
    """FR-20: every retrieval writes exactly one row to the decision log."""
    hits = [("A", {"doc_id": "DOC-A", "title": "T"}, 0.9)]
    retrieve("q", ticket_id="T-LOG", search=_stub(hits))
    with sqlite3.connect(db) as c:
        rows = c.execute(
            "SELECT ticket_id, stage, action_taken, prediction, threshold_applied, "
            "confidence, sources_used "
            "FROM decisions WHERE ticket_id = ?",
            ("T-LOG",),
        ).fetchall()
    assert len(rows) == 1
    ticket_id, stage, action, prediction, threshold, confidence, sources_used = rows[0]
    assert ticket_id == "T-LOG"
    assert stage == "retrieval"
    assert action == "retrieved"
    assert "DOC-A" in prediction
    assert threshold > 0
    assert confidence == 0.9
    assert "DOC-A" in sources_used


def test_empty_result_still_logs_a_decision_row(db):
    """A8: even 'no passages found' writes a decision log row so reconciliation
    can see the retrieval was attempted."""
    retrieve("q", ticket_id="T-EMPTY", search=_stub([]))
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT action_taken, prediction FROM decisions WHERE ticket_id = ?",
            ("T-EMPTY",),
        ).fetchone()
    assert row is not None
    action, prediction = row
    assert action == "empty"
    # Prediction is prefixed with the schema tag `top_doc_id=` in both branches,
    # so a log analyser can filter by prediction shape without parsing action.
    assert prediction == "top_doc_id=none"


def test_search_failure_logs_error_in_reason(db):
    retrieve("q", ticket_id="T-ERR", search=_raiser(RuntimeError("chroma unreachable")))
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT action_taken, reason FROM decisions WHERE ticket_id = ?",
            ("T-ERR",),
        ).fetchone()
    action, reason = row
    assert action == "empty"
    assert "search_error" in reason
    assert "RuntimeError" in reason


def test_empty_query_logs_empty_reason(db):
    retrieve("", ticket_id="T-EMPTYQ", search=_stub([]))
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT action_taken, reason FROM decisions WHERE ticket_id = ?",
            ("T-EMPTYQ",),
        ).fetchone()
    action, reason = row
    assert action == "empty"
    assert reason == "empty_query"


# ─── A11: malformed index metadata must not escape ───────────────────


def test_malformed_chunk_index_does_not_raise(db):
    """A11 regression: the Passage-building loop used to sit outside the
    try/except, so a chunk_index of "two" raised ValueError straight out of a
    function whose docstring promises it never raises.
    """
    hits = [("text", {"doc_id": "DOC-A", "chunk_index": "two"}, 0.9)]
    passages = retrieve("q", ticket_id="T-BADMETA", search=_stub(hits))
    assert len(passages) == 1
    assert passages[0].chunk_index == 0  # falls back, keeps the passage


def test_passage_without_doc_id_is_dropped(db):
    """A6: every citation must resolve to a retrieved passage. A passage with
    no doc_id cannot be cited, so emitting it would create an uncitable source.
    """
    hits = [
        ("good", {"doc_id": "DOC-A"}, 0.9),
        ("orphan", {"title": "no doc_id here"}, 0.8),
    ]
    passages = retrieve("q", ticket_id="T-NODOC", search=_stub(hits))
    assert [p.doc_id for p in passages] == ["DOC-A"]


# ─── ordering is enforced, not assumed ───────────────────────────────


def test_output_is_sorted_by_score_descending(db):
    """The docstring promises score-descending output. It used to inherit
    whatever order the backend returned."""
    hits = [
        ("mid", {"doc_id": "DOC-MID"}, 0.55),
        ("top", {"doc_id": "DOC-TOP"}, 0.95),
        ("low", {"doc_id": "DOC-LOW"}, 0.40),
    ]
    passages = retrieve("q", ticket_id="T-SORT", search=_stub(hits), threshold=0.35)
    assert [p.doc_id for p in passages] == ["DOC-TOP", "DOC-MID", "DOC-LOW"]
    assert [p.score for p in passages] == sorted((p.score for p in passages), reverse=True)


def test_below_threshold_hit_does_not_discard_later_good_hits(db):
    """Regression: the old `break` stopped at the first below-threshold hit, so
    on unsorted input a good passage after a weak one was silently dropped."""
    hits = [
        ("weak", {"doc_id": "DOC-WEAK"}, 0.20),
        ("strong", {"doc_id": "DOC-STRONG"}, 0.90),
    ]
    passages = retrieve("q", ticket_id="T-BREAK", search=_stub(hits), threshold=0.35)
    assert [p.doc_id for p in passages] == ["DOC-STRONG"]


# ─── A8: ticket_id is required, not defaulted ────────────────────────


def test_ticket_id_is_a_required_argument():
    """A8 regression: a default of "" let a caller log a row with an empty
    ticket_id, which reconcile() then reports as an extra and fails on."""
    with pytest.raises(TypeError):
        retrieve("q", search=_stub([]))  # type: ignore[call-arg]


# ─── determinism ─────────────────────────────────────────────────────


def test_same_query_same_stub_same_passages(db):
    """A5: retrieval is deterministic given a deterministic search callable."""
    hits = [
        ("A", {"doc_id": "DOC-A"}, 0.9),
        ("B", {"doc_id": "DOC-B"}, 0.7),
    ]
    a = retrieve("q", ticket_id="T-DET-A", search=_stub(hits))
    b = retrieve("q", ticket_id="T-DET-B", search=_stub(hits))
    # Same ranked passages, in the same order, with the same scores.
    assert [(p.doc_id, p.score) for p in a] == [(p.doc_id, p.score) for p in b]


# ─── Passage shape ───────────────────────────────────────────────────


def test_passage_carries_all_metadata_fields(db):
    """capstone-component-impl contract: every Passage carries doc_id, score,
    text, title. Also verify category/chunk_index/chunk_text propagate."""
    hits = [
        (
            "**Password reset guide** (authentication)\n\nSteps to reset...",
            {
                "doc_id": "DOC-AUTH-002",
                "title": "Password reset guide",
                "category": "authentication",
                "chunk_index": 2,
                "chunk_text": "Steps to reset...",
            },
            0.87,
        ),
    ]
    passages = retrieve("q", ticket_id="T-SHAPE", search=_stub(hits))
    p = passages[0]
    assert p.doc_id == "DOC-AUTH-002"
    assert p.score == 0.87
    assert p.text.startswith("**Password reset guide**")
    assert p.title == "Password reset guide"
    assert p.category == "authentication"
    assert p.chunk_index == 2
    assert p.chunk_text == "Steps to reset..."


def test_passage_missing_metadata_falls_back_to_empty_strings(db):
    """Robust to a metadata dict missing fields — the retriever doesn't crash,
    the passage just has empty defaults for the missing keys."""
    hits = [("passage text", {"doc_id": "DOC-X"}, 0.8)]  # no title, no category, no chunk_text
    passages = retrieve("q", ticket_id="T-MIN", search=_stub(hits))
    p = passages[0]
    assert p.doc_id == "DOC-X"
    assert p.title == ""
    assert p.category == ""
    assert p.chunk_index == 0
    assert p.chunk_text == ""
