"""Tests for urgency prioritisation in the harness (D-17).

Per capstone-test-writer §The three cases: happy path (the queue is ordered),
adversarial (a ticket the pre-pass could not classify, an unseen urgency
string), and degraded provider (the pre-pass classifier raising).

What these protect: prioritisation is only observable on a run that does NOT
finish, which is exactly the run nobody is watching. If the order silently
reverts to file order, or the pre-pass double-bills a ticket, no completed run
would show it — the metrics report is identical in any order.
"""
from __future__ import annotations

import json

import pytest

from evaluation.harness import (PriorClassification, URGENCY_RANK, _urgency_accuracy,
                                classify_all, main, prioritise, process_ticket)
from src.schema import ClassificationResult

from tests.test_harness_smoke import SMOKE_TICKETS, FakeModelClient, _no_retrieval  # noqa: F401


def _prior(urgency: str, seconds: float = 0.0,
           calls: list | None = None) -> PriorClassification:
    return PriorClassification(
        result=ClassificationResult(intent="onboarding", urgency=urgency,
                                    confidence=0.9),
        seconds=seconds,
        calls=calls if calls is not None else [],
    )


def _tickets(*ids: str) -> list[dict]:
    return [{"ticket_id": i, "channel": "email", "body": "x"} for i in ids]


# ─── ordering ────────────────────────────────────────────────────────


def test_high_urgency_tickets_are_worked_first():
    tickets = _tickets("T-low", "T-high", "T-medium")
    prior = {"T-low": _prior("low"), "T-high": _prior("high"),
             "T-medium": _prior("medium")}
    assert [t["ticket_id"] for t in prioritise(tickets, prior)] == [
        "T-high", "T-medium", "T-low"]


def test_order_within_an_urgency_band_is_file_order():
    """Stable sort. Without it, two runs of the same file would disagree on
    which of two equally urgent tickets a killed run had reached (A5)."""
    tickets = _tickets("T1", "T2", "T3", "T4")
    prior = {t: _prior("high") for t in ("T1", "T2", "T3", "T4")}
    assert [t["ticket_id"] for t in prioritise(tickets, prior)] == [
        "T1", "T2", "T3", "T4"]


def test_prioritise_does_not_drop_or_duplicate_tickets():
    tickets = _tickets("T1", "T2", "T3")
    prior = {"T1": _prior("low"), "T3": _prior("high")}
    out = prioritise(tickets, prior)
    assert sorted(t["ticket_id"] for t in out) == ["T1", "T2", "T3"]
    assert len(out) == 3


def test_a_ticket_missing_from_the_pre_pass_ranks_medium():
    """A pre-pass failure must not promote or demote a ticket. `medium` is the
    rank the unknown-fallback carries, so a failed ticket sorts where an
    unclassifiable one would."""
    tickets = _tickets("T-low", "T-unseen", "T-high")
    prior = {"T-low": _prior("low"), "T-high": _prior("high")}
    assert [t["ticket_id"] for t in prioritise(tickets, prior)] == [
        "T-high", "T-unseen", "T-low"]


def test_an_unrecognised_urgency_string_ranks_medium():
    """The classifier validates urgency against VALID_URGENCIES, but the sort
    key must not raise on a value that reaches it another way."""
    tickets = _tickets("T-weird", "T-high")
    prior = {"T-weird": _prior("critical"), "T-high": _prior("high")}
    assert [t["ticket_id"] for t in prioritise(tickets, prior)] == ["T-high", "T-weird"]
    assert set(URGENCY_RANK) == {"high", "medium", "low"}


# ─── the pre-pass ────────────────────────────────────────────────────


def test_classify_all_returns_one_entry_per_ticket(db, _no_retrieval):  # noqa: F811
    prior = classify_all(SMOKE_TICKETS, call_model=FakeModelClient())
    assert set(prior) == {t["ticket_id"] for t in SMOKE_TICKETS}
    assert all(p.seconds >= 0 for p in prior.values())


def test_classify_all_survives_a_classifier_that_raises(db, monkeypatch):
    """Degraded provider (A11/FR-23). classify() returns a fallback rather than
    raising, but a fault in the surrounding ingest or timing must not end the
    run before a single row has been written."""
    import evaluation.harness as h

    def explode(ticket, **kw):
        if ticket.ticket_id == "SMOKE-02":
            raise RuntimeError("provider unreachable")
        return ClassificationResult(intent="onboarding", urgency="high", confidence=0.9)

    monkeypatch.setattr(h, "classify", explode)
    prior = classify_all(SMOKE_TICKETS)
    assert "SMOKE-02" not in prior, "the failed ticket is simply absent"
    assert len(prior) == 2, "the other two still classified"
    # And it still appears in the queue, ranked medium.
    assert len(prioritise(SMOKE_TICKETS, prior)) == 3


def test_classify_all_attributes_tokens_to_the_right_ticket(db, monkeypatch):
    """usage.drain() is global. Without a drain per ticket the first ticket in
    the pre-pass would carry every later ticket's tokens."""
    import evaluation.harness as h
    from src import usage

    def record_one(ticket, **kw):
        usage.record("classification", "gpt-4o-mini",
                     {"prompt_tokens": 10, "completion_tokens": 5})
        return ClassificationResult(intent="onboarding", urgency="high", confidence=0.9)

    monkeypatch.setattr(h, "classify", record_one)
    prior = classify_all(SMOKE_TICKETS)
    assert [len(p.calls) for p in prior.values()] == [1, 1, 1]


# ─── phase 2 reuses phase 1 rather than paying twice ─────────────────


def test_a_supplied_classification_is_not_recomputed(db, _no_retrieval, monkeypatch):  # noqa: F811
    """The whole point of the two-phase design: prioritising a run must not
    cost an extra classifier call per ticket."""
    import evaluation.harness as h

    calls: list[str] = []

    def counting_classify(ticket, **kw):
        calls.append(ticket.ticket_id)
        return ClassificationResult(intent="onboarding", urgency="low", confidence=0.9)

    monkeypatch.setattr(h, "classify", counting_classify)
    row = process_ticket(SMOKE_TICKETS[0], call_model=FakeModelClient(),
                         prior=_prior("high"))
    assert calls == [], "classify was called again"
    assert row["urgency"] == "high", "the row carries the pre-pass verdict"


def test_the_pre_pass_cost_and_latency_stay_on_the_ticket(db, _no_retrieval):  # noqa: F811
    """A prioritised run must not report a cheaper, faster pipeline than the
    same work unprioritised. process_ticket drains usage on entry, so the
    pre-pass call has to be carried in explicitly."""
    call = {"stage": "classification", "model": "gpt-4o-mini",
            "prompt_tokens": 100, "completion_tokens": 20, "cached": False,
            "cost_usd": 0.0}
    row = process_ticket(SMOKE_TICKETS[0], call_model=FakeModelClient(),
                         prior=_prior("high", seconds=2.5, calls=[call]))
    assert row["stage_seconds"]["classification"] == 2.5
    assert row["latency_seconds"] >= 2.5, "pre-pass time is part of the ticket"
    assert call in row["usage"]["per_call"]
    assert row["usage"]["prompt_tokens"] >= 100


def test_prioritised_and_unprioritised_rows_agree(db, _no_retrieval, monkeypatch):  # noqa: F811
    """Ordering changes which tickets a partial run covers, nothing else. The
    same ticket must produce the same row either way."""
    import evaluation.harness as h

    monkeypatch.setattr(
        h, "classify",
        lambda ticket, **kw: ClassificationResult(intent="onboarding", urgency="high",
                                                  confidence=0.9))
    plain = process_ticket(SMOKE_TICKETS[0], call_model=FakeModelClient())
    with_prior = process_ticket(SMOKE_TICKETS[0], call_model=FakeModelClient(),
                                prior=_prior("high"))
    for field in ("intent", "urgency", "confidence", "decision", "trigger",
                  "citations", "answer"):
        assert plain[field] == with_prior[field], field


# ─── the CLI contract ────────────────────────────────────────────────


@pytest.fixture
def _fake_pipeline(monkeypatch):
    """Run main() end to end with the fake client threaded through."""
    import evaluation.harness as h

    monkeypatch.setattr(
        h, "classify",
        lambda ticket, **kw: ClassificationResult(
            intent="onboarding",
            urgency={"SMOKE-01": "medium", "SMOKE-02": "high",
                     "SMOKE-03": "low"}[ticket.ticket_id],
            confidence=0.9))
    monkeypatch.setattr(
        h, "process_ticket",
        lambda raw, **kw: process_ticket(raw, call_model=FakeModelClient(),
                                         **{k: v for k, v in kw.items()
                                            if k != "call_model"}))


def _run(tmp_path, extra: list[str]) -> list[str]:
    src = tmp_path / "in.json"
    src.write_text(json.dumps(SMOKE_TICKETS))
    out = tmp_path / "out"
    assert main(["--input", str(src), "--output", str(out)] + extra) == 0
    return [json.loads(line)["ticket_id"]
            for line in (out / "results.jsonl").read_text().strip().splitlines()]


def test_the_default_run_is_ordered_by_urgency(db, _no_retrieval, _fake_pipeline,  # noqa: F811
                                               tmp_path):
    assert _run(tmp_path, []) == ["SMOKE-02", "SMOKE-01", "SMOKE-03"]


def test_no_prioritize_restores_file_order(db, _no_retrieval, _fake_pipeline,  # noqa: F811
                                           tmp_path):
    """Every run committed under evaluation/results/ was produced in file
    order. --no-prioritize is how those stay reproducible."""
    assert _run(tmp_path, ["--no-prioritize"]) == ["SMOKE-01", "SMOKE-02", "SMOKE-03"]


def test_every_ticket_is_processed_exactly_once_when_prioritised(
        db, _no_retrieval, _fake_pipeline, tmp_path):  # noqa: F811
    """A9: the full set runs. Reordering must not drop the tail."""
    assert sorted(_run(tmp_path, [])) == ["SMOKE-01", "SMOKE-02", "SMOKE-03"]


# ─── the metric that makes the ordering checkable ────────────────────


def test_urgency_accuracy_scores_predictions_against_labels():
    truth = {"T1": {"urgency": "high"}, "T2": {"urgency": "high"},
             "T3": {"urgency": "low"}, "T4": {"urgency": "medium"},
             "T5": {}}
    rows = [{"ticket_id": "T1", "urgency": "high"},
            {"ticket_id": "T2", "urgency": "low"},
            {"ticket_id": "T3", "urgency": "low"},
            {"ticket_id": "T4", "urgency": "high"},
            {"ticket_id": "T5", "urgency": "high"}]
    m = _urgency_accuracy(rows, truth)
    assert m["n"] == 4, "the unlabelled ticket is not scored"
    # _pct returns a proportion, as every other metric in this report does.
    assert m["accuracy"] == 0.5
    assert m["high_recall"] == 0.5
    assert m["high_called_low"] == 1
    assert m["confusion"]["high"] == {"high": 1, "low": 1}


def test_urgency_accuracy_is_empty_without_labels():
    """The hidden evaluation set may carry no labels; their absence degrades
    the report, not the run."""
    m = _urgency_accuracy([{"ticket_id": "T1", "urgency": "high"}], {})
    assert m["n"] == 0
    assert m["accuracy"] is None, "an accuracy over nothing is undefined, not 0%"
    assert m["high_recall"] is None
    assert m["confusion"] == {}


def test_high_recall_is_undefined_when_no_ticket_is_labelled_high():
    """0.0 here would read as the classifier missing every urgent ticket, which
    is exactly the failure D-17 exists to catch — so it must not be printed
    when there was no urgent ticket to find."""
    m = _urgency_accuracy([{"ticket_id": "T1", "urgency": "high"}],
                          {"T1": {"urgency": "low"}})
    assert m["n"] == 1 and m["accuracy"] == 0.0, "a real miss is still 0%"
    assert m["high_recall"] is None
    assert m["high_called_low"] == 0
