"""The held-out split is only worth anything if it is stable, disjoint and
representative. These tests pin all three.
"""
from __future__ import annotations

import collections
import json

from evaluation.make_gt_split import SEED, make_split

GT = json.load(open("data/ground_truth_responses.json"))


def test_split_is_deterministic():
    assert make_split(GT) == make_split(GT)


def test_split_is_disjoint_and_complete():
    s = make_split(GT)
    assert not set(s["tune"]) & set(s["heldout"])
    assert set(s["tune"]) | set(s["heldout"]) == {g["ticket_id"] for g in GT}


def test_split_is_stratified_by_intent():
    s = make_split(GT)
    intent = {g["ticket_id"]: g["intent"] for g in GT}
    tune = collections.Counter(intent[t] for t in s["tune"])
    held = collections.Counter(intent[t] for t in s["heldout"])
    assert max(abs(tune[i] - held[i]) for i in set(intent.values())) <= 1
    assert abs(len(s["tune"]) - len(s["heldout"])) <= 1


def test_committed_split_matches_the_generator():
    """If the committed file drifts from the script, the 'frozen before the
    prompt changed' claim no longer holds for the file being scored against.
    """
    committed = json.load(open("evaluation/splits/gt_prompt_split.json"))
    assert committed["seed"] == SEED
    assert committed == make_split(GT)
