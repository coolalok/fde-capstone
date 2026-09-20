"""Replay a harness run's stored guardrail verdicts under changed guardrail rules.

Satisfies: nothing in production. Evidence for D-11 and for the
           answer-relevance judge question (docs/adr/D-11-*.md).

Re-routes every ticket of a completed run from what the run recorded (intent,
confidence, retrieval, generator unknown, each guardrail's verdict) without a
model call, applying the router's rule order from src/route.py. It first checks
that the unchanged rules reproduce every stored decision, and refuses to report
otherwise: a counterfactual on a replay that does not match the run is noise.

Three configurations:
  as_run                 the rules the run used
  pii_value_shaped       D-11: LLM PII detections that cannot be the value are dropped
  pii_and_no_relevance   D-11, and answer_relevance verdicts ignored (fail-safe
                         relevance blocks still count: a judge outage still holds)

Guardrail verdicts do not depend on one another, so removing one leaves the
others' stored verdicts valid.

Usage:
    python -m evaluation.guardrail_counterfactual \\
        --run evaluation/results/b21_local_80_20260919
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from src.config import CONFIDENCE_THRESHOLD
from src.guardrails import _llm_detection_is_value_shaped
from src.route import AUTO_RESPOND, NEVER_AUTO_RESPOND

_ROOT = Path(__file__).parent.parent
TICKETS_PATH = _ROOT / "data" / "validation_tickets.json"

CONFIGS = {
    "as_run": (False, False),
    "pii_value_shaped": (True, False),
    "pii_and_no_relevance": (True, True),
}


def _pii_block_survives_filter(g: dict) -> bool:
    detections = (g.get("details") or {}).get("detections", [])
    return not detections or any(
        d.get("source") != "llm" or _llm_detection_is_value_shaped(d["category"], d["text"])
        for d in detections)


def sends(row: dict, *, pii_filter: bool, drop_relevance: bool) -> bool:
    """Would the router auto-respond, in src/route.py's rule order?"""
    if row.get("degraded"):
        return False
    for g in row.get("guardrails", []):
        if not g["blocking"] or g["passed"]:
            continue
        if g.get("fail_safe"):
            return False
        if drop_relevance and g["name"] == "answer_relevance":
            continue
        if pii_filter and g["name"] == "pii" and not _pii_block_survives_filter(g):
            continue
        return False
    if row.get("intent") in NEVER_AUTO_RESPOND:
        return False
    if not row.get("retrieved_doc_ids") or row.get("unknown"):
        return False
    return (row.get("confidence") or 0.0) >= CONFIDENCE_THRESHOLD


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="harness output directory")
    ap.add_argument("--tickets", default=str(TICKETS_PATH))
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in (Path(args.run) / "results.jsonl").open()]
    labels = {t["ticket_id"]: t["labels"] for t in json.loads(Path(args.tickets).read_text())}

    mismatched = [r["ticket_id"] for r in rows
                  if sends(r, pii_filter=False, drop_relevance=False)
                  != (r.get("decision") == AUTO_RESPOND)]
    if mismatched:
        print(f"replay does not reproduce the run for {mismatched}; not reporting")
        return 1

    report = {"run": args.run, "n": len(rows), "configs": {}}
    for name, (pii_filter, drop_relevance) in CONFIGS.items():
        sent = [r for r in rows if sends(r, pii_filter=pii_filter, drop_relevance=drop_relevance)]
        correct = sum(1 for r in sent if labels[r["ticket_id"]]["expected_route"] == AUTO_RESPOND)
        report["configs"][name] = {
            "sent": len(sent), "correct_sends": correct, "wrong_sends": len(sent) - correct,
            "send_precision": round(correct / len(sent), 4) if sent else None,
            "correct_fcr": round(correct / len(rows), 4),
        }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
