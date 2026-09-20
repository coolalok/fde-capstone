"""Tests for the PR-EVAL-JUDGE-01 runner and the B-18 agreement check. No model calls
except the slow agreement test, which runs only once human scores exist.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.judge import (
    AGREEMENT_FLOOR,
    _ranks,
    agreement,
    model_family,
    parse_scores,
    score_item,
    spearman,
)

VALID = {
    "reasoning": "Passages fit; claims supported; answers the question.",
    "context_relevance": {"score": 5, "supporting_evidence": "DOC-A-001"},
    "groundedness": {"score": 4, "unsupported_claims": ["x"]},
    "answer_relevance": {"score": 3, "notes": "what was asked"},
}
ITEM = {"item_id": "CAL-99", "ticket_id": "T-1",
        "ticket": {"channel": "email", "subject": "s", "body": "b"},
        "passages": [{"doc_id": "DOC-A-001", "title": "t", "category": "c", "text": "p"}],
        "reply": "r", "human_scores": {}}


# ─── Spearman ────────────────────────────────────────────────────────


def test_ranks_average_ties():
    assert _ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_and_reversed():
    assert spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_with_ties_matches_scipy():
    stats = pytest.importorskip("scipy.stats")
    x, y = [1, 2, 2, 3, 5, 4, 4], [1, 3, 2, 4, 5, 5, 3]
    assert spearman(x, y) == pytest.approx(stats.spearmanr(x, y).statistic, abs=1e-9)


def test_spearman_is_undefined_without_variation_or_data():
    assert spearman([3, 3, 3], [1, 2, 3]) is None
    assert spearman([1, 2], [1, 2]) is None


# ─── verdict validation ──────────────────────────────────────────────


def test_parse_scores_accepts_a_valid_verdict_including_fenced():
    assert parse_scores(json.dumps(VALID))["scores"] == {
        "context_relevance": 5, "groundedness": 4, "answer_relevance": 3}
    assert parse_scores("```json\n" + json.dumps(VALID) + "\n```")["scores"]["groundedness"] == 4


@pytest.mark.parametrize("bad", [0, 6, 4.5, True, "4", None])
def test_parse_scores_rejects_non_integer_or_out_of_range_scores(bad):
    v = json.loads(json.dumps(VALID))
    v["groundedness"]["score"] = bad
    with pytest.raises(ValueError):
        parse_scores(json.dumps(v))


def test_parse_scores_requires_reasoning_and_every_dimension():
    for broken in ({k: v for k, v in VALID.items() if k != "reasoning"},
                   {k: v for k, v in VALID.items() if k != "answer_relevance"}):
        with pytest.raises(ValueError):
            parse_scores(json.dumps(broken))


# ─── scoring an item ─────────────────────────────────────────────────


def test_score_item_records_scores_and_prompt_version():
    out = score_item(ITEM, call_model=lambda s, u, seed: json.dumps(VALID))
    assert out["error"] is None
    assert out["scores"]["context_relevance"] == 5
    assert out["prompt_version"].startswith("PR-EVAL-JUDGE-01@")


def test_score_item_records_a_malformed_verdict_as_an_error_not_a_score():
    out = score_item(ITEM, call_model=lambda s, u, seed: '{"reasoning": "x"}')
    assert out["scores"] is None and "ValueError" in out["error"]


def test_score_item_never_scores_an_empty_reply():
    def must_not_run(*a):  # pragma: no cover
        raise AssertionError("the judge must not be called for an abstention")
    out = score_item(ITEM | {"reply": "  "}, call_model=must_not_run)
    assert out["scores"] is None and "empty reply" in out["error"]


def test_the_prompt_sees_the_reply_passages_and_ticket():
    seen = {}

    def capture(system, user, seed):
        seen["user"] = user
        return json.dumps(VALID)
    score_item(ITEM | {"reply": "REPLY-TEXT"}, call_model=capture)
    assert "REPLY-TEXT" in seen["user"] and "DOC-A-001" in seen["user"]
    assert "Channel: email" in seen["user"]


# ─── agreement ───────────────────────────────────────────────────────


def _pair(item_id, human, judge, error=None):
    item = {"item_id": item_id, "human_scores": dict(zip(
        ("context_relevance", "groundedness", "answer_relevance"), human))}
    judged = {"item_id": item_id, "error": error,
              "scores": None if error else dict(zip(
                  ("context_relevance", "groundedness", "answer_relevance"), judge))}
    return item, judged


def test_agreement_pools_dimensions_and_excludes_incomplete_pairs():
    rows = [_pair("A", (5, 5, 5), (5, 4, 5)), _pair("B", (2, 2, 2), (2, 3, 2)),
            _pair("C", (4, 3, 4), (4, 3, 3)), _pair("D", (3, 3, 3), None, error="boom"),
            ({"item_id": "E", "human_scores": {"context_relevance": None,
                                               "groundedness": None, "answer_relevance": None}},
             {"item_id": "E", "error": None, "scores": {"context_relevance": 1,
                                                        "groundedness": 1, "answer_relevance": 1}})]
    items = [i for i, _ in rows]
    judged = {j["item_id"]: j for _, j in rows}
    r = agreement(items, judged)
    assert r["pooled"]["n"] == 9
    assert r["excluded"] == {"judge_error": 1, "human_unscored": 1}
    assert r["dimensions"]["context_relevance"]["exact_agreement"] == 1.0
    assert r["pooled"]["spearman"] > 0.8 and r["trusted"] is True


# ─── self-preference safeguard (capstone-test-writer) ────────────────


@pytest.mark.parametrize("model, family", [
    ("gpt-4o-mini", "openai"), ("openai/gpt-4o-mini", "openai"),
    ("gemini-3.8-flash", "google"), ("google/gemma-3-27b-it", "google"),
    ("meta-llama/llama-3.1-8b-instruct", "meta"),
    ("nvidia/nemotron-3-super-120b-a12b:free", "nvidia"),
    ("mistralai/mistral-small-3.1-24b-instruct", "mistral"),
])
def test_model_family(model, family):
    assert model_family(model) == family


def test_judge_not_same_family_as_generator():
    """Config check, no model call: the judge must not share the generator's family."""
    from src.config import GUARDRAIL_MODEL, MODEL_NAME
    assert model_family(GUARDRAIL_MODEL) != model_family(MODEL_NAME), (GUARDRAIL_MODEL, MODEL_NAME)


# ─── B-18 gate: runs once the human scores and a judge run exist ──────

FIXTURE = Path("tests/fixtures/judge_calibration.json")
JUDGED = Path("evaluation/results/judge_calibration/judged.jsonl")


@pytest.mark.slow
def test_judge_agreement_with_human_baseline():
    """Judge/human agreement must reach Spearman >= 0.70 (B-18 definition of done)."""
    if not FIXTURE.exists() or not JUDGED.exists():
        pytest.skip("calibration fixture or judge run not present")
    fixture = json.loads(FIXTURE.read_text())
    if any(v is None for i in fixture["items"] for v in i["human_scores"].values()):
        pytest.skip("human scores incomplete")
    judged = {json.loads(line)["item_id"]: json.loads(line) for line in JUDGED.open()}
    r = agreement(fixture["items"], judged)
    assert r["pooled"]["spearman"] >= AGREEMENT_FLOOR, r
