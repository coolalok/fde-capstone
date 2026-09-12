"""End-to-end evaluation harness. Backlog item B-19.

Satisfies: FR-21 (single documented command, --input / --output, unattended),
           FR-22 (metrics_report.json with business, technical and governance
                  metrics, all computed by code),
           FR-23 (degrade rather than crash; every degraded ticket escalates).
Cites:     A9 (unattended run), A10 (report auto-generated), A8 (reconciliation),
           A11 (graceful degradation).

Usage:
    python -m evaluation.harness --input data/validation_tickets.json \\
                                 --output evaluation/results/run1

Design decisions worth reading:

- **One run_id per invocation.** Stamped via set_run_id() before the first
  ticket, so reconciliation counts this run's rows and not the dev and
  validation rows already sitting in decisions.db. That was Bug 2; without it
  A8 fails on arrival on any machine that has run the harness before.

- **Ground truth is read from the RAW record, never from the Ticket.** FR-01 v2
  keeps labels.* off the Ticket so production code cannot see answers it will
  not have at inference. The harness is evaluation, so it may read them — from
  the input file directly, alongside the pipeline rather than through it.

- **Label-dependent metrics are optional.** The hidden evaluation set is a file
  we have never seen and may carry no labels at all. Intent precision/recall and
  retrieval hit rate are computed only when labels are present; their absence
  degrades the report, not the run.

- **Every ticket is wrapped.** A single ticket that raises anywhere must not end
  the run (FR-23). The failure is recorded, the ticket is force-escalated, and
  processing continues. Exit code stays 0 — a degraded run is a completed run.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from src.classify import classify
from src.config import CONFIDENCE_THRESHOLD, GUARDRAIL_MODEL, MODEL_NAME
from src.generate import generate
from src.guardrails import run_all
from src.ingest import normalise_any
from src.logging_config import configure_logging
from src.logging_store import new_run_id, reconcile, set_run_id
from src.retrieve import retrieve
from src.route import AUTO_RESPOND, BLOCK, ESCALATE, route
from src.schema import GuardrailContext, Route

import logging

logger = logging.getLogger(__name__)


def process_ticket(raw: dict, *, skip_guardrails: bool = False,
                   call_model: Optional[Any] = None) -> dict:
    """Run one ticket through the whole pipeline. Never raises.

    Returns the per-ticket result row (FR-21: one output row per ticket).

    ``call_model`` is threaded to every stage that talks to the provider, so
    tests/test_harness_smoke.py can exercise the real pipeline with a fake
    client (capstone-test-writer §harness smoke test). Without this seam a
    smoke test would have to monkeypatch three modules' private
    ``_openrouter_call``, which couples the test to internals it should not
    know about. Production leaves it None.
    """
    started = time.perf_counter()
    ticket_id = str(raw.get("ticket_id", ""))
    row: dict[str, Any] = {"ticket_id": ticket_id, "degraded": False, "error": None}

    try:
        ticket = normalise_any(raw)
        row["channel"] = ticket.channel
        row["warnings"] = ticket.warnings

        classification = classify(ticket, call_model=call_model)
        row["intent"] = classification.intent
        row["urgency"] = classification.urgency
        row["confidence"] = classification.confidence
        row["classifier_error"] = classification.error

        passages = retrieve(ticket.body, ticket_id=ticket_id)
        row["retrieved_doc_ids"] = [p.doc_id for p in passages]
        row["top_score"] = passages[0].score if passages else 0.0

        response = generate(ticket, passages, ticket_id=ticket_id,
                            call_model=call_model)
        row["unknown"] = response.unknown
        row["citations"] = response.citations
        row["answer_len"] = len(response.answer)
        row["generator_error"] = response.error
        row["retries"] = response.retries

        guardrail_results = []
        if not skip_guardrails:
            ctx = GuardrailContext(
                ticket=ticket, passages=passages, classification=classification
            )
            guardrail_results = run_all(response, ctx, call_model=call_model)
        row["guardrails"] = [
            {"name": g.name, "passed": g.passed, "blocking": g.blocking,
             "reason": g.reason[:200]}
            for g in guardrail_results
        ]

        decision: Route = route(
            ticket, classification, passages, response, guardrail_results
        )
        row["decision"] = decision.decision
        row["trigger"] = decision.trigger
        row["reason"] = decision.reason
        row["bundle_present"] = decision.bundle is not None

    except Exception as exc:  # FR-23 — one bad ticket must not end the run
        logger.error(
            "harness.ticket_degraded",
            extra={"ticket_id": ticket_id, "error": str(exc),
                   "error_type": type(exc).__name__,
                   "traceback": traceback.format_exc()[-800:]},
        )
        row.update(
            degraded=True,
            error=f"{type(exc).__name__}: {exc}",
            decision=ESCALATE,
            trigger="degraded",
            reason=f"degraded: {type(exc).__name__}: {exc}",
        )

    row["latency_seconds"] = round(time.perf_counter() - started, 3)
    return row


# ─── metrics (FR-22) ─────────────────────────────────────────────────


# A calibration bucket below this many tickets is noise, not evidence: on 80
# tickets one ticket can move a bucket's observed accuracy by 100 points. Such
# buckets are still REPORTED (with their n) but excluded from the headline
# max-gap figure, which would otherwise be driven by a single ticket.
MIN_CALIBRATION_BUCKET_N = 5


def _pct(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def _intent_precision_recall(rows: list[dict], truth: dict[str, dict]) -> dict:
    """Per-class precision and recall for the classifier. Labels required."""
    per: dict[str, dict[str, int]] = {}
    for r in rows:
        gold = truth.get(r["ticket_id"], {}).get("intent")
        pred = r.get("intent")
        if gold is None or pred is None:
            continue
        per.setdefault(gold, {"tp": 0, "fn": 0, "fp": 0})
        per.setdefault(pred, {"tp": 0, "fn": 0, "fp": 0})
        if pred == gold:
            per[gold]["tp"] += 1
        else:
            per[gold]["fn"] += 1
            per[pred]["fp"] += 1
    return {
        cls: {
            "support": c["tp"] + c["fn"],
            "precision": _pct(c["tp"], c["tp"] + c["fp"]),
            "recall": _pct(c["tp"], c["tp"] + c["fn"]),
        }
        for cls, c in sorted(per.items())
    }


def build_metrics(rows: list[dict], truth: dict[str, dict], *,
                  run_id: str, skip_guardrails: bool) -> dict:
    """Every number here is computed, never hand-entered (FR-22 acceptance)."""
    n = len(rows)
    decisions = Counter(r.get("decision") for r in rows)
    latencies = sorted(r["latency_seconds"] for r in rows)

    # ── governance ────────────────────────────────────────────────────
    recon = reconcile([r["ticket_id"] for r in rows], run_id=run_id)
    guardrail_activations: Counter = Counter()
    pii_detections = 0
    for r in rows:
        for g in r.get("guardrails", []):
            if not g["passed"]:
                guardrail_activations[g["name"]] += 1
                if g["name"] == "pii":
                    pii_detections += 1

    # ── business ──────────────────────────────────────────────────────
    auto = decisions.get(AUTO_RESPOND, 0)
    escalated = decisions.get(ESCALATE, 0) + decisions.get(BLOCK, 0)
    # FCR proxy: a ticket answered at first contact with no human. When labels
    # exist we can say whether that answer was the RIGHT call; without them the
    # proxy is the auto-respond rate alone.
    correct_auto = sum(
        1 for r in rows
        if r.get("decision") == AUTO_RESPOND
        and truth.get(r["ticket_id"], {}).get("expected_route") == "auto_respond"
    ) if truth else None

    metrics: dict[str, Any] = {
        "run_id": run_id,
        "model_name": MODEL_NAME,
        # Recorded separately: the guardrails judge with a different model on
        # purpose (D-07/Bug 5), so a reader cannot tell which model produced a
        # verdict from model_name alone.
        "guardrail_model": GUARDRAIL_MODEL if not skip_guardrails else None,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "guardrails_enabled": not skip_guardrails,
        "labels_available": bool(truth),
        "counts": {
            "tickets_processed": n,
            "auto_respond": auto,
            "escalate": decisions.get(ESCALATE, 0),
            "block": decisions.get(BLOCK, 0),
            "degraded": sum(1 for r in rows if r.get("degraded")),
            "generator_unknown": sum(1 for r in rows if r.get("unknown")),
            "empty_retrieval": sum(1 for r in rows if not r.get("retrieved_doc_ids")),
        },
        "business_metrics": {
            # Named "proxy" deliberately: a single offline run cannot observe
            # whether a customer came back, so these are leading indicators,
            # not the outcome measures Marcus tracks (EV-M2).
            "fcr_proxy": _pct(auto, n),
            "fcr_correct_proxy": _pct(correct_auto, n) if correct_auto is not None else None,
            "escalation_rate": _pct(escalated, n),
            "repeat_contact_proxy": _pct(
                sum(1 for r in rows if r.get("unknown") or r.get("degraded")), n
            ),
            "ttr_seconds_median": round(statistics.median(latencies), 3) if latencies else 0.0,
        },
        "technical_metrics": {
            "latency_p50_seconds": round(statistics.median(latencies), 3) if latencies else 0.0,
            # ceil, not int: with n=2, int(2*0.95)-1 == 0 picked the FASTEST
            # ticket and reported a p95 BELOW the p50. Caught on the first run.
            "latency_p95_seconds": round(
                latencies[min(len(latencies) - 1,
                              max(0, math.ceil(0.95 * len(latencies)) - 1))], 3
            ) if latencies else 0.0,
            "latency_max_seconds": latencies[-1] if latencies else 0.0,
            "classifier_failures": sum(1 for r in rows if r.get("classifier_error")),
            "generator_failures": sum(1 for r in rows if r.get("generator_error")),
        },
        "governance_metrics": {
            "decisions_logged": recon["tickets_with_log"],
            "reconciles": recon["reconciles"],
            "missing_from_log": recon["missing_from_log"],
            "extra_in_log": recon["extra_in_log"],
            "guardrail_activations": dict(guardrail_activations),
            "pii_detections": pii_detections,
        },
    }

    # ── confidence calibration (governance) ───────────────────────────
    # Project Brief §07: stated confidence should sit within five points of
    # observed accuracy. PR-CLASSIFY-01 states the same contract to the model
    # ("when you return 0.9, you should be right 90% of the time").
    if truth:
        buckets: list[list[float]] = [[] for _ in range(10)]
        correct = [0] * 10
        skipped_fallbacks = 0
        for r in rows:
            gold = truth.get(r["ticket_id"], {}).get("intent")
            pred, conf = r.get("intent"), r.get("confidence")
            if gold is None or pred is None or conf is None:
                continue
            # A classifier FAILURE is not a calibration data point — the model
            # never stated a confidence, the fallback did (0.0). Including them
            # packs bucket 0 with non-observations and flatters the result.
            if r.get("classifier_error"):
                skipped_fallbacks += 1
                continue
            b = min(9, int(conf * 10))
            buckets[b].append(conf)
            if pred == gold:
                correct[b] += 1
        calibration = []
        for i, confs in enumerate(buckets):
            if not confs:
                continue
            n_b = len(confs)
            # Average the ACTUAL stated confidences, not the bucket midpoint.
            # The midpoint carries up to 5 points of quantisation error, which
            # is the entire tolerance the Brief asks us to measure.
            stated = sum(confs) / n_b
            observed = correct[i] / n_b
            calibration.append({
                "bucket": f"{i / 10:.1f}-{(i + 1) / 10:.1f}",
                "n": n_b,
                "stated_avg": round(stated, 3),
                "observed": round(observed, 3),
                # Negative = overconfident (stated above observed).
                "gap_pp": round((observed - stated) * 100, 1),
                "sufficient_n": n_b >= MIN_CALIBRATION_BUCKET_N,
            })
        metrics["governance_metrics"]["confidence_calibration"] = calibration
        metrics["governance_metrics"]["calibration_fallbacks_excluded"] = skipped_fallbacks
        metrics["governance_metrics"]["max_calibration_gap_pp"] = max(
            (abs(c["gap_pp"]) for c in calibration if c["sufficient_n"]), default=None)
        metrics["governance_metrics"]["calibration_min_bucket_n"] = MIN_CALIBRATION_BUCKET_N

    # ── label-dependent technical metrics ─────────────────────────────
    if truth:
        answerable = [r for r in rows
                      if truth.get(r["ticket_id"], {}).get("answerable_from_docs")]
        hits = sum(
            1 for r in answerable
            if set(r.get("retrieved_doc_ids", [])[:3])
            & set(truth[r["ticket_id"]].get("expected_doc_ids", []))
        )
        metrics["technical_metrics"]["retrieval_hit_at_3"] = _pct(hits, len(answerable))
        metrics["technical_metrics"]["retrieval_answerable_n"] = len(answerable)
        metrics["technical_metrics"]["intent_per_class"] = _intent_precision_recall(rows, truth)
        metrics["technical_metrics"]["intent_accuracy"] = _pct(
            sum(1 for r in rows
                if r.get("intent") == truth.get(r["ticket_id"], {}).get("intent")), n)
    return metrics


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full pipeline over a ticket file and write a metrics report.")
    parser.add_argument("--input", required=True, help="Path to input tickets JSON")
    parser.add_argument("--output", required=True, help="Directory for results")
    parser.add_argument("--limit", type=int, default=0, help="process only the first N tickets")
    parser.add_argument("--skip-guardrails", action="store_true",
                        help="run without the guardrail layer (diagnostic only)")
    args = parser.parse_args(argv)

    configure_logging()
    input_path, output_dir = Path(args.input), Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    tickets = json.loads(input_path.read_text())
    if args.limit:
        tickets = tickets[: args.limit]
    # Ground truth is read here, from the raw file — never through the Ticket.
    truth = {t["ticket_id"]: t["labels"] for t in tickets if "labels" in t}

    run_id = set_run_id(new_run_id("harness"))
    print(f"[harness] run_id={run_id}")
    print(f"[harness] input={input_path} tickets={len(tickets)} "
          f"labels={'yes' if truth else 'no'} guardrails={not args.skip_guardrails}")

    started = time.perf_counter()
    rows = []
    for i, raw in enumerate(tickets, 1):
        rows.append(process_ticket(raw, skip_guardrails=args.skip_guardrails))
        if i % 10 == 0 or i == len(tickets):
            print(f"[harness]   {i}/{len(tickets)} ({time.perf_counter() - started:.0f}s)")

    results_path = output_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    metrics = build_metrics(rows, truth, run_id=run_id,
                            skip_guardrails=args.skip_guardrails)
    metrics["wall_clock_seconds"] = round(time.perf_counter() - started, 1)
    report_path = output_dir / "metrics_report.json"
    report_path.write_text(json.dumps(metrics, indent=2))

    c = metrics["counts"]
    print(f"[harness] auto_respond={c['auto_respond']} escalate={c['escalate']} "
          f"block={c['block']} degraded={c['degraded']}")
    print(f"[harness] A8 reconciles={metrics['governance_metrics']['reconciles']}")
    print(f"[harness] wrote {results_path}")
    print(f"[harness] wrote {report_path}")
    # A9/FR-23: a degraded run is still a completed run.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
