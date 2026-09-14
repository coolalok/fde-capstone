"""B-24 fairness audit: outcome quality by customer segment (NFR-05).

Reads a harness run (results.jsonl) and the labelled ticket file, then compares
outcomes across language_fluency, customer_region, customer_tier, channel and
ticket length.

QUALITY IS NOT RUBRIC-SCORED. B-24's definition of done asks for rubric-scored
answer quality, which needs the PR-EVAL-JUDGE-01 judge (B-17, not built), and
the validation set carries no reference replies. Quality is measured from the
labels the validation set does carry:

  decision_correct   the ticket's decision agreed with labels.expected_route
                     (auto-sent vs held back). Primary quality measure: it
                     penalises answering what should be held and holding what
                     should be answered.
  resolution_rate    of tickets that SHOULD auto-send, the share that did.
  unsafe_send_rate   of tickets that should be HELD, the share auto-sent
                     (lower is better).
  auto_precision     of tickets auto-sent, the share that should have been.
                     NFR-05's tier rule applies to quality "within the
                     auto_respond band"; this is that measure.
  intent_accuracy, retrieval_hit_at_3 (NFR-05 requires retrieval to be reported
                     alongside), mean classifier confidence.

  mix_adjusted_quality
                     decision correctness re-weighted to the overall ticket mix
                     (direct standardisation): share_should_auto x
                     resolution_rate + share_should_hold x (1 - unsafe_send_rate),
                     using the whole run's shares. Answers whether a segment's
                     lower decision_correct is its ticket mix or its treatment.
                     Eligible only when BOTH component rates have MIN_N tickets.

Why conditioned rates. Segments differ sharply in what they send in: on the
80-ticket validation set, 10 of 19 non-fluent tickets are unanswerable against
17 of 61 fluent. A raw auto-send rate would mostly measure that mix. Resolution
and unsafe-send rates compare like tickets with like.

Uncertainty. Every rate carries a Wilson 95% interval. A segment below MIN_N
tickets for a given measure is reported but never judged, and cannot be "best".
A gap beyond the limit is BREACH only when the segment's interval and the best
segment's interval do not overlap; otherwise BREACH_NOT_SIGNIFICANT.

Limits (NFR-05): 15pp across language_fluency and customer_region; 10pp across
customer_tier for auto_precision. Channel and length have no NFR limit; their
gaps are reported against 15pp for information only.

Usage:
    python -m evaluation.fairness_audit --results evaluation/results/b21_openai_80_20260914
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
TICKETS_PATH = _ROOT / "data" / "validation_tickets.json"

AUTO = "auto_respond"
DIMENSIONS = ("language_fluency", "customer_region", "customer_tier", "channel", "length")
MIN_N = 10
Z = 1.96
QUALITY_GAP_LIMIT = 0.15
TIER_AUTO_PRECISION_GAP_LIMIT = 0.10
HIGHER_IS_BETTER = {
    "decision_correct": True,
    "resolution_rate": True,
    "unsafe_send_rate": False,
    "auto_precision": True,
    "intent_accuracy": True,
    "retrieval_hit_at_3": True,
    "mix_adjusted_quality": True,
}
# (dimension, measure, limit, binding) — binding=False is informational.
CHECKS = (
    ("language_fluency", "decision_correct", QUALITY_GAP_LIMIT, True),
    ("language_fluency", "resolution_rate", QUALITY_GAP_LIMIT, True),
    ("language_fluency", "unsafe_send_rate", QUALITY_GAP_LIMIT, True),
    ("customer_region", "decision_correct", QUALITY_GAP_LIMIT, True),
    ("customer_region", "resolution_rate", QUALITY_GAP_LIMIT, True),
    ("customer_region", "unsafe_send_rate", QUALITY_GAP_LIMIT, True),
    ("customer_tier", "auto_precision", TIER_AUTO_PRECISION_GAP_LIMIT, True),
    ("language_fluency", "mix_adjusted_quality", QUALITY_GAP_LIMIT, False),
    ("customer_region", "mix_adjusted_quality", QUALITY_GAP_LIMIT, False),
    ("channel", "decision_correct", QUALITY_GAP_LIMIT, False),
    ("length", "decision_correct", QUALITY_GAP_LIMIT, False),
)


def wilson(k: int, n: int) -> Optional[tuple[float, float]]:
    """Wilson score 95% interval for k successes in n trials."""
    if n == 0:
        return None
    p = k / n
    z2 = Z * Z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> dict:
    ci = wilson(k, n)
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None,
            "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None}


def length_cuts(word_counts: list[int]) -> tuple[float, float]:
    """Tercile boundaries, so short/medium/long are roughly equal thirds."""
    lower, upper = statistics.quantiles(word_counts, n=3)
    return lower, upper


def length_band(words: int, cuts: tuple[float, float]) -> str:
    lower, upper = cuts
    if words <= lower:
        return "short"
    return "long" if words > upper else "medium"


def ticket_words(ticket: dict) -> int:
    return len(f"{ticket.get('subject', '')} {ticket.get('body', '')}".split())


def ticket_record(result: dict, ticket: dict, cuts: tuple[float, float]) -> dict:
    labels = ticket["labels"]
    should_auto = labels.get("expected_route") == AUTO
    sent = result["decision"] == AUTO
    expected = set(labels.get("expected_doc_ids") or [])
    answerable = labels.get("answerable_from_docs")
    words = ticket_words(ticket)
    return {
        "ticket_id": ticket["ticket_id"],
        "language_fluency": ticket.get("language_fluency"),
        "customer_region": ticket.get("customer_region"),
        "customer_tier": ticket.get("customer_tier"),
        "channel": ticket.get("channel"),
        "length": length_band(words, cuts),
        "words": words,
        "should_auto": should_auto,
        "sent": sent,
        "decision_correct": sent == should_auto,
        "intent_correct": result.get("intent") == labels.get("intent"),
        "answerable_label": answerable,
        "retrieval_hit": (bool(expected & set(result.get("retrieved_doc_ids", [])[:3]))
                          if expected and answerable else None),
        "confidence": result.get("confidence"),
    }


def segment_metrics(records: list[dict]) -> dict:
    should_auto = [r for r in records if r["should_auto"]]
    should_hold = [r for r in records if not r["should_auto"]]
    sent = [r for r in records if r["sent"]]
    retrieval = [r for r in records if r["retrieval_hit"] is not None]
    confidence = [r["confidence"] for r in records if r["confidence"] is not None]
    return {
        "n": len(records),
        "composition": {
            "should_auto": len(should_auto),
            "should_hold": len(should_hold),
            "unanswerable": sum(1 for r in records if r["answerable_label"] is False),
        },
        "decision_correct": rate(sum(r["decision_correct"] for r in records), len(records)),
        "resolution_rate": rate(sum(r["sent"] for r in should_auto), len(should_auto)),
        "unsafe_send_rate": rate(sum(r["sent"] for r in should_hold), len(should_hold)),
        "auto_precision": rate(sum(r["should_auto"] for r in sent), len(sent)),
        "intent_accuracy": rate(sum(r["intent_correct"] for r in records), len(records)),
        "retrieval_hit_at_3": rate(sum(r["retrieval_hit"] for r in retrieval), len(retrieval)),
        "mean_confidence": round(statistics.mean(confidence), 4) if confidence else None,
    }


def mix_adjusted_quality(segment: dict, share_should_auto: float) -> dict:
    """Decision correctness re-weighted to a common ticket mix.

    The interval combines the two component Wilson intervals as independent
    normal approximations (half-width / Z as the standard error), which avoids
    the zero-width interval a plain Wald error gives at a rate of 0 or 1.
    """
    res, uns = segment["resolution_rate"], segment["unsafe_send_rate"]
    n = min(res["n"], uns["n"])
    if res["value"] is None or uns["value"] is None:
        return {"value": None, "ci95": None, "n": n}
    w = share_should_auto
    value = w * res["value"] + (1 - w) * (1 - uns["value"])
    se_res = (res["ci95"][1] - res["ci95"][0]) / (2 * Z)
    se_uns = (uns["ci95"][1] - uns["ci95"][0]) / (2 * Z)
    half = Z * math.sqrt((w * se_res) ** 2 + ((1 - w) * se_uns) ** 2)
    return {"value": round(value, 4), "n": n,
            "ci95": [round(max(0.0, value - half), 4), round(min(1.0, value + half), 4)]}


def by_segment(records: list[dict], dimension: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[str(r[dimension])].append(r)
    share = sum(r["should_auto"] for r in records) / len(records) if records else 0.0
    out = {}
    for segment, rs in sorted(groups.items()):
        m = segment_metrics(rs)
        m["mix_adjusted_quality"] = mix_adjusted_quality(m, share)
        out[segment] = m
    return out


def assess(segments: dict[str, dict], measure: str, limit: float) -> dict:
    """Gap of each segment from the best eligible segment, judged against a limit."""
    higher = HIGHER_IS_BETTER[measure]
    eligible = {s: m[measure] for s, m in segments.items()
                if m[measure]["value"] is not None and m[measure]["n"] >= MIN_N}
    unassessed = sorted(s for s, m in segments.items()
                        if m[measure]["value"] is None or m[measure]["n"] < MIN_N)
    if len(eligible) < 2:
        return {"measure": measure, "limit": limit, "verdict": "INSUFFICIENT_N",
                "best_segment": None, "segments": [], "unassessed": unassessed}
    pick = max if higher else min
    best = pick(eligible, key=lambda s: eligible[s]["value"])
    best_ci = eligible[best]["ci95"]
    findings = []
    for segment, m in segments.items():
        r = m[measure]
        if r["value"] is None:
            continue
        best_value = eligible[best]["value"]
        gap = round((best_value - r["value"]) if higher else (r["value"] - best_value), 4)
        if r["n"] < MIN_N:
            status = "INSUFFICIENT_N"
        elif gap > limit:
            separated = r["ci95"][1] < best_ci[0] if higher else r["ci95"][0] > best_ci[1]
            status = "BREACH" if separated else "BREACH_NOT_SIGNIFICANT"
        else:
            status = "WITHIN_LIMIT"
        findings.append({"segment": segment, "value": r["value"], "n": r["n"],
                         "ci95": r["ci95"], "gap_from_best": gap, "status": status})
    statuses = {f["status"] for f in findings}
    if "BREACH" in statuses:
        verdict = "BREACH"
    elif "BREACH_NOT_SIGNIFICANT" in statuses:
        verdict = "BREACH_NOT_SIGNIFICANT"
    else:
        verdict = "WITHIN_LIMIT"
    return {"measure": measure, "limit": limit, "verdict": verdict, "best_segment": best,
            "segments": findings, "unassessed": unassessed}


def _pct(r: dict) -> str:
    if r["value"] is None:
        return "n/a"
    return f"{r['value']:.0%} ({r['k']}/{r['n']}; 95% CI {r['ci95'][0]:.0%}-{r['ci95'][1]:.0%})"


def markdown_table(report: dict) -> str:
    """Rows shaped for the Governance Framework fairness table."""
    lines = ["| Segment | Tickets | Resolution rate | Quality score (decision correct) "
             "| Variation from best (quality, pp) | Explanation |",
             "|---|---|---|---|---|---|"]
    for dimension in DIMENSIONS:
        segments = report["dimensions"][dimension]
        quality = assess(segments, "decision_correct", QUALITY_GAP_LIMIT)
        gaps = {f["segment"]: f["gap_from_best"] for f in quality["segments"]}
        for segment, m in segments.items():
            c = m["composition"]
            note = (f"{c['should_auto']} should auto-send, {c['unanswerable']} unanswerable; "
                    f"mean confidence {m['mean_confidence']}")
            if m["n"] < MIN_N:
                note += f"; n<{MIN_N}, indicative only"
            gap = gaps.get(segment)
            lines.append(f"| {dimension}={segment} | {m['n']} | {_pct(m['resolution_rate'])} "
                         f"| {_pct(m['decision_correct'])} "
                         f"| {'n/a' if gap is None else f'{gap * 100:+.0f}'} | {note} |")
    return "\n".join(lines) + "\n"


def audit(results: list[dict], tickets: dict[str, dict]) -> dict:
    live = [r for r in results if not r.get("degraded")]
    cuts = length_cuts([ticket_words(tickets[r["ticket_id"]]) for r in live])
    records = [ticket_record(r, tickets[r["ticket_id"]], cuts) for r in live]
    dimensions = {d: by_segment(records, d) for d in DIMENSIONS}
    checks = []
    for dimension, measure, limit, binding in CHECKS:
        a = assess(dimensions[dimension], measure, limit)
        checks.append({"dimension": dimension, "binding": binding, **a})
    binding = [c for c in checks if c["binding"]]
    return {
        "tickets": len(results),
        "degraded_excluded": len(results) - len(live),
        "length_cuts_words": list(cuts),
        "overall": segment_metrics(records),
        "dimensions": dimensions,
        "checks": checks,
        "nfr05_breaches": [f"{c['dimension']}.{c['measure']}" for c in binding
                           if c["verdict"] == "BREACH"],
        "nfr05_unproven": [f"{c['dimension']}.{c['measure']}" for c in binding
                           if c["verdict"] in ("BREACH_NOT_SIGNIFICANT", "INSUFFICIENT_N")
                           or c["unassessed"]],
        "quality_basis": "label-based decision outcomes; NOT rubric-scored (B-17 judge not built)",
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", required=True, help="harness output directory")
    ap.add_argument("--tickets", default=str(TICKETS_PATH))
    ap.add_argument("--output", default="", help="defaults to <results>/fairness")
    args = ap.parse_args(argv)
    results_dir = Path(args.results)
    results = [json.loads(line) for line in (results_dir / "results.jsonl").open()]
    tickets = {t["ticket_id"]: t for t in json.loads(Path(args.tickets).read_text())}
    report = audit(results, tickets)
    report["source"] = str(results_dir)
    metrics = results_dir / "metrics_report.json"
    if metrics.exists():
        m = json.loads(metrics.read_text())
        report["models"] = {"generator": m.get("model_name"), "judge": m.get("guardrail_model")}
    out = Path(args.output) if args.output else results_dir / "fairness"
    out.mkdir(parents=True, exist_ok=True)
    (out / "fairness_report.json").write_text(json.dumps(report, indent=2))
    (out / "fairness_table.md").write_text(markdown_table(report))
    for c in report["checks"]:
        tag = "NFR-05" if c["binding"] else "info  "
        print(f"[fairness] {tag} {c['dimension']:17} {c['measure']:17} limit {c['limit']:.0%}: "
              f"{c['verdict']:22} best={c['best_segment']} unassessed={c['unassessed']}")
        for f in c["segments"]:
            print(f"             {f['segment']:14} value={f['value']:.3f} n={f['n']:>2} "
                  f"ci={f['ci95']} gap={f['gap_from_best']:+.3f} {f['status']}")
    print(f"[fairness] NFR-05 breaches: {report['nfr05_breaches'] or 'none'}")
    print(f"[fairness] NFR-05 not provable at this n: {report['nfr05_unproven'] or 'none'}")
    print(f"[fairness] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
