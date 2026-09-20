"""Guardrails in turn vs concurrently (D-12): same drafts, time and verdicts compared.

Satisfies: nothing in production. Evidence for D-12.

Takes the stored drafts of a harness run, rebuilds each ticket's guardrail
context, and runs src.guardrails.run_all on every draft twice: once with one
worker (the guardrails in turn, as before D-12) and once with GUARDRAIL_MAX_WORKERS
(concurrently). The model cache must be off (MODEL_CACHE_DISABLED=1), or the
second pass would replay the first.

The modes run as separate passes over all drafts: in turn, concurrent, in turn
again. Alternating the mode per ticket was tried first and is confounded: Ollama
keeps each slot's last prompt, so whichever mode ran second on a ticket reused
the first mode's work on identical prompts (VAL-0001: 33.9 s in turn, then 4.5 s
concurrent). Between passes every other draft's prompts go through the slots, so
that reuse is gone. The second in-turn pass measures drift in the machine's own
speed across the run.

Reports, per mode, the guardrail-stage seconds (p50, p95, mean) and, per ticket,
whether the two modes reached the same verdict for every guardrail. The drafts
are identical, so a difference is the judge being non-deterministic, not the
concurrency changing a decision; it is reported either way.

Passages are re-retrieved with the body alone, the query the stored runs used
before D-09, so grounding sees what the draft was written from.

Usage:
    MODEL_CACHE_DISABLED=1 GUARDRAIL_BASE_URL=http://localhost:11435/v1 \\
    GUARDRAIL_MODEL=qwen2.5-7b-ctx8k GUARDRAIL_API_KEY=ollama \\
    python -m evaluation.guardrail_parallel_check \\
        --run evaluation/results/b21_local_80_20260919 --limit 20 \\
        --output evaluation/results/guardrail_parallel_check_20260920
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
TICKETS_PATH = _ROOT / "data" / "validation_tickets.json"


def _summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"n": len(ordered), "p50": round(statistics.median(ordered), 2),
            "p95": ordered[min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))],
            "mean": round(statistics.mean(ordered), 2)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="harness output dir with stored drafts")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)

    import src.guardrails as guardrails
    from src.config import GUARDRAIL_MAX_WORKERS, GUARDRAIL_MODEL, MODEL_CACHE_DISABLED
    from src.ingest import normalise_any
    from src.logging_config import configure_logging
    from src.logging_store import new_run_id, set_run_id
    from src.retrieve import retrieve
    from src.schema import ClassificationResult, GeneratedResponse, GuardrailContext

    if not MODEL_CACHE_DISABLED:
        print("set MODEL_CACHE_DISABLED=1: with the cache on the second pass replays the first")
        return 1
    configure_logging()
    run_id = set_run_id(new_run_id("guardrail-parallel-check"))
    tickets = {t["ticket_id"]: t for t in json.loads(TICKETS_PATH.read_text())}
    rows = [json.loads(line) for line in (Path(args.run) / "results.jsonl").open()]
    # Drafts that reach the LLM guardrails; an abstention short-circuits them.
    drafts = [r for r in rows if r.get("answer") and not r.get("unknown")
              and not r.get("degraded")][: args.limit]

    contexts = []
    for r in drafts:
        ticket = normalise_any(tickets[r["ticket_id"]])
        contexts.append((r, GeneratedResponse(
            answer=r["answer"], citations=r["citations"],
            confidence=r["response_pre_guardrail"]["confidence"], unknown=False),
            GuardrailContext(
                ticket=ticket,
                passages=retrieve(ticket.body, ticket_id=ticket.ticket_id),
                classification=ClassificationResult(
                    intent=r["intent"], urgency=r.get("urgency", "medium"),
                    confidence=r["confidence"]))))

    passes = [("in_turn", 1), ("concurrent", GUARDRAIL_MAX_WORKERS), ("in_turn_again", 1)]
    seconds: dict[str, list[float]] = {name: [] for name, _ in passes}
    verdicts: dict[str, list] = {name: [] for name, _ in passes}
    for name, workers in passes:
        guardrails.GUARDRAIL_MAX_WORKERS = workers
        for i, (r, response, ctx) in enumerate(contexts):
            t0 = time.perf_counter()
            results = guardrails.run_all(response, ctx)
            seconds[name].append(round(time.perf_counter() - t0, 2))
            verdicts[name].append([(g.name, g.passed, g.fail_safe) for g in results])
            print(f"[check] {name} {i + 1}/{len(contexts)} {r['ticket_id']} "
                  f"{seconds[name][-1]}s", flush=True)
    guardrails.GUARDRAIL_MAX_WORKERS = GUARDRAIL_MAX_WORKERS

    per_ticket = [
        {"ticket_id": r["ticket_id"],
         **{f"{name}_s": seconds[name][i] for name, _ in passes},
         "same_verdicts_in_turn_vs_concurrent": verdicts["in_turn"][i] == verdicts["concurrent"][i],
         "same_verdicts_in_turn_twice": verdicts["in_turn"][i] == verdicts["in_turn_again"][i],
         "verdicts": {name: verdicts[name][i] for name, _ in passes}}
        for i, (r, _, _) in enumerate(contexts)]
    in_turn_mean = statistics.mean(seconds["in_turn"] + seconds["in_turn_again"])
    report = {
        "run_id": run_id, "source_run": args.run, "guardrail_model": GUARDRAIL_MODEL,
        "workers": dict(passes), "tickets": len(drafts),
        "guardrail_seconds": {m: _summary(v) for m, v in seconds.items()},
        # Both in-turn passes against the concurrent one, so drift is shared out.
        "speed_up_mean": round(in_turn_mean / statistics.mean(seconds["concurrent"]), 2),
        "identical_verdicts_in_turn_vs_concurrent": sum(
            t["same_verdicts_in_turn_vs_concurrent"] for t in per_ticket),
        "identical_verdicts_in_turn_twice": sum(
            t["same_verdicts_in_turn_twice"] for t in per_ticket),
        "per_ticket": per_ticket,
    }
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "per_ticket"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
