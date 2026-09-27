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
from src.route import (ADVISORY_GUARDRAILS, AUTO_RESPOND, COVERAGE_GUARDRAILS,
                       NEVER_AUTO_RESPOND)

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


def _holds_at_safety(g: dict, *, pii_filter: bool, drop_relevance: bool) -> bool:
    """Is this guardrail verdict a rule-2 safety block? Mirrors route._safety_failures.

    The sets come from src.route so that the two cannot drift: a coverage
    guardrail is held back to rule 6, and an ADVISORY verdict is recorded but
    does not withhold a reply — unless it is fail_safe, which says the check
    could not run rather than that the draft is fine (route._is_advisory).
    """
    if g["passed"] or not g["blocking"] or g["name"] in COVERAGE_GUARDRAILS:
        return False
    if g.get("fail_safe"):
        return True
    if g["name"] in ADVISORY_GUARDRAILS:
        return False
    if drop_relevance and g["name"] == "answer_relevance":
        return False
    if pii_filter and g["name"] == "pii" and not _pii_block_survives_filter(g):
        return False
    return True


def sends(row: dict, *, pii_filter: bool, drop_relevance: bool) -> bool:
    """Would the router auto-respond, in src/route.py's rule order?

    Rules 0 (kill switch) and 1 (an unlogged upstream decision) are not
    replayable: a result row records neither. Both escalate every ticket they
    fire on, so a run made under either simply fails the reproduction check
    below and the tool refuses to report, which is the right answer.
    """
    if row.get("degraded"):
        return False
    # 2. Safety: a blocking guardrail that read the draft and found a fault.
    if any(_holds_at_safety(g, pii_filter=pii_filter, drop_relevance=drop_relevance)
           for g in row.get("guardrails", [])):
        return False
    # 2b. Injection attempt in the ticket text (R-03, D-16).
    if row.get("injection_flags"):
        return False
    # 3. Policy: intents that never auto-answer (D-07).
    if row.get("intent") in NEVER_AUTO_RESPOND:
        return False
    # 4. Coverage: retrieval found nothing to ground a reply in.
    if not row.get("retrieved_doc_ids"):
        return False
    # 5. Honesty: the generator declined to answer.
    if row.get("unknown"):
        return False
    # 6. Quality: the confidence floor, as the threshold and as the guardrail.
    if (row.get("confidence") or 0.0) < CONFIDENCE_THRESHOLD:
        return False
    return not any(g["name"] in COVERAGE_GUARDRAILS and g["blocking"] and not g["passed"]
                   for g in row.get("guardrails", []))


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
