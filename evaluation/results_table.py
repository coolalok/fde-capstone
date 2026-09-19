"""The Evaluation Framework results table, produced by the run that it describes.

Satisfies: FR-22 (metrics computed by code).
Cites:     Evaluation Framework §4 — "the figures below are what that run must
           produce automatically rather than what you calculate by hand
           afterwards"; "The results table you should produce"; the tier-three
           governance conditions; "Report what you did, not only what you found".

Writes results_table.md and results_table.json into a harness output directory.
Every row fills Achieved, Confidence in the figure and Notes. A row whose method
the Framework prescribes and this project did not follow reads "Not measured to
method" — never a stand-in number. Any nearby evidence goes in Notes, labelled
as a different measure.

Label-dependent rows (resolution correctness, precision, cross-group variation)
need labels.* in the ticket file; the hidden set may carry none, and the rows then
say so.

Usage:
    python -m evaluation.results_table --results evaluation/results/<run>
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
from pathlib import Path
from typing import Any, Optional

from evaluation import fairness_audit as fa
from evaluation.harness import _citation_accuracy
from src.generate import strip_citation_markers
from src.guardrails import regex_pii_detections

_ROOT = Path(__file__).parent.parent
TICKETS_PATH = _ROOT / "data" / "validation_tickets.json"
# B-18 evidence: blind human scores and the judge's scores on 50 drafts.
CALIBRATION_FIXTURE = _ROOT / "tests" / "fixtures" / "judge_calibration.json"
CALIBRATION_RESULTS = _ROOT / "evaluation" / "results" / "judge_calibration_20260917"

AUTO = "auto_respond"
MET, NOT_MET, NOT_MEASURED = "MET", "NOT MET", "NOT MEASURED"

# Measure, baseline and target exactly as printed in the Framework's table.
FRAMEWORK_ROWS = (
    ("First contact resolution", "42%", "60%"),
    ("Mean time to first reply", "8 to 12 hrs", "< 5 min"),
    ("Satisfaction proxy", "3.2 / 5", "4.0"),
    ("Escalation rate", "58%", "≤ 30%"),
    ("Classification precision", "—", "85%"),
    ("Hallucination rate", "—", "≤ 5%"),
    ("Citation accuracy", "—", "95%"),
    ("Latency p95", "—", "< 3 s"),
    ("Private data occurrences", "—", "0"),
    ("Cross-group variation", "—", "< 5 pts"),
)
FCR_TARGET, REPLY_TARGET_S, ESCALATION_TARGET = 0.60, 300.0, 0.30
PRECISION_TARGET, LATENCY_TARGET_S, VARIATION_TARGET = 0.85, 3.0, 0.05
CALIBRATION_TOLERANCE_PP = 5.0


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def ci_text(k: int, n: int) -> str:
    ci = fa.wilson(k, n)
    return f"95% CI {ci[0] * 100:.0f}-{ci[1] * 100:.0f}% (n={n})" if ci else "n=0"


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile, the same rule as the harness report."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))]


def cached_calls(row: dict) -> int:
    return row.get("usage", {}).get("cached_calls", 0)


def is_live(row: dict) -> bool:
    """A ticket whose every model call reached the provider.

    Runs made before usage was recorded carry no usage and were all live. Runs
    made after usage was recorded but before cache hits were logged show a
    replayed ticket as zero calls: a ticket that completed with no call and no
    failure can only have been served from the cache."""
    u = row.get("usage")
    if u is None:
        return True
    if cached_calls(row):
        return False
    return u.get("calls", 0) > 0 or bool(row.get("classifier_error") or row.get("degraded"))


def sent_text(row: dict) -> str:
    post = row.get("response_post_guardrail") or {}
    if "answer" in post:
        return post["answer"] if post.get("sent_to_customer", True) else ""
    return strip_citation_markers(row.get("answer", ""))


def _row(measure: str, achieved: str, confidence: str, notes: str, status: str) -> dict:
    baseline, target = next((b, t) for m, b, t in FRAMEWORK_ROWS if m == measure)
    return {"measure": measure, "baseline": baseline, "target": target,
            "achieved": achieved, "confidence": confidence, "notes": notes,
            "status": status}


# ─── the ten Framework rows ──────────────────────────────────────────


def first_contact_resolution(rows: list[dict], labels: dict[str, dict]) -> dict:
    n = len(rows)
    sent = [r for r in rows if r.get("decision") == AUTO]
    if not labels:
        return _row("First contact resolution", f"{pct(len(sent) / n)} auto-sent",
                    ci_text(len(sent), n),
                    "No labels in the input, so a sent reply cannot be checked as a "
                    "correct resolution; this is the auto-send rate only.",
                    MET if len(sent) / n >= FCR_TARGET else NOT_MET)
    correct = [r for r in sent if labels[r["ticket_id"]].get("expected_route") == AUTO]
    wrong = len(sent) - len(correct)
    return _row(
        "First contact resolution",
        f"{pct(len(correct) / n)} correctly resolved ({pct(len(sent) / n)} auto-sent)",
        ci_text(len(correct), n),
        f"{wrong} of {len(sent)} sent replies went to tickets the labels say must be held, "
        "so they are not counted as resolved: a wrong answer returns as a repeat contact. "
        "Correctness is agreement with labels.expected_route, not a check of reply quality.",
        MET if len(correct) / n >= FCR_TARGET else NOT_MET)


def time_to_first_reply(rows: list[dict]) -> dict:
    sent = [r for r in rows if r.get("decision") == AUTO]
    held = len(rows) - len(sent)
    if not sent:
        return _row("Mean time to first reply", "No automated replies", "n=0",
                    f"All {held} tickets were escalated or blocked.", NOT_MET)
    secs = [r["latency_seconds"] for r in sent]
    replayed = sum(1 for r in sent if not is_live(r))
    mean = statistics.mean(secs)
    confidence = f"n={len(sent)} auto-sent tickets; median {statistics.median(secs):.1f} s"
    if replayed:
        confidence += f"; {replayed} partly replayed from the model cache (faster than live)"
    return _row(
        "Mean time to first reply", f"{mean:.1f} s", confidence,
        "Harness time from ticket read to reply ready; excludes queueing and delivery. "
        f"The {held} escalated or blocked tickets get no automated reply (holding reply is "
        "out of scope, PRD Table 6), so their first reply comes from the human queue.",
        MET if mean < REPLY_TARGET_S else NOT_MET)


def satisfaction_proxy(evidence: dict) -> dict:
    b18 = evidence.get("b18")
    nearby = ""
    if b18:
        nearby = (f" Nearest evidence: B-18, where one person scored {b18['n']} drafts from "
                  f"{b18['source_run']} on the judge's RAG rubric (mean answer relevance "
                  f"{b18['human_answer_relevance_mean']:.2f}/5) — a different rubric, a "
                  "different run and a single scorer, so not a satisfaction proxy.")
    return _row("Satisfaction proxy", "Not measured", "No scored sample on this run",
                "The Framework's method is human review of a stated sample of responses "
                "against a rubric, reporting sample size, rubric and scorers. Not done for "
                "this run." + nearby, NOT_MEASURED)


def escalation_rate(rows: list[dict]) -> dict:
    n = len(rows)
    escalated = sum(1 for r in rows if r.get("decision") == "escalate")
    blocked = sum(1 for r in rows if r.get("decision") == "block")
    fail_safe = sum(1 for r in rows if any(g.get("fail_safe") for g in r.get("guardrails", [])))
    k = escalated + blocked
    return _row(
        "Escalation rate", pct(k / n), ci_text(k, n),
        f"{escalated} escalated by routing and {blocked} blocked by a guardrail; "
        f"{fail_safe} tickets were blocked because a check could not run (fail-safe), "
        "not because it found a fault.",
        MET if k / n <= ESCALATION_TARGET else NOT_MET)


def classification_precision(metrics: dict, labels: dict[str, dict]) -> dict:
    per = metrics.get("technical_metrics", {}).get("intent_per_class")
    if not labels or not per:
        return _row("Classification precision", "Not measured", "No labels",
                    "Needs labels.intent in the input.", NOT_MEASURED)
    classes = {c: v for c, v in per.items() if v["support"] > 0}
    precisions = [v["precision"] for v in classes.values()]
    passing = sum(1 for p in precisions if p >= PRECISION_TARGET)
    supports = [v["support"] for v in classes.values()]
    small = sum(1 for s in supports if s < 5)
    weakest = sorted(classes.items(), key=lambda kv: kv[1]["precision"])[:3]
    weak = "; ".join(f"{c} {v['precision'] * 100:.0f}% (n={v['support']})" for c, v in weakest)
    return _row(
        "Classification precision",
        f"{pct(statistics.mean(precisions))} mean over {len(classes)} classes; "
        f"{passing} of {len(classes)} at ≥85%",
        f"Per-class n: median {statistics.median(supports):.0f}; {small} classes have "
        "fewer than 5 tickets, so per-class figures are indicative only",
        f"Weakest: {weak}. Overall intent accuracy "
        f"{pct(metrics['technical_metrics'].get('intent_accuracy', 0))}. The target is "
        "per class, so it is met only if every class reaches 85%.",
        MET if passing == len(classes) else NOT_MET)


def hallucination_rate(evidence: dict) -> dict:
    b18 = evidence.get("b18")
    nearby = ""
    if b18:
        nearby = (f" Nearest evidence (B-18, drafts from {b18['source_run']}): one human "
                  f"found an unsupported claim in {b18['human_unsupported']} of {b18['n']} "
                  f"drafts; the LLM judge in {b18['judge_unsupported']} of {b18['n']}; the "
                  f"judge failed calibration (pooled Spearman {b18['pooled_spearman']} "
                  "against 0.70).")
    return _row("Hallucination rate", "Not measured to method", "—",
                "The Framework requires at least fifty responses assessed independently by "
                "two people, with their agreement reported. This project had one human "
                "assessor." + nearby, NOT_MEASURED)


def citation_accuracy(rows: list[dict], metrics: dict, labels: dict[str, dict]) -> dict:
    doc = metrics.get("technical_metrics", {}).get("citation_accuracy")
    if doc is None and labels:
        doc = _citation_accuracy(rows, labels)
    nearby = ""
    if doc and doc.get("n"):
        nearby = (f" Nearest evidence: the cited ARTICLE was one the labels expect in "
                  f"{pct(doc['precision'])} of citations over {doc['n']} drafts (recall "
                  f"{pct(doc['recall'])}) — a check of the right source, not of support.")
    return _row("Citation accuracy", "Not measured to method", "—",
                "The Framework checks each citation against the sentence it is attached "
                "to. Sentence-level support was not assessed." + nearby, NOT_MEASURED)


def latency_p95(rows: list[dict], metrics: dict) -> dict:
    live = [r["latency_seconds"] for r in rows if is_live(r)]
    replayed = len(rows) - len(live)
    if not live:
        return _row("Latency p95", "Not measured", "No live tickets",
                    "Every ticket was replayed from the model cache.", NOT_MEASURED)
    value = p95(live)
    confidence = f"n={len(live)} live tickets; max {max(live):.1f} s"
    if replayed:
        confidence += f"; {replayed} cache-replayed tickets excluded"
    return _row(
        "Latency p95", f"{value:.1f} s", confidence,
        "End to end per ticket, including retrieval and every model call, run in sequence. "
        f"Models: {metrics.get('model_name')} drafting, {metrics.get('guardrail_model')} "
        "guardrails.",
        MET if value < LATENCY_TARGET_S else NOT_MET)


def private_data(rows: list[dict], metrics: dict) -> dict:
    sent = [r for r in rows if r.get("decision") == AUTO]
    hits = [(r["ticket_id"], d["category"]) for r in sent
            for d in regex_pii_detections(sent_text(r))]
    blocked = metrics.get("governance_metrics", {}).get("pii_detections", 0)
    found = "; ".join(f"{t} ({c})" for t, c in hits)
    return _row(
        "Private data occurrences", str(len(hits)),
        f"Automated scan of all {len(sent)} sent replies; manual sample review: not done",
        f"The scan uses the PII guardrail's own patterns (email, API key, phone, account "
        f"number), independently of the judge's verdict. The guardrail blocked {blocked} "
        "drafts for private data before sending." + (f" Found: {found}." if found else ""),
        MET if not hits else NOT_MET)


def cross_group_variation(rows: list[dict], tickets: dict[str, dict]) -> tuple[dict, dict]:
    labelled = {t: v for t, v in tickets.items() if "labels" in v}
    if len(labelled) < len(rows):
        row = _row("Cross-group variation", "Not measured", "No labels",
                   "Needs labels.* in the input.", NOT_MEASURED)
        return row, {}
    report = fa.audit(rows, tickets)
    gaps = []
    for dimension in ("language_fluency", "customer_region", "customer_tier"):
        a = fa.assess(report["dimensions"][dimension], "decision_correct",
                      VARIATION_TARGET)
        for f in a["segments"]:
            if f["status"] != "INSUFFICIENT_N":
                gaps.append((f["gap_from_best"], dimension, f["segment"], a["best_segment"],
                             f["n"], f["status"]))
    if not gaps:
        return _row("Cross-group variation", "Not measured", "Every segment under n=10",
                    "No segment reached the audit's minimum size.", NOT_MEASURED), report
    gap, dimension, segment, best, n, status = max(gaps)
    return _row(
        "Cross-group variation",
        f"{gap * 100:.0f} pts ({dimension}: {segment} vs {best})",
        f"{status.replace('_', ' ').lower()} at n={n}; segments under n=10 excluded",
        "Quality here is decision correctness against labels, not a rubric score, across "
        "language fluency, region and tier. NFR-05 allows 15 points; this Framework target "
        "is 5. Full per-segment figures: fairness audit.",
        MET if gap < VARIATION_TARGET else NOT_MET), report


# ─── tier three: governance conditions ──────────────────────────────


def governance_conditions(rows: list[dict], metrics: dict, pii_row: dict,
                          variation_row: dict) -> list[dict]:
    g = metrics.get("governance_metrics", {})
    logged, n = g.get("decisions_logged"), len(rows)
    calibration = [b for b in g.get("confidence_calibration", []) if b.get("sufficient_n")]
    band = next((b for b in g.get("confidence_calibration", [])
                 if b["bucket"] == "0.8-0.9"), None)
    worst = max(calibration, key=lambda b: abs(b["gap_pp"]), default=None)
    calib_status = NOT_MEASURED if worst is None else (
        MET if abs(worst["gap_pp"]) <= CALIBRATION_TOLERANCE_PP else NOT_MET)
    calib_text = "No confidence band with enough tickets" if worst is None else (
        f"largest gap {worst['gap_pp']:+.1f} pts in band {worst['bucket']} "
        f"(stated {worst['stated_avg']:.2f}, observed {worst['observed']:.2f}, n={worst['n']})")
    if band:
        calib_text += (f"; 0.80-0.90 band observed {band['observed']:.2f} "
                       f"(n={band['n']}, Framework expects about 0.85)")
    return [
        {"condition": "Private data in outbound text", "requirement": "Zero occurrences.",
         "result": f"{pii_row['achieved']} ({pii_row['confidence']})",
         "status": pii_row["status"]},
        {"condition": "Quality across customer groups",
         "requirement": "Under five percentage points of variation.",
         "result": f"{variation_row['achieved']} ({variation_row['confidence']})",
         "status": variation_row["status"]},
        {"condition": "Decision logging", "requirement": "Complete coverage.",
         "result": f"{logged} of {n} tickets logged; reconciles={g.get('reconciles')}",
         "status": MET if g.get("reconciles") and logged == n else NOT_MET},
        {"condition": "Confidence calibration",
         "requirement": "Stated confidence within five points of observed accuracy.",
         "result": calib_text, "status": calib_status},
    ]


# ─── assembly ────────────────────────────────────────────────────────


def b18_evidence() -> Optional[dict]:
    """Summarise the B-18 calibration run, if its files are present."""
    judged_path = CALIBRATION_RESULTS / "judged.jsonl"
    agreement_path = CALIBRATION_RESULTS / "agreement.json"
    if not (CALIBRATION_FIXTURE.exists() and judged_path.exists() and agreement_path.exists()):
        return None
    fixture = json.loads(CALIBRATION_FIXTURE.read_text())
    human = [i["human_scores"] for i in fixture["items"]
             if all(v is not None for v in i["human_scores"].values())]
    judged = [json.loads(line) for line in judged_path.open()]
    scored = [j["scores"] for j in judged if j.get("scores")]
    agreement = json.loads(agreement_path.read_text())
    return {
        "source_run": Path(fixture.get("source_run", "")).parent.name or "unknown",
        "n": len(human),
        "human_answer_relevance_mean": statistics.mean(h["answer_relevance"] for h in human),
        "human_unsupported": sum(1 for h in human if h["groundedness"] < 5),
        "judge_unsupported": sum(1 for s in scored if s["groundedness"] < 5),
        "pooled_spearman": agreement["pooled"]["spearman"],
    }


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build(rows: list[dict], metrics: dict, tickets: dict[str, dict], *,
          hidden_set_runs: int = 0, evidence: Optional[dict] = None) -> dict:
    evidence = {"b18": b18_evidence()} if evidence is None else evidence
    labels = {t: v["labels"] for t, v in tickets.items() if "labels" in v}
    pii = private_data(rows, metrics)
    variation, _ = cross_group_variation(rows, tickets)
    table = [
        first_contact_resolution(rows, labels),
        time_to_first_reply(rows),
        satisfaction_proxy(evidence),
        escalation_rate(rows),
        classification_precision(metrics, labels),
        hallucination_rate(evidence),
        citation_accuracy(rows, metrics, labels),
        latency_p95(rows, metrics),
        pii,
        variation,
    ]
    cost = metrics.get("cost_metrics", {})
    run_id = metrics.get("run_id", "")
    stamp = run_id.split("-")[1] if run_id.count("-") >= 2 else ""
    header = {
        "run_id": run_id,
        "run_date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 else "unknown",
        "tickets": len(rows),
        "generator_model": metrics.get("model_name"),
        "guardrail_model": metrics.get("guardrail_model"),
        "guardrails_enabled": metrics.get("guardrails_enabled"),
        "confidence_threshold": metrics.get("confidence_threshold"),
        "model_cache_enabled": cost.get("model_cache_enabled"),
        "cached_calls": cost.get("cached_calls"),
        "live_calls": cost.get("live_calls"),
        "tickets_with_replayed_calls": sum(1 for r in rows if not is_live(r)),
        "code_version": git_commit(),
        "hidden_set_runs": hidden_set_runs,
    }
    return {"header": header, "rows": table,
            "governance": governance_conditions(rows, metrics, pii, variation),
            "business": business_reading(rows, labels),
            "limitations": limitations(header, table)}


def business_reading(rows: list[dict], labels: dict[str, dict]) -> list[str]:
    """Carry the technical numbers through to the queue, as the Framework asks."""
    n = len(rows)
    sent = [r for r in rows if r.get("decision") == AUTO]
    lines = [f"{len(sent)} of {n} tickets ({pct(len(sent) / n)}) were answered without a "
             f"human; {n - len(sent)} ({pct((n - len(sent)) / n)}) went to the human queue "
             "(baseline escalation 58%)."]
    if labels:
        wrong = sum(1 for r in sent if labels[r["ticket_id"]].get("expected_route") != AUTO)
        correct = len(sent) - wrong
        lines.append(f"{wrong} of those answers went to tickets that should have reached a "
                     f"person, so correct automated resolution is {pct(correct / n)} against "
                     "the 42% human baseline: the system moves work off the queue, but not yet "
                     "more correctly resolved work.")
    return lines


def limitations(header: dict, table: list[dict]) -> list[str]:
    """Facts for the sentence the report needs: 'the figures above should be treated
    with caution because ...'. The author writes the sentence."""
    items = [f"A single run of {header['tickets']} tickets: one ticket moves a rate by "
             f"{100 / header['tickets']:.1f} points, and 95% intervals are wide."]
    if header.get("tickets_with_replayed_calls"):
        items.append(f"{header['tickets_with_replayed_calls']} tickets were partly replayed "
                     "from the model cache (D-08), so they describe the run that filled it.")
    unmeasured = [r["measure"] for r in table if r["status"] == NOT_MEASURED]
    if unmeasured:
        items.append("Not measured to the Framework's method: " + ", ".join(unmeasured) + ".")
    items.append("Correctness is agreement with the dataset's labels, some of which are "
                 "debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 "
                 "covers it).")
    items.append(f"Hidden evaluation set runs: {header['hidden_set_runs']}. These figures are "
                 "from a labelled validation set, not the held-out test set.")
    return items


def to_markdown(t: dict) -> str:
    h = t["header"]
    if h["model_cache_enabled"] is None:
        cache = "not recorded (run predates cache logging)"
    else:
        cache = (f"{'on' if h['model_cache_enabled'] else 'off'} ({h['cached_calls']} "
                 f"cached calls, {h['live_calls']} live)")
    out = ["# Evaluation results", "",
           f"Run `{h['run_id']}` on {h['run_date']}: {h['tickets']} tickets. Code "
           f"`{h['code_version']}` at table generation. Drafting model "
           f"`{h['generator_model']}`, guardrail model `{h['guardrail_model']}`, confidence "
           f"threshold {h['confidence_threshold']}, guardrails "
           f"{'on' if h['guardrails_enabled'] else 'off'}. Model cache {cache}; "
           f"{h['tickets_with_replayed_calls']} tickets replayed. Runs against the hidden "
           f"evaluation set: {h['hidden_set_runs']}.", "",
           "| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |",
           "|---|---|---|---|---|---|"]
    for r in t["rows"]:
        cells = [r["measure"], r["baseline"], r["target"], f"{r['achieved']} ({r['status']})",
                 r["confidence"], r["notes"]]
        out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    out += ["", "## Governance conditions (tier three)", "",
            "| Condition | Requirement | Result | Status |", "|---|---|---|---|"]
    for g in t["governance"]:
        out.append(f"| {g['condition']} | {g['requirement']} | {g['result']} | {g['status']} |")
    out += ["", "## What the numbers mean for the queue", ""]
    out += [f"- {line}" for line in t["business"]]
    out += ["", "## Facts for \"the figures above should be treated with caution because\"",
            ""]
    out += [f"- {line}" for line in t["limitations"]]
    return "\n".join(out) + "\n"


def write(output_dir: Path, rows: list[dict], metrics: dict, tickets: dict[str, dict], *,
          hidden_set_runs: int = 0) -> dict:
    table = build(rows, metrics, tickets, hidden_set_runs=hidden_set_runs)
    (output_dir / "results_table.json").write_text(json.dumps(table, indent=2))
    (output_dir / "results_table.md").write_text(to_markdown(table))
    return table


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", required=True, help="harness output directory")
    ap.add_argument("--tickets", default=str(TICKETS_PATH), help="the input the run used")
    ap.add_argument("--hidden-set-runs", type=int, default=0,
                    help="how many times the hidden evaluation set has been run")
    args = ap.parse_args(argv)
    out = Path(args.results)
    rows = [json.loads(line) for line in (out / "results.jsonl").open()]
    metrics: dict[str, Any] = json.loads((out / "metrics_report.json").read_text())
    tickets = {t["ticket_id"]: t for t in json.loads(Path(args.tickets).read_text())}
    table = write(out, rows, metrics, tickets, hidden_set_runs=args.hidden_set_runs)
    for r in table["rows"]:
        print(f"[results] {r['measure']:26} {r['status']:13} {r['achieved']}")
    print(f"[results] wrote {out / 'results_table.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
