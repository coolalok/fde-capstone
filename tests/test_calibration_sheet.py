"""The scoring sheet must be blind, use the judge's exact rubric, survive hostile text,
and import only valid scores from the fixture it was built from.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from evaluation.calibration_sheet import (
    build_html,
    embed_json,
    fixture_id,
    import_scores,
    rubric_markdown,
)

FIXTURE = json.loads(Path("tests/fixtures/judge_calibration.json").read_text())
PROMPT = Path("prompts/evaluation/PR-EVAL-JUDGE-01.md").read_text()


def _data_block(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_sheet_contains_every_item():
    data = _data_block(build_html(FIXTURE, PROMPT))
    assert [i["item_id"] for i in data["items"]] == [i["item_id"] for i in FIXTURE["items"]]


def test_sheet_is_blind():
    """No label, routing outcome, stratum or judge output may reach the scorer."""
    data = _data_block(build_html(FIXTURE, PROMPT))
    for item in data["items"]:
        assert set(item) == {"item_id", "ticket", "passages", "reply"}
    page = build_html(FIXTURE, PROMPT)
    for leak in ("answerable_label", "sent_to_customer", "intent_label", "stratum",
                 "human_scores", '"decision"'):
        assert leak not in page, leak


def test_sheet_rubric_is_the_judge_prompt_rubric():
    page = build_html(FIXTURE, PROMPT)
    rubric = rubric_markdown(PROMPT)
    for heading in re.findall(r"^### (.+)$", rubric, re.M):
        assert heading.split(" — ")[0] in page
    assert "Length is not quality." in page


def test_hostile_reply_cannot_break_out_of_the_data_block():
    hostile = copy.deepcopy(FIXTURE)
    hostile["items"][0]["reply"] = "</script><script>alert(1)</script>"
    page = build_html(hostile, PROMPT)
    assert page.count("</script>") == 2          # the data block and the app script only
    assert _data_block(page)["items"][0]["reply"] == "</script><script>alert(1)</script>"
    assert "<\\/script>" in embed_json({"x": "</script>"})


def _payload(fx, scores):
    return {"fixture_id": fixture_id(fx), "scores": scores}


def test_import_merges_valid_scores_and_notes():
    fx = copy.deepcopy(FIXTURE)
    first = fx["items"][0]["item_id"]
    report = import_scores(fx, _payload(fx, {first: {
        "context_relevance": 4, "groundedness": 5, "answer_relevance": 3, "notes": "ok"}}))
    assert fx["items"][0]["human_scores"] == {
        "context_relevance": 4, "groundedness": 5, "answer_relevance": 3}
    assert fx["items"][0]["human_notes"] == "ok"
    assert report["items_complete"] == 1 and report["items_updated"] == 1


@pytest.mark.parametrize("bad", [0, 6, 3.5, True, "4"])
def test_import_rejects_invalid_scores(bad):
    fx = copy.deepcopy(FIXTURE)
    first = fx["items"][0]["item_id"]
    with pytest.raises(ValueError):
        import_scores(fx, _payload(fx, {first: {"groundedness": bad}}))


def test_import_refuses_scores_from_a_different_fixture():
    fx = copy.deepcopy(FIXTURE)
    with pytest.raises(ValueError, match="different calibration fixture"):
        import_scores(fx, {"fixture_id": "not-this-one", "scores": {}})


def test_import_allows_a_partial_file():
    fx = copy.deepcopy(FIXTURE)
    first = fx["items"][0]["item_id"]
    report = import_scores(fx, _payload(fx, {first: {"groundedness": 4}}))
    assert fx["items"][0]["human_scores"]["groundedness"] == 4
    assert report["items_complete"] == 0
