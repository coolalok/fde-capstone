"""The calibration set must be reproducible, exclude the judge's worked examples,
cover the hard strata, and never be overwritten once a human has scored it.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import pytest

from evaluation.judge_calibration import (
    DIMENSIONS,
    FEW_SHOT_TICKETS,
    N_ITEMS,
    SMALL_STRATUM,
    has_human_scores,
    select_ticket_ids,
    stratum,
)

TICKETS = {t["ticket_id"]: t for t in json.load(open("data/validation_tickets.json"))}
ROWS = [json.loads(line) for line in
        open("evaluation/results/b21_openai_80_20260914/results.jsonl")]
FIXTURE = Path("tests/fixtures/judge_calibration.json")


def test_selection_is_deterministic_and_the_right_size():
    a, b = select_ticket_ids(ROWS, TICKETS), select_ticket_ids(ROWS, TICKETS)
    assert a == b and len(a) == N_ITEMS and len(set(a)) == N_ITEMS


def test_worked_examples_are_excluded():
    assert not set(FEW_SHOT_TICKETS) & set(select_ticket_ids(ROWS, TICKETS))


def test_worked_example_list_matches_the_prompt_file():
    prompt = Path("prompts/evaluation/PR-EVAL-JUDGE-01.md").read_text()
    in_prompt = set(re.findall(r"### Example \d[^\n]*\((VAL-\d{4})", prompt))
    assert in_prompt == set(FEW_SHOT_TICKETS)


def test_only_tickets_with_a_draft_are_selected():
    by_id = {r["ticket_id"]: r for r in ROWS}
    for tid in select_ticket_ids(ROWS, TICKETS):
        assert by_id[tid]["response_pre_guardrail"]["answer"].strip()


def test_small_strata_are_included_whole():
    by_id = {r["ticket_id"]: r for r in ROWS}
    pool = collections.defaultdict(set)
    for r in ROWS:
        if r["ticket_id"] not in FEW_SHOT_TICKETS and r["response_pre_guardrail"]["answer"].strip():
            pool[stratum(r, TICKETS[r["ticket_id"]])].add(r["ticket_id"])
    chosen = set(select_ticket_ids(ROWS, TICKETS))
    for key, ids in pool.items():
        if len(ids) <= SMALL_STRATUM:
            assert ids <= chosen, key
    non_fluent = {tid for tid in chosen if TICKETS[tid]["language_fluency"] == "non_fluent"}
    assert non_fluent == {tid for key, ids in pool.items() if key[0] == "non_fluent" for tid in ids}
    assert all(stratum(by_id[t], TICKETS[t]) for t in chosen)


def test_refuses_to_detect_scores_when_none_are_filled():
    empty = {"items": [{"human_scores": {d: None for d in DIMENSIONS}}]}
    scored = {"items": [{"human_scores": {"context_relevance": 4, "groundedness": None,
                                          "answer_relevance": None}}]}
    assert has_human_scores(empty) is False
    assert has_human_scores(scored) is True


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture not built yet")
def test_committed_fixture_is_consistent():
    fixture = json.loads(FIXTURE.read_text())
    items = fixture["items"]
    assert len(items) == N_ITEMS
    assert not {i["ticket_id"] for i in items} & set(FEW_SHOT_TICKETS)
    by_id = {r["ticket_id"]: r for r in ROWS}
    for item in items:
        row = by_id[item["ticket_id"]]
        assert [p["doc_id"] for p in item["passages"]] == row["retrieved_doc_ids"]
        assert item["reply"] == row["response_pre_guardrail"]["answer"]
        for d in DIMENSIONS:
            v = item["human_scores"][d]
            assert v is None or (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5)
