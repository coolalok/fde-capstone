"""Check generated answers against the pack's ground-truth response assertions.

data/ground_truth_responses.json carries 200 senior-agent-written reference
responses, each with `must_not_claim` (things the reply must never assert) and
`must_mention` (facts it should contain). Nothing in the project used them.

This is a DETERMINISTIC eval: no LLM judge, so no rate limits, no capability
ceiling, no run-to-run variance. That matters because judge availability is the
current binding constraint (Bug 5), and an eval built on a judge would inherit
the problem it is meant to measure.

What it measures: how often the generator makes a claim the ground truth
forbids. That is NFR-01b territory — the "confidently wrong" failure the whole
project is built around (EV-M3) — and it is currently unmeasured.

Scope and honesty about it:
  - All 200 ground-truth tickets are DEV-set; zero overlap with validation. So
    this cannot score a B-21 validation run; it runs its own pass.
  - `must_not_claim` items are natural-language ("a refund has been issued"),
    not literal strings, so detection is by pattern. Two of the three reuse the
    tone/scope guardrail's already-tested regexes; the third gets one here.
  - Detection is therefore a LOWER BOUND on violations: a phrasing no pattern
    covers is counted as clean.
  - Guardrails are not run. We are measuring what the GENERATOR produces, not
    what the guardrail layer would have blocked.

Usage:
    python -m evaluation.gt_response_check --limit 40 --output evaluation/results/gt
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from src.generate import generate
from src.guardrails import _RE_ETA, _RE_REFUND
from src.ingest import normalise_any
from src.logging_config import configure_logging
from src.logging_store import new_run_id, set_run_id
from src.retrieve import retrieve

_ROOT = Path(__file__).parent.parent
GT_PATH = _ROOT / "data" / "ground_truth_responses.json"
TICKETS_PATH = _ROOT / "data" / "development_tickets.json"

# "the issue has been fixed on our side" — a claim about work WE have done.
# The other two prohibitions already have tested detectors in the tone/scope
# guardrail, so only this one is new.
_RE_FIXED_OUR_SIDE = re.compile(
    r"""
    \b(?:
        (?:we|our\ team|engineering)\ (?:have|has|'ve)\ (?:now\ )?
            (?:fixed|resolved|corrected|repaired|patched|deployed\ a\ fix)
      | (?:this|the\ issue|it)\ (?:has\ been|was|is\ now)\ (?:fixed|resolved|corrected)
      | (?:we|our\ team)\ (?:are|'re)\ (?:working\ on|investigating)\ (?:it|this|the\ issue)
      | (?:we|our\ team)\ (?:have|has|'ve)\ (?:checked|reviewed|looked\ at)
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Maps each ground-truth prohibition to its detector.
CLAIM_DETECTORS = {
    "a refund has been issued": _RE_REFUND,
    "a specific delivery date for a fix": _RE_ETA,
    "the issue has been fixed on our side": _RE_FIXED_OUR_SIDE,
}


def check_answer(answer: str, must_not_claim: list[str],
                 must_mention: list[str]) -> dict:
    """Pure function so it is testable without a model call."""
    violations = [
        {"claim": claim, "matched": m.group(0)}
        for claim in must_not_claim
        if (pattern := CLAIM_DETECTORS.get(claim)) is not None
        and (m := pattern.search(answer)) is not None
    ]
    lowered = answer.lower()
    missing = [p for p in must_mention if p.lower() not in lowered]
    return {
        "violations": violations,
        "must_mention_total": len(must_mention),
        "must_mention_missing": missing,
        "undetectable_claims": [c for c in must_not_claim if c not in CLAIM_DETECTORS],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="check only the first N tickets")
    ap.add_argument("--output", default="evaluation/results/gt",
                    help="directory for the report")
    args = ap.parse_args(argv)

    configure_logging()
    gt = {g["ticket_id"]: g for g in json.loads(GT_PATH.read_text())}
    tickets = [t for t in json.loads(TICKETS_PATH.read_text()) if t["ticket_id"] in gt]
    if args.limit:
        tickets = tickets[: args.limit]

    run_id = set_run_id(new_run_id("gtcheck"))
    print(f"[gt] run_id={run_id} tickets={len(tickets)} (of {len(gt)} with ground truth)")

    rows, started = [], time.perf_counter()
    for i, raw in enumerate(tickets, 1):
        tid = raw["ticket_id"]
        # No classify() call: neither retrieve nor generate consumes the
        # classification, so it would be a wasted model call per ticket.
        ticket = normalise_any(raw)
        passages = retrieve(ticket.body, ticket_id=tid)
        response = generate(ticket, passages, ticket_id=tid)
        checked = check_answer(response.answer, gt[tid]["must_not_claim"],
                               gt[tid]["must_mention"])
        rows.append({"ticket_id": tid, "unknown": response.unknown,
                     "answer": response.answer, "error": response.error, **checked})
        if i % 10 == 0 or i == len(tickets):
            print(f"[gt]   {i}/{len(tickets)} ({time.perf_counter() - started:.0f}s)")

    answered = [r for r in rows if not r["unknown"] and r["answer"]]
    violating = [r for r in answered if r["violations"]]
    by_claim: dict[str, int] = {}
    for r in violating:
        for v in r["violations"]:
            by_claim[v["claim"]] = by_claim.get(v["claim"], 0) + 1
    expected_mentions = sum(r["must_mention_total"] for r in answered)
    missing_mentions = sum(len(r["must_mention_missing"]) for r in answered)

    report = {
        "run_id": run_id,
        "tickets_checked": len(rows),
        "answers_produced": len(answered),
        "answers_declined_unknown": sum(1 for r in rows if r["unknown"]),
        "answers_with_a_prohibited_claim": len(violating),
        "prohibited_claim_rate": round(len(violating) / len(answered), 4) if answered else None,
        "violations_by_claim": by_claim,
        "must_mention_expected": expected_mentions,
        "must_mention_missing": missing_mentions,
        "must_mention_coverage": (
            round(1 - missing_mentions / expected_mentions, 4) if expected_mentions else None),
        "note": ("Detection is a lower bound — a phrasing no pattern covers counts "
                 "as clean. Guardrails were NOT run; this measures the generator."),
        "wall_clock_seconds": round(time.perf_counter() - started, 1),
    }

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "gt_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (out / "gt_report.json").write_text(json.dumps(report, indent=2))

    print(f"\n[gt] answers produced: {len(answered)}/{len(rows)} "
          f"(declined unknown: {report['answers_declined_unknown']})")
    print(f"[gt] answers making a PROHIBITED claim: {len(violating)}"
          f" ({report['prohibited_claim_rate']})")
    for claim, n in sorted(by_claim.items(), key=lambda x: -x[1]):
        print(f"[gt]    {n:>3}x  {claim}")
    print(f"[gt] must_mention coverage: {report['must_mention_coverage']}")
    print(f"[gt] wrote {out}/gt_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
