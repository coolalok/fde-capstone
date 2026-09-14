"""B-18: build the 50-item human calibration set for PR-EVAL-JUDGE-01.

Each item is one (ticket, retrieved passages, drafted reply) triple from the clean
80-ticket B-21 run. A human scores it blind on the judge's rubric; the judge's scores
must then agree at Spearman >= 0.70 (capstone-test-writer) before its numbers are
reported as measurements.

Selection (deterministic):
- Only tickets with a non-empty draft; an abstention has nothing to score.
- The judge prompt's worked examples are EXCLUDED, so agreement is not inflated by the
  judge having seen those answers.
- Strata are (language_fluency, sent or held, answerable or not). Every stratum of at
  most SMALL_STRATUM drafts is included whole — that keeps all non-fluent drafts and the
  rare fluent cases. The remaining places go to the larger strata in proportion to size
  (largest remainder), picked round-robin across intents after a seeded shuffle.
- Presentation order is shuffled with the same seed so the scorer never works through
  one stratum in a block.

What the scorer sees is only what the judge sees: channel, subject, body, passages and
reply. Labels, routing outcome and guardrail verdicts are kept in `meta` for analysis
and are not shown.

The fixture is never regenerated over human scores: if any score is filled in, writing
refuses unless --force is given.

Usage:
    python -m evaluation.judge_calibration build
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
RESULTS = _ROOT / "evaluation" / "results" / "b21_openai_80_20260914" / "results.jsonl"
TICKETS = _ROOT / "data" / "validation_tickets.json"
FIXTURE = _ROOT / "tests" / "fixtures" / "judge_calibration.json"
PROMPT_ID = "PR-EVAL-JUDGE-01"

N_ITEMS = 50
SMALL_STRATUM = 10
SEED = 20260914
DIMENSIONS = ("context_relevance", "groundedness", "answer_relevance")
# The worked examples in prompts/evaluation/PR-EVAL-JUDGE-01.md. A test checks this
# list against the prompt file, so the two cannot drift apart.
FEW_SHOT_TICKETS = ("VAL-0006", "VAL-0013", "VAL-0036")


def stratum(row: dict, ticket: dict) -> tuple[str, str, str]:
    return (
        ticket["language_fluency"],
        "sent" if row["response_post_guardrail"]["sent_to_customer"] else "held",
        "answerable" if ticket["labels"].get("answerable_from_docs") else "unanswerable",
    )


def _largest_remainder(sizes: dict, places: int) -> dict:
    total = sum(sizes.values())
    if not total or places <= 0:
        return {k: 0 for k in sizes}
    exact = {k: places * v / total for k, v in sizes.items()}
    alloc = {k: int(x) for k, x in exact.items()}
    by_remainder = sorted(sizes, key=lambda k: (exact[k] - alloc[k], k), reverse=True)
    for k in by_remainder[: places - sum(alloc.values())]:
        alloc[k] += 1
    return {k: min(alloc[k], sizes[k]) for k in sizes}


def _round_robin_by_intent(ids: list[str], tickets: dict, k: int, rng: random.Random) -> list[str]:
    by_intent: dict[str, list[str]] = defaultdict(list)
    for tid in ids:
        by_intent[tickets[tid]["labels"]["intent"]].append(tid)
    intents = sorted(by_intent)
    rng.shuffle(intents)
    for intent in intents:
        rng.shuffle(by_intent[intent])
    picked: list[str] = []
    while len(picked) < k and any(by_intent.values()):
        for intent in intents:
            if by_intent[intent] and len(picked) < k:
                picked.append(by_intent[intent].pop())
    return picked


def select_ticket_ids(rows: list[dict], tickets: dict, n: int = N_ITEMS,
                      exclude: tuple[str, ...] = FEW_SHOT_TICKETS, seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    strata: dict[tuple, list[str]] = defaultdict(list)
    for row in rows:
        tid = row["ticket_id"]
        if tid in exclude or not (row["response_pre_guardrail"]["answer"] or "").strip():
            continue
        strata[stratum(row, tickets[tid])].append(tid)
    for key in strata:
        strata[key].sort()
    chosen = [tid for key in sorted(strata) if len(strata[key]) <= SMALL_STRATUM
              for tid in strata[key]]
    large = {key: len(ids) for key, ids in strata.items() if len(ids) > SMALL_STRATUM}
    quota = _largest_remainder(large, n - len(chosen))
    for key in sorted(large):
        chosen += _round_robin_by_intent(strata[key], tickets, quota[key], rng)
    if len(chosen) > n:
        raise ValueError(f"small strata alone exceed {n} items ({len(chosen)})")
    return chosen


def build_items(ticket_ids: list[str], rows_by_id: dict, tickets: dict, retrieve_fn) -> list[dict]:
    """retrieve_fn(ticket_id) -> list of Passage; must reproduce the run's doc list."""
    order = list(ticket_ids)
    random.Random(SEED).shuffle(order)
    items = []
    for i, tid in enumerate(order, 1):
        row, ticket = rows_by_id[tid], tickets[tid]
        passages = retrieve_fn(tid)
        if [p.doc_id for p in passages] != row["retrieved_doc_ids"]:
            raise ValueError(f"{tid}: retrieval no longer reproduces the run's passages")
        items.append({
            "item_id": f"CAL-{i:02d}",
            "ticket_id": tid,
            "ticket": {"channel": ticket["channel"], "subject": ticket["subject"],
                       "body": ticket["body"]},
            "passages": [{"doc_id": p.doc_id, "title": p.title, "category": p.category,
                          "chunk_index": p.chunk_index, "text": p.chunk_text} for p in passages],
            "reply": row["response_pre_guardrail"]["answer"],
            "meta": {
                "language_fluency": ticket["language_fluency"],
                "customer_region": ticket["customer_region"],
                "customer_tier": ticket["customer_tier"],
                "intent_label": ticket["labels"]["intent"],
                "answerable_label": ticket["labels"].get("answerable_from_docs"),
                "sent_to_customer": row["response_post_guardrail"]["sent_to_customer"],
                "decision": row["decision"],
                "stratum": list(stratum(row, ticket)),
            },
            "human_scores": {d: None for d in DIMENSIONS},
            "human_notes": "",
        })
    return items


def has_human_scores(fixture: dict) -> bool:
    return any(v is not None for item in fixture.get("items", [])
               for v in item.get("human_scores", {}).values())


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--force", action="store_true", help="overwrite even if human scores exist")
    args = ap.parse_args(argv)

    if FIXTURE.exists() and has_human_scores(json.loads(FIXTURE.read_text())) and not args.force:
        raise SystemExit(f"{FIXTURE} already holds human scores; refusing to overwrite")

    from src.ingest import normalise_any
    from src.logging_config import configure_logging
    from src.logging_store import new_run_id, set_run_id
    from src.retrieve import retrieve

    configure_logging()
    set_run_id(new_run_id("judge-calibration"))
    tickets = {t["ticket_id"]: t for t in json.loads(TICKETS.read_text())}
    rows = [json.loads(line) for line in RESULTS.open()]
    rows_by_id = {r["ticket_id"]: r for r in rows}
    ids = select_ticket_ids(rows, tickets)
    items = build_items(ids, rows_by_id, tickets,
                        lambda tid: retrieve(normalise_any(tickets[tid]).body, ticket_id=tid))
    fixture = {
        "purpose": "B-18 human calibration set for PR-EVAL-JUDGE-01 (score blind; see README note)",
        "prompt_id": PROMPT_ID,
        "source_run": str(RESULTS.relative_to(_ROOT)),
        "generator": "gpt-4o-mini (B-21 run)",
        "seed": SEED,
        "excluded_worked_examples": list(FEW_SHOT_TICKETS),
        "dimensions": list(DIMENSIONS),
        "items": items,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")
    print(f"[calibration] wrote {len(items)} items to {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
