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
from evaluation.harness import (_citation_accuracy, _intent_confusion, _intent_precision_recall,
                                failure_breakdown, routing_outcomes, stage_latency)
from src.generate import strip_citation_markers
from src.guardrails import regex_pii_detections

_ROOT = Path(__file__).parent.parent
TICKETS_PATH = _ROOT / "data" / "validation_tickets.json"
# B-18 evidence: blind human scores and the judge's scores on 50 drafts.
CALIBRATION_FIXTURE = _ROOT / "tests" / "fixtures" / "judge_calibration.json"
CALIBRATION_RESULTS = _ROOT / "evaluation" / "results" / "judge_calibration_20260917"
# Read only to find tickets whose text also appears there with a different label.
DEV_TICKETS_PATH = _ROOT / "data" / "development_tickets.json"

AUTO = "auto_respond"
MET, NOT_MET, NOT_MEASURED = "MET", "NOT MET", "NOT MEASURED"

# Measure, baseline and target exactly as printed in the Framework's results
# table. The last two are not in that table but are asked for elsewhere in the
# Framework: repeat contacts in the tier-one table, availability in tier two.
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
    ("Repeat contacts", "Not measured", "Halved"),
    ("Availability", "—", "99.5%"),
)
FCR_TARGET, REPLY_TARGET_S, ESCALATION_TARGET = 0.60, 300.0, 0.30
PRECISION_TARGET, LATENCY_TARGET_S, VARIATION_TARGET = 0.85, 3.0, 0.05
CALIBRATION_TOLERANCE_PP = 5.0
AVAILABILITY_TARGET = 0.995

# fairness_audit.assess already decides whether a segment's gap is separable
# from the best segment's interval. This row takes its status from that verdict
# rather than re-deriving one from the gap alone, so the Confidence cell and the
# status cannot contradict each other. A breach that is not significant at these
# segment sizes is a gap this sample cannot resolve: unmeasured, not failed.
VARIATION_STATUS = {"WITHIN_LIMIT": MET, "BREACH": NOT_MET,
                    "BREACH_NOT_SIGNIFICANT": NOT_MEASURED}


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
        # Without labels a sent reply cannot be checked as a correct
        # resolution, so there is nothing to compare with the 60% target:
        # deleting the labels must not turn a failing run into a passing one.
        return _row("First contact resolution", "Not measured",
                    f"No labels in the input (n={n} tickets)",
                    "Needs labels.expected_route to tell a resolved contact from a wrong "
                    f"answer that comes back. Nearest evidence: {pct(len(sent) / n)} of "
                    f"tickets were auto-sent ({ci_text(len(sent), n)}) — a different "
                    "measure, since sending a reply is not evidence of resolving anything.",
                    NOT_MEASURED)
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


def repeat_contacts(rows: list[dict], tickets: dict[str, dict],
                    labels: dict[str, dict]) -> dict:
    """The same customer raising the same issue again within a week (tier one).

    An offline run cannot see a customer come back, so the achieved figure is
    unmeasured. The baseline is not: the Dataset Guide calls history.* "the
    current baseline", and history.repeat_contact records whether each ticket
    came back under human handling. That is the figure "Halved" is set against.
    """
    history = [tickets[r["ticket_id"]]["history"] for r in rows
               if "repeat_contact" in tickets.get(r["ticket_id"], {}).get("history", {})]
    if not history:
        return _row("Repeat contacts", "Not measured",
                    "An offline run cannot observe a customer returning",
                    "No history.repeat_contact in the input, so there is no baseline to "
                    "halve either.", NOT_MEASURED)
    k, n = sum(1 for h in history if h["repeat_contact"]), len(history)
    leading = ""
    if labels:
        routing = routing_outcomes(rows, labels)
        leading = (f" Leading indicator: {routing['wrong_sends']} of {routing['sent']} sent "
                   "replies went to tickets the labels say must be held, the kind of reply "
                   "that comes back as a repeat contact.")
    row = _row("Repeat contacts", "Not measured",
               "An offline run cannot observe a customer returning",
               f"Baseline from history.repeat_contact: {k} of {n} of these tickets "
               f"({pct(k / n)}) came back under human handling, so halved is "
               f"{pct(k / n / 2)} or lower.{leading}", NOT_MEASURED)
    row["baseline"] = f"{pct(k / n)} (history, n={n})"
    return row


def availability(rows: list[dict]) -> dict:
    """Tickets served with every stage working (tier two, 99.5%).

    "Include behaviour when the model provider fails": a ticket whose model call
    failed still gets a decision (FR-23 escalates it), so the Notes count those
    separately from tickets the run lost, which is none by construction.
    """
    n = len(rows)
    failed = [r for r in rows
              if r.get("degraded") or r.get("classifier_error") or r.get("generator_error")
              or any(g.get("fail_safe") for g in r.get("guardrails", []))]
    k = n - len(failed)
    decided = sum(1 for r in rows if r.get("decision"))
    unconfirmed = (" At this n the interval cannot confirm 99.5%."
                   if fa.wilson(k, n)[0] < AVAILABILITY_TARGET else "")
    return _row(
        "Availability", pct(k / n), ci_text(k, n),
        f"{k} of {n} tickets had every stage work. {len(failed)} hit a model-call or "
        "pipeline failure (degraded ticket, classifier or generator error, or a guardrail "
        f"that could not run); {decided} of {n} still received a decision, a failure "
        "escalating rather than erroring. One run's tickets are not uptime over time."
        + unconfirmed,
        MET if k / n >= AVAILABILITY_TARGET else NOT_MET)


def classification_precision(rows: list[dict], metrics: dict, labels: dict[str, dict]) -> dict:
    per = metrics.get("technical_metrics", {}).get("intent_per_class")
    if per and labels and any("predicted" not in v for v in per.values()):
        # A run recorded before the precision denominator was stored: recompute
        # from the run's own rows, as citation_accuracy does. The stored
        # precision cannot be read instead, because 0/0 and a measured 0.0 were
        # both written as 0.0 and are no longer distinguishable.
        per = _intent_precision_recall(rows, labels)
    if not labels or not per:
        return _row("Classification precision", "Not measured", "No labels",
                    "Needs labels.intent in the input.", NOT_MEASURED)
    classes = {c: v for c, v in per.items() if v["support"] > 0}
    # A class that was never predicted has no precision denominator. It is not
    # 0% precise; it is unmeasured, and averaging it in as a zero understates
    # every other class's work.
    measured = {c: v for c, v in classes.items() if v["precision"] is not None}
    unmeasured = sorted(set(classes) - set(measured))
    if not measured:
        return _row("Classification precision", "Not measured",
                    f"No class was predicted on any of {len(classes)} labelled classes",
                    "Precision has no denominator on this run: nothing was predicted.",
                    NOT_MEASURED)
    precisions = [v["precision"] for v in measured.values()]
    passing = sum(1 for p in precisions if p >= PRECISION_TARGET)
    predicted = [v["predicted"] for v in classes.values()]
    thin = sum(1 for p in predicted if 0 < p < 5)
    weakest = sorted(measured.items(), key=lambda kv: kv[1]["precision"])[:3]
    weak = "; ".join(f"{c} {v['precision'] * 100:.0f}% (n={v['predicted']})" for c, v in weakest)
    never = (f" {len(unmeasured)} class(es) never predicted, so their precision is "
             f"undefined rather than 0% and is excluded from the mean: "
             f"{', '.join(unmeasured)}.") if unmeasured else ""
    return _row(
        "Classification precision",
        f"{pct(statistics.mean(precisions))} mean over the {len(measured)} classes with "
        f"a precision denominator; {passing} of {len(measured)} at ≥85%",
        f"Precision n (predictions made per class): median "
        f"{statistics.median(predicted):.0f}; {thin} classes were predicted fewer than 5 "
        f"times and {len(unmeasured)} never, so per-class figures are indicative only",
        f"Weakest: {weak}.{never} Overall intent accuracy "
        f"{pct(metrics['technical_metrics'].get('intent_accuracy', 0))}. The target is "
        "per class, so it is met only if every class reaches 85%.",
        NOT_MET if passing < len(measured) else (NOT_MEASURED if unmeasured else MET))


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
    excluded = 0
    for dimension in ("language_fluency", "customer_region", "customer_tier"):
        a = fa.assess(report["dimensions"][dimension], "decision_correct",
                      VARIATION_TARGET)
        best_n = next((f["n"] for f in a["segments"] if f["segment"] == a["best_segment"]), 0)
        for f in a["segments"]:
            if f["status"] == "INSUFFICIENT_N":
                excluded += 1
                continue
            gaps.append((f["gap_from_best"], dimension, f["segment"], a["best_segment"],
                         f["n"], best_n, f["status"]))
    if not gaps:
        return _row("Cross-group variation", "Not measured",
                    f"Every segment under n={fa.MIN_N}",
                    "No segment reached the audit's minimum size.", NOT_MEASURED), report
    gap, dimension, segment, best, n, best_n, status = max(gaps)
    # Name both sides of the comparison, and only claim an exclusion that ran.
    small = f"; {excluded} segments under n={fa.MIN_N} excluded" if excluded else ""
    return _row(
        "Cross-group variation",
        f"{gap * 100:.0f} pts ({dimension}: {segment} vs {best})",
        f"{status.replace('_', ' ').lower()}: {segment} n={n} against {best} n={best_n}{small}",
        "Quality here is decision correctness against labels, not a rubric score, across "
        "language fluency, region and tier. The status is the audit's own per-segment "
        "verdict: a gap wider than the target whose interval overlaps the best segment's "
        "is a gap this sample cannot resolve, so it is reported as not measured rather "
        "than as a failure. NFR-05 allows 15 points; this Framework target is 5. Full "
        "per-segment figures: fairness audit.",
        VARIATION_STATUS[status]), report


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
    # Say what was left out and why, so the figure cannot read as a clean sweep.
    # An abstention is a refusal to classify, not a stated probability of being
    # right; see ABSTENTION_INTENTS in evaluation/harness.py.
    abstained = g.get("calibration_abstentions_excluded") or 0
    fallbacks = g.get("calibration_fallbacks_excluded") or 0
    if abstained or fallbacks:
        parts = []
        if abstained:
            parts.append(f"{abstained} abstention{'s' if abstained != 1 else ''} "
                         f"(confidence 0.00 with no intent named)")
        if fallbacks:
            parts.append(f"{fallbacks} classifier fallback"
                         f"{'s' if fallbacks != 1 else ''}")
        calib_text += (f"; excluded from the gap: {' and '.join(parts)}, "
                       f"which state no probability")
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
    fixture = json.loads(CALIBRATION_FIXTURE.read_text(encoding="utf-8"))
    human = [i["human_scores"] for i in fixture["items"]
             if all(v is not None for v in i["human_scores"].values())]
    judged = [json.loads(line) for line in judged_path.open(encoding="utf-8")]
    scored = [j["scores"] for j in judged if j.get("scores")]
    agreement = json.loads(agreement_path.read_text(encoding="utf-8"))
    return {
        "source_run": Path(fixture.get("source_run", "")).parent.name or "unknown",
        "n": len(human),
        "human_answer_relevance_mean": statistics.mean(h["answer_relevance"] for h in human),
        "human_unsupported": sum(1 for h in human if h["groundedness"] < 5),
        "judge_unsupported": sum(1 for s in scored if s["groundedness"] < 5),
        "pooled_spearman": agreement["pooled"]["spearman"],
    }


# The paths whose contents decide what a run does. A commit that only adds
# results does not change the system, so it must not change the version.
CODE_PATHS = ("src", "prompts", "evaluation/*.py")


def git_commit() -> str:
    """The last commit that changed code, marked when code has uncommitted edits."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    try:
        commit = git("log", "-1", "--format=%h", "--", *CODE_PATHS)
        dirty = git("status", "--porcelain", "--", *CODE_PATHS)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit} + uncommitted changes" if dirty else commit


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
        classification_precision(rows, metrics, labels),
        hallucination_rate(evidence),
        citation_accuracy(rows, metrics, labels),
        latency_p95(rows, metrics),
        pii,
        variation,
        repeat_contacts(rows, tickets, labels),
        availability(rows),
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
        "kill_switch_active": metrics.get("governance_metrics", {}).get(
            "kill_switch_active", False),
    }
    return {"header": header, "rows": table,
            "governance": governance_conditions(rows, metrics, pii, variation),
            "business": business_reading(rows, labels),
            "routing": routing_outcomes(rows, labels) if labels else None,
            "failures": failure_breakdown(rows, labels) if labels else None,
            "intent": intent_by_class(rows, labels),
            "stages": stage_latency(rows),
            "limitations": limitations(header, table, rows, tickets)}


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


def contested_labels(rows: list[dict], tickets: dict[str, dict]) -> dict:
    """Tickets in this run whose exact text carries a different label elsewhere.

    The dataset repeats ticket text: 50 groups of identical subject+body across
    the labelled sets disagree on expected_route or answerable_from_docs, and two
    such pairs sit inside the validation set itself (VAL-0012/VAL-0034,
    VAL-0060/VAL-0061). No system can be right on both members of a pair, so a
    share of any error count here is the dataset disagreeing with itself. Scored
    against the run's own ticket file plus development_tickets.json when readable;
    a hidden set with no repeats simply reports zero.
    """
    def key(t: dict) -> tuple:
        return ((t.get("subject") or "").strip(), (t.get("body") or "").strip())

    def label(t: dict) -> tuple:
        lab = t.get("labels") or {}
        return (lab.get("expected_route"), lab.get("answerable_from_docs"))

    pool = [t for t in tickets.values() if t.get("labels")]
    if not pool:
        return {"n": 0, "tickets": [], "pairs_within_run": 0}
    try:
        pool += [t for t in json.loads(DEV_TICKETS_PATH.read_text(encoding="utf-8"))
                 if t.get("ticket_id") not in tickets]
    except (OSError, ValueError):  # no dev file to compare against; run's own is enough
        pass
    by_text: dict[tuple, list[dict]] = {}
    for t in pool:
        by_text.setdefault(key(t), []).append(t)
    ids = {t["ticket_id"] for group in by_text.values() if len(group) > 1
           and len({label(x) for x in group}) > 1 for t in group}
    # A pair inside THIS run: both members are the run's own tickets and they
    # disagree with each other. A dev copy disagreeing does not make one.
    within = sum(1 for group in by_text.values()
                 if len({label(x) for x in group if x["ticket_id"] in tickets}) > 1)
    here = sorted(i for i in ids if i in {r["ticket_id"] for r in rows})
    return {"n": len(here), "tickets": here, "pairs_within_run": within}


def limitations(header: dict, table: list[dict], rows: Optional[list[dict]] = None,
                tickets: Optional[dict[str, dict]] = None) -> list[str]:
    """Facts for the sentence the report needs: 'the figures above should be treated
    with caution because ...'. The author writes the sentence."""
    items = [f"A single run of {header['tickets']} tickets: one ticket moves a rate by "
             f"{100 / header['tickets']:.1f} points, and 95% intervals are wide."]
    if header.get("kill_switch_active"):
        items.append("The kill switch was active: rule 0 escalated every ticket before any "
                     "other rule could fire, so no routing or resolution figure here "
                     "describes the system's own behaviour (Governance Framework §5, D-15).")
    if header.get("tickets_with_replayed_calls"):
        items.append(f"{header['tickets_with_replayed_calls']} tickets were partly replayed "
                     "from the model cache (D-08), so they describe the run that filled it.")
    unmeasured = [r["measure"] for r in table if r["status"] == NOT_MEASURED]
    if unmeasured:
        items.append("Not measured to the Framework's method: " + ", ".join(unmeasured) + ".")
    # Name the set this run actually used. Both sentences below used to hardcode
    # the validation set and a VAL- example, which a development-set run then
    # printed verbatim — citing a ticket it had never processed.
    prefixes = {str(r.get("ticket_id", "")).split("-")[0]
                for r in (rows or []) if r.get("ticket_id")}
    source = {"VAL": "labelled validation set", "DEV": "labelled development set"}.get(
        next(iter(prefixes)) if len(prefixes) == 1 else "", "labelled data")
    debatable = ("e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it"
                 if any(str(r.get("ticket_id", "")) == "VAL-0004" for r in (rows or []))
                 else None)
    items.append("Correctness is agreement with the dataset's labels, some of which are "
                 "debatable" + (f" ({debatable})" if debatable else "") + ".")
    contested = contested_labels(rows or [], tickets or {})
    if contested["n"]:
        pairs = contested["pairs_within_run"]
        items.append(
            f"{contested['n']} of {header['tickets']} tickets have text that appears "
            "elsewhere in the labelled data with a different expected_route or "
            "answerable_from_docs, so their correct answer is set by which copy was "
            "filed here, not by the ticket"
            + (f"; {pairs} such {'pair sits' if pairs == 1 else 'pairs sit'} inside "
               "this run, where no system can be right on both" if pairs else "") + ".")
    items.append(f"Hidden evaluation set runs: {header['hidden_set_runs']}. These figures are "
                 f"from a {source}, not the held-out test set.")
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
           f"evaluation set: {h['hidden_set_runs']}."
           + (" **Kill switch ACTIVE: automatic answering was halted, so every ticket "
              "escalated by rule 0 (D-15) and these figures describe a halted system.**"
              if h.get("kill_switch_active") else ""), "",
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
    out += routing_markdown(t.get("routing"), t.get("failures"))
    out += intent_markdown(t.get("intent"))
    out += stages_markdown(t.get("stages"))
    out += ["", "## Facts for \"the figures above should be treated with caution because\"",
            ""]
    out += [f"- {line}" for line in t["limitations"]]
    return "\n".join(out) + "\n"


def routing_markdown(routing: Optional[dict], failures: Optional[dict]) -> list[str]:
    """Wrong sends and wrong holds kept apart, and the stage each one traces to."""
    if not routing:
        return []
    out = ["", "## Routing against the labels", "",
           "The FCR figure divides correct sends by every ticket. It hides two failures "
           "with opposite fixes: sending what should be held, and holding what could "
           "be sent.", "",
           "| Measure | Value |", "|---|---|",
           f"| Replies sent | {routing['sent']} of {routing['n']} |",
           f"| Send precision (sent replies that should have been sent) | "
           f"{_maybe_pct(routing['send_precision'])} ({routing['correct_sends']} of "
           f"{routing['sent']}) |",
           f"| Send coverage (tickets that should be answered, answered) | "
           f"{_maybe_pct(routing['send_coverage'])} ({routing['correct_sends']} of "
           f"{routing['should_send']}) |",
           f"| Wrong sends | {routing['wrong_sends']} ({pct(routing['wrong_send_rate'])} "
           f"of tickets) |",
           f"| Wrong holds | {routing['wrong_holds']} ({pct(routing['wrong_hold_rate'])} "
           f"of tickets) |"]
    if failures and failures["wrong_decisions"]:
        out += ["", f"Where the {failures['wrong_decisions']} wrong decisions come from. "
                "Each is attributed to one stage by `evaluation.harness.failure_stage`: a "
                "wrong send to what the labels say is wrong with sending, a wrong hold to "
                "the earliest stage that explains it.", "",
                "| Stage: reason | Tickets |", "|---|---|"]
        out += [f"| {reason} | {n} |" for reason, n in failures["by_reason"].items()]
    return out


def intent_by_class(rows: list[dict], labels: dict[str, dict]) -> Optional[dict]:
    """Per-class precision and recall, and the confusion matrix behind them.

    Evaluation Framework, "Intent classification precision and recall": "Report
    both, per class, and include the confusion matrix in your appendix."
    Computed from the rows, not read from metrics_report.json, so the table of a
    run recorded before the matrix existed can be regenerated without re-running
    it. None when the labels carry no intent.
    """
    per = _intent_precision_recall(rows, labels)
    if not per:
        return None
    return {"per_class": per, "confusion": _intent_confusion(rows, labels)}


def intent_markdown(intent: Optional[dict]) -> list[str]:
    """The per-class table and the confusion matrix, one row per class."""
    if not intent:
        return []
    per, confusion = intent["per_class"], intent["confusion"]
    classes = list(per)
    out = ["", "## Intent classification by class", "",
           "Precision is over the tickets predicted as the class (n predicted); recall "
           "is over the tickets labelled as it (n labelled). A class never predicted "
           "has no precision and one never labelled has no recall: n/a, not 0%.", "",
           "| Intent | n labelled | n predicted | Precision | Recall |",
           "|---|---|---|---|---|"]
    out += [f"| {c} | {v['support']} | {v['predicted']} | {_maybe_pct(v['precision'])} "
            f"| {_maybe_pct(v['recall'])} |" for c, v in per.items()]
    out += ["", "### Intent confusion matrix", "",
            "Rows are the labelled intent; columns are the predicted intent, numbered as "
            "the rows are. The diagonal (bold) is correct classifications; any other "
            "count is tickets mistaken for that column's class. Blank cells are zero.", "",
            "| Labelled / predicted | " + " | ".join(str(i) for i in range(1, len(classes) + 1))
            + " |",
            "|---|" + "---|" * len(classes)]
    for i, gold in enumerate(classes, 1):
        row = confusion.get(gold, {})
        cells = [("**{}**" if pred == gold else "{}").format(row[pred]) if row.get(pred) else ""
                 for pred in classes]
        out.append(f"| {i}. {gold} | " + " | ".join(cells) + " |")
    return out


def stages_markdown(stages: Optional[dict]) -> list[str]:
    """Seconds per pipeline stage. Absent for runs made before stage timing existed."""
    if not stages:
        return []
    calls = stages["model_calls_per_ticket"]
    out = ["", "## Where the time goes", "",
           f"Live tickets only (n={stages['n_live_tickets']}); tickets with any call "
           f"replayed from the model cache are excluded. Model calls per ticket: mean "
           f"{calls['mean']}, max {calls['max']}.", "",
           "| Stage | p50 s | p95 s | mean s |", "|---|---|---|---|"]
    out += [f"| {name} | {s['p50']} | {s['p95']} | {s['mean']} |"
            for name, s in stages["stages"].items()]
    return out


def _maybe_pct(x: Optional[float]) -> str:
    return pct(x) if x is not None else "n/a"


def write(output_dir: Path, rows: list[dict], metrics: dict, tickets: dict[str, dict], *,
          hidden_set_runs: int = 0) -> dict:
    table = build(rows, metrics, tickets, hidden_set_runs=hidden_set_runs)
    (output_dir / "results_table.json").write_text(json.dumps(table, indent=2), encoding="utf-8")
    (output_dir / "results_table.md").write_text(to_markdown(table), encoding="utf-8")
    return table


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", required=True, help="harness output directory")
    ap.add_argument("--tickets", default=str(TICKETS_PATH), help="the input the run used")
    ap.add_argument("--hidden-set-runs", type=int, default=0,
                    help="how many times the hidden evaluation set has been run")
    args = ap.parse_args(argv)
    out = Path(args.results)
    rows = [json.loads(line) for line in (out / "results.jsonl").open(encoding="utf-8")]
    metrics: dict[str, Any] = json.loads((out / "metrics_report.json").read_text(encoding="utf-8"))
    tickets = {t["ticket_id"]: t
               for t in json.loads(Path(args.tickets).read_text(encoding="utf-8"))}
    table = write(out, rows, metrics, tickets, hidden_set_runs=args.hidden_set_runs)
    for r in table["rows"]:
        print(f"[results] {r['measure']:26} {r['status']:13} {r['achieved']}")
    print(f"[results] wrote {out / 'results_table.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
