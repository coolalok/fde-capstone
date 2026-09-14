"""Freeze a tune / held-out split of data/ground_truth_responses.json.

must_mention and reference_response exist only on these 200 tickets. Any change
tuned against them and then scored on them reports a number flattered by the
tuning. So the tickets are split BEFORE a prompt is edited, the split is
committed, and a candidate prompt is judged once on the held-out half.

Stratified by intent so both halves see every intent in proportion. Deterministic:
same seed, same split. Where an intent has an odd count the extra ticket
alternates between halves, so no half systematically gets the larger share.

Usage:
    python -m evaluation.make_gt_split
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).parent.parent
GT_PATH = _ROOT / "data" / "ground_truth_responses.json"
OUT_PATH = _ROOT / "evaluation" / "splits" / "gt_prompt_split.json"
SEED = 20260914


def make_split(gt: list[dict], seed: int = SEED) -> dict:
    by_intent: dict[str, list[str]] = defaultdict(list)
    for g in gt:
        by_intent[g["intent"]].append(g["ticket_id"])
    rng = random.Random(seed)
    tune: list[str] = []
    heldout: list[str] = []
    extra_to_heldout = False
    for intent in sorted(by_intent):
        ids = sorted(by_intent[intent])
        rng.shuffle(ids)
        half = len(ids) // 2
        if len(ids) % 2:
            cut = half + (0 if extra_to_heldout else 1)
            extra_to_heldout = not extra_to_heldout
        else:
            cut = half
        tune += ids[:cut]
        heldout += ids[cut:]
    return {
        "seed": seed,
        "method": "stratified by intent; odd remainders alternate between halves",
        "source": "data/ground_truth_responses.json",
        "rule": ("heldout is scored ONCE per candidate prompt; any iteration on a "
                 "prompt uses tune only"),
        "tune": sorted(tune),
        "heldout": sorted(heldout),
    }


def main() -> int:
    gt = json.loads(GT_PATH.read_text())
    split = make_split(gt)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(split, indent=1) + "\n")
    print(f"[split] tune={len(split['tune'])} heldout={len(split['heldout'])} -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
