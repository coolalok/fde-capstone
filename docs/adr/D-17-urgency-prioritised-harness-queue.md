# D-17 — The harness works high-urgency tickets first, on its own classifier's rating

**Status:** Accepted
**Date:** 2026-09-23
**Decider:** Alok Kulkarni
**Constrains:** FR-21, FR-22, FR-23
**Affects:** `evaluation/harness.py` (`classify_all`, `prioritise`, `process_ticket`, `_urgency_accuracy`, `main`), `tests/test_harness_prioritise.py`, `README.md`

## Context

The harness processed tickets in file order: a plain loop over the input list, with `--limit N` taking the first N as they happen to appear in the file. Urgency was predicted on every ticket (`PR-CLASSIFY-01`, recorded on each row) and used by nothing — not the router, not the guardrails, not the report.

Order is irrelevant to a run that finishes. Tickets are processed independently, so an 80-ticket run produces an identical metrics report whatever sequence it ran in. Order decides what a run that does *not* finish has spent its quota on, and this project has lost runs: `evaluation/harness.py` carries the note that a 40-minute B-21 run was killed with an empty results file, which is why rows stream to disk per ticket. Free-tier rate limits and provider outages make a partial run a normal outcome here, not an edge case. When 30 of 120 tickets complete, which 30 is the only question that matters, and file order answers it arbitrarily.

## Options considered

**A. Sort on `labels.urgency` from the raw record.** Roughly five lines. Two objections, and the second is fatal. It uses evaluation ground truth to shape the run, which is the line this project holds everywhere else — FR-01 v2 keeps `labels.*` off the `Ticket` precisely so no production path can read them, and the harness reads them only for scoring, alongside the pipeline rather than through it. And the hidden 120-ticket evaluation set may carry no labels at all; the harness already prints `labels=yes|no` and degrades its label-dependent metrics accordingly. Sorting on labels would silently become a no-op on the one run that is graded.

**B. A keyword heuristic over the raw subject and body before any model call.** No ground truth, no model calls, streaming behaviour untouched. But it prioritises on a proxy the system does not otherwise use, which would then need its own justification, its own tests and its own accuracy measurement — a second, weaker urgency signal sitting beside the real one.

**C. Two phases: classify everything, order by the predicted urgency, then run the rest of the pipeline in that order, reusing phase 1's result.** Uses the rating the system already produces and already stands behind. Costs no extra model calls, because phase 2 is handed the classification rather than recomputing it.

**D. Leave it in file order and document that order is arbitrary.** Honest, and free. It leaves the partial-run question unanswered.

## Chosen

**Option C**, on by default, with `--no-prioritize` to restore file order.

Default on because the failure it prevents — a quota exhausted on low-urgency tickets while high-urgency ones went unprocessed — happens silently on exactly the runs nobody is watching. An opt-in flag would be remembered on the runs that do not need it and forgotten on the ones that do.

`--no-prioritize` exists because every run committed under `evaluation/results/` was produced in file order. Reproducing one now requires the flag, and that is stated in the README next to the command.

## Consequences

- **Cost is unchanged.** Phase 2 receives a `PriorClassification` and skips the classifier. A prioritised 80-ticket run makes the same number of model calls as an unprioritised one.
- **The reported figures are unchanged, and that took work to keep true.** `process_ticket` drains `usage` on entry and measures latency from entry, so the pre-pass call would have been dropped from the run's token totals and from the ticket's end-to-end latency. `PriorClassification` carries `seconds` and `calls` back onto the row. Without that, prioritising a run would have made the pipeline look cheaper and faster than the same work unprioritised — a reporting fault, not a scheduling one.
- **`--limit N` still slices before phase 1**, so it takes the first N in file order and prioritises within them. Limiting *after* the pre-pass would mean classifying all 500 dev tickets to run 10, which the cost-nothing rule rules out. A `--limit` run is therefore a prioritised sample of the head of the file, not the N most urgent tickets in it.
- **A pre-pass failure cannot move a ticket.** A ticket that fails in phase 1 is absent from the map, ranks `medium` — the same rank the unknown-fallback carries — and is classified again in phase 2, which is the behaviour it would have had without prioritisation. FR-23 holds in both phases.
- **The crash window moves.** A run killed during phase 1 writes no rows at all, where the same wall-clock interruption would previously have produced some. Phase 1 is one model call per ticket against roughly four for the full pipeline, so this trades a small early window for correct ordering across the whole remainder.
- **Determinism (A5) is preserved.** The sort is stable, so tickets of equal urgency keep file order and two runs over the same file agree on where a killed run got to.
- **Urgency is now scored.** `technical_metrics.urgency_accuracy` compares predicted urgency against `labels.urgency` when labels are present, with a gold-to-predicted confusion table and `high_called_low` broken out — a high ticket rated low is worked late, which is the failure this ADR exists to prevent, while a low ticket rated high only loses a place in the queue. A queue sorted on an unmeasured rating is sorted on nothing in particular, so the metric is part of the decision rather than an addition to it.

## Revisit trigger

- `urgency_accuracy` comes back poor on a labelled run, particularly `high_recall`. Ordering on a rating that cannot find urgent tickets is worse than file order, because it looks deliberate. `--no-prioritize` is the immediate answer; a better urgency signal is the real one.
- The harness ever processes tickets concurrently. Ordering a queue that several workers draw from is a different problem, and the two-phase structure is not obviously the right shape for it.
- `PR-CLASSIFY-01`'s deferred question about `received_at` as an urgency input (prompt line 135) is reopened. It was left until "B-21 surfaces urgency calibration as the weak point", which B-21 could not do while urgency went unscored. `urgency_accuracy` is the instrument that deferral was waiting on.

## Supersedes / superseded by
- Nothing. First decision on processing order.
