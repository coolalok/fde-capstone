"""Guards on the text PR-GENERATE-01 actually sends to the model."""
from __future__ import annotations

import json

from evaluation.gt_response_check import mentions
from src.prompt_loader import load_prompt

SYSTEM = load_prompt("PR-GENERATE-01").system


def test_system_prompt_contains_no_ground_truth_answer_key_terms():
    """must_mention is the per-ticket answer key. A term from it in the system
    prompt raises coverage because the prompt holds the answer, not because the
    reply got better — and it would make every coverage figure unreportable.
    """
    gt = json.load(open("data/ground_truth_responses.json"))
    terms = sorted({t for g in gt for t in g["must_mention"]})
    leaked = [t for t in terms if mentions(SYSTEM, t)]
    assert not leaked, f"answer-key terms in the system prompt: {leaked}"


def test_system_prompt_keeps_the_contracts_the_pipeline_depends_on():
    for required in ("<<TICKET_START>>", "`unknown`", "Exactly these four fields",
                     "[DOC-AUTH-001]", "Do not claim to be a human agent"):
        assert required in SYSTEM, required


def test_system_prompt_does_not_invite_unsourced_frequency_claims():
    lowered = SYSTEM.lower()
    for phrase in ("the usual cause", "in most cases"):
        assert phrase not in lowered, phrase
