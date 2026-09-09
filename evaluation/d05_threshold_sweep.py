"""D-05 confidence-threshold sweep on the validation set. Backlog item B-16.

Sweeps CONFIDENCE_THRESHOLD from 0.50 to 0.95 in 0.05 steps and reports, per
threshold, the auto-respond precision and recall against each ticket's
`labels.expected_route`. Selects the value that maximises the first-contact-
resolution proxy subject to precision >= 0.95.

Why precision >= 0.95: EV-M3 (Marcus) — "I would rather it said nothing than
said something wrong". A wrong auto-reply is the failure mode this project
exists to avoid, so precision is the binding constraint and recall is what we
maximise underneath it.

SCOPE. Classify, retrieve AND generate run for real; guardrails do not.
Generation is included because FR-14's unknown branch is the control that
decides answerability, and answerability — not confidence — turns out to be
what bounds auto-respond precision on this corpus (see --no-generation below
for the contrast). Guardrails are excluded: they block on PII, tone and
grounding, which are safety properties orthogonal to the threshold, and they
cost ~3 extra model calls per ticket. Full-pipeline figures are B-21's job.

Pass --no-generation to reproduce the generation-free baseline, which is what
the first B-16 run measured before generation was added.

Usage:
    python -m evaluation.d05_threshold_sweep [--limit N]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src.classify import classify
from src.generate import generate
from src.guardrails import GroundingGuardrail
from src.logging_config import configure_logging
from src.schema import GuardrailContext
from src.retrieve import retrieve
from src.route import AUTO_RESPOND, route
from src.schema import Ticket

_ROOT = Path(__file__).parent.parent
DATA = _ROOT / "data" / "validation_tickets.json"
RESULTS = _ROOT / "evaluation" / "results"


def _out_path(args) -> Path:
    """Config-specific filename.

    Runs with different pipeline stages enabled are different experiments and
    must not share a file — a --limit smoke test once overwrote an 80-ticket
    run that an ADR cited as its evidence.
    """
    parts = ["d05_threshold_sweep"]
    parts.append("nogen" if args.no_generation else "gen")
    if args.with_grounding:
        parts.append("grounding")
    if args.limit:
        parts.append(f"limit{args.limit}")
    return RESULTS / ("_".join(parts) + ".json")


PRECISION_FLOOR = 0.95
THRESHOLDS = [round(0.50 + 0.05 * i, 2) for i in range(10)]  # 0.50 .. 0.95


def _score(routes: list[str], expected: list[str]) -> dict:
    """Auto-respond precision/recall against expected_route, plus the FCR proxy."""
    tp = sum(1 for r, e in zip(routes, expected) if r == AUTO_RESPOND and e == "auto_respond")
    fp = sum(1 for r, e in zip(routes, expected) if r == AUTO_RESPOND and e != "auto_respond")
    want = sum(1 for e in expected if e == "auto_respond")
    n = len(expected)
    return {
        "auto_responded": tp + fp,
        "true_positives": tp,
        "false_positives": fp,
        # Precision is undefined when we auto-respond to nothing. Report None
        # rather than 1.0 — a threshold that answers zero tickets has not
        # achieved perfect precision, it has abstained.
        "precision": (tp / (tp + fp)) if (tp + fp) else None,
        "recall": tp / want if want else 0.0,
        "escalation_rate": sum(1 for r in routes if r != AUTO_RESPOND) / n,
        # FCR proxy: share of ALL tickets resolved correctly without a human.
        "fcr_proxy": tp / n,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="D-05 confidence threshold sweep.")
    ap.add_argument("--limit", type=int, default=0, help="classify only the first N tickets")
    ap.add_argument("--no-generation", action="store_true",
                    help="skip generation (threshold-only baseline)")
    ap.add_argument("--with-grounding", action="store_true",
                    help="also run the FR-17 grounding guardrail (D-05b revisit trigger)")
    args = ap.parse_args()
    configure_logging()

    tickets = json.loads(DATA.read_text())
    if args.limit:
        tickets = tickets[: args.limit]
    print(f"[d05] validation tickets: {len(tickets)}")

    # ── Classify + retrieve once; the sweep then re-routes the cached results.
    cached = []
    t0 = time.time()
    for i, raw in enumerate(tickets, 1):
        ticket = Ticket(
            ticket_id=raw["ticket_id"],
            channel=raw["channel"],
            subject=raw.get("subject", ""),
            body=raw["body"],
            customer_tier=raw.get("customer_tier", ""),
        )
        classification = classify(ticket)
        passages = retrieve(ticket.body, ticket_id=ticket.ticket_id)
        response = (None if args.no_generation
                    else generate(ticket, passages, ticket_id=ticket.ticket_id))
        grails = []
        if args.with_grounding and response is not None:
            ctx = GuardrailContext(ticket=ticket, passages=passages,
                                   classification=classification)
            grails = [GroundingGuardrail().check(response, ctx)]
        cached.append((ticket, classification, passages, raw["labels"], response, grails))
        if i % 20 == 0:
            print(f"[d05]   {i}/{len(tickets)} classified ({time.time() - t0:.0f}s)")
    print(f"[d05] classification+retrieval done in {time.time() - t0:.0f}s")

    classifier_errors = sum(1 for _, c, _, _, _, _ in cached if c.error is not None)
    unknown_generations = sum(1 for _, _, _, _, r, _ in cached if r is not None and r.unknown)
    if not args.no_generation:
        print(f"[d05] generator returned unknown on {unknown_generations}/{len(cached)} tickets")
    if classifier_errors:
        print(f"[d05] WARNING: {classifier_errors} classifier failures — treated as unknown")

    if args.with_grounding:
        blocked = sum(1 for _, _, _, _, _, g in cached if g and not g[0].passed)
        errs = sum(1 for _, _, _, _, _, g in cached
                   if g and "guardrail_error" in g[0].reason)
        print(f"[d05] grounding guardrail blocked {blocked}/{len(cached)} "
              f"({errs} of those were guardrail errors, which fail SAFE)")

    expected = [lbl["expected_route"] for _, _, _, lbl, _, _ in cached]

    rows = []
    for th in THRESHOLDS:
        routes = [
            route(t, c, p, resp, g, threshold=th).decision
            for t, c, p, _, resp, g in cached
        ]
        row = {"threshold": th, **_score(routes, expected)}
        rows.append(row)

    # ── Selection rule: max FCR subject to precision >= floor.
    eligible = [r for r in rows if r["precision"] is not None and r["precision"] >= PRECISION_FLOOR]
    chosen = max(eligible, key=lambda r: r["fcr_proxy"]) if eligible else None

    print(f"\n{'thresh':>7} {'auto':>5} {'TP':>4} {'FP':>4} {'precision':>10} "
          f"{'recall':>8} {'FCR':>7} {'esc rate':>9}")
    for r in rows:
        p = "n/a" if r["precision"] is None else f"{r['precision']:.3f}"
        mark = "  <- selected" if chosen and r["threshold"] == chosen["threshold"] else ""
        print(f"{r['threshold']:>7.2f} {r['auto_responded']:>5} {r['true_positives']:>4} "
              f"{r['false_positives']:>4} {p:>10} {r['recall']:>8.3f} "
              f"{r['fcr_proxy']:>7.3f} {r['escalation_rate']:>9.3f}{mark}")

    if chosen:
        print(f"\n[d05] SELECTED threshold {chosen['threshold']:.2f} — "
              f"precision {chosen['precision']:.3f} (floor {PRECISION_FLOOR}), "
              f"FCR proxy {chosen['fcr_proxy']:.3f}")
    else:
        print(f"\n[d05] NO threshold reaches precision >= {PRECISION_FLOOR} on this set.")

    # ── PRD Table 9 Q6: is a tier-differentiated threshold warranted?
    by_tier: dict = {}
    if chosen:
        th = chosen["threshold"]
        for tier in sorted({t.customer_tier or "unknown" for t, _, _, _, _, _ in cached}):
            idx = [i for i, (t, _, _, _, _, _) in enumerate(cached)
                   if (t.customer_tier or "unknown") == tier]
            if not idx:
                continue
            routes = [route(cached[i][0], cached[i][1], cached[i][2], cached[i][4], cached[i][5],
                            threshold=th).decision for i in idx]
            by_tier[tier] = {"n": len(idx), **_score(routes, [expected[i] for i in idx])}
        print(f"\n[d05] Q6 — per-tier at the selected threshold {th:.2f}:")
        print(f"{'tier':>12} {'n':>4} {'precision':>10} {'recall':>8} {'FCR':>7}")
        for tier, m in by_tier.items():
            p_ = "n/a" if m["precision"] is None else f"{m['precision']:.3f}"
            print(f"{tier:>12} {m['n']:>4} {p_:>10} {m['recall']:>8.3f} {m['fcr_proxy']:>7.3f}")

    per_ticket = [
        {"ticket_id": t.ticket_id, "tier": t.customer_tier or "unknown",
         "predicted_intent": c.intent, "confidence": c.confidence,
         "classifier_error": c.error, "n_passages": len(p),
         "expected_route": lbl["expected_route"],
         "true_intent": lbl["intent"],
         "answerable_from_docs": lbl["answerable_from_docs"],
         "generator_unknown": (None if r is None else r.unknown),
         "grounding_passed": (g[0].passed if g else None),
         "grounding_reason": (g[0].reason[:120] if g else None)}
        for t, c, p, lbl, r, g in cached
    ]

    OUT = _out_path(args)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "n_tickets": len(cached),
        "classifier_errors": classifier_errors,
        "generation_included": not args.no_generation,
        "grounding_included": args.with_grounding,
        "unknown_generations": unknown_generations,
        "precision_floor": PRECISION_FLOOR,
        "scope": "confidence threshold only; no generator output, no guardrail results",
        "rows": rows,
        "selected": chosen,
        "by_tier_at_selected": by_tier,
        "per_ticket": per_ticket,
    }, indent=2))
    print(f"[d05] wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
