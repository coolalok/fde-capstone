# D-15 — A dedicated kill switch, read on every routing call

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-09, FR-10, FR-12
**Affects:** `src/config.py` (`kill_switch_active`), `src/route.py` (`_decide` rule 0), `src/metrics.py`, `src/api.py` (`/healthz`), `evaluation/harness.py`, `evaluation/results_table.py`, `docs/Governance_Framework.docx` §5 and §7

## Context

The Governance Framework asks for "a way to stop it answering automatically, immediately, without a deployment", and says that a project without one has found its first governance finding.

What was documented as the kill switch was `CONFIDENCE_THRESHOLD=1.01`: no confidence can exceed 1.0, so rule 6 fires for every ticket and everything escalates. It works, and it was never built for the purpose. Four problems:

1. **It needs a restart.** `CONFIDENCE_THRESHOLD` is a module-level constant read once at import (`src/config.py`), so a running process keeps the old value. The framework's own answer to "how long until it takes effect" read "seconds — the next process start", which is not "without a deployment".
2. **It overloads a tuning knob.** The same constant is the threshold D-05b measured and the floor the FR-19 guardrail enforces. Someone tuning it and someone halting the system are editing the same value.
3. **It is invisible.** The decision log would read "confidence 0.92 is below the 1.01 threshold". Nothing distinguishes a deliberate halt from a misconfigured threshold, and an auditor reading a run made during an incident cannot tell which they are looking at.
4. **It was untested.** §7 said so: "NOT TESTED: no test asserts that a threshold above 1.0 escalates every ticket, and no drill has been run."

## Options considered

**A. Keep the threshold trick and add a test.** Cheapest, and it would close the "untested" finding. It leaves the restart requirement, the overloaded knob and the indistinguishable log entry.

**B. A dedicated environment flag, read at call time, as rule 0 of the router.** `KILL_SWITCH=1` in the environment of a running process; `route()` reads it on every call and escalates with `trigger="kill_switch_active"`, ahead of every other rule.

**C. A sentinel file (e.g. `storage/HALT`) checked per ticket.** Same immediacy as B without touching the process environment, and it survives a restart, which is either a feature or a trap depending on who removes the file.

## Chosen

**Option B.**

C was rejected for this project rather than on principle: a file that halts the system and survives restarts needs an owner and a removal procedure, and there is no operations team here to hold them. The environment flag is visible in the process, disappears with it, and needs no filesystem state. If this were deployed behind a supervisor that restarts processes, C would be the better answer and D-15 should be revisited.

Read at call time is the whole point. Every other setting in `src/config.py` is a module-level constant, deliberately: a run must not change configuration underneath itself. The kill switch is the exception, because a control that needs a restart is not a kill switch.

Rule 0, ahead of the governance rule, because the precedence order encodes what outranks what. A human saying stop outranks every automatic judgement, including a guardrail block: under the halt the block queue must not fill with tickets that were stopped deliberately.

## Consequences

- **The pipeline still runs.** Classification, retrieval, generation and the guardrails all execute under the halt, so the escalation bundle (FR-11) a reviewer receives is as complete as on any other day. The halt removes automatic sending, not the work that makes the human's job faster. It also costs model calls, which is the deliberate trade: a cheaper halt that skipped generation would hand the queue bare tickets.
- **A halted run is labelled everywhere it could mislead**: `governance_metrics.kill_switch_active` in the metrics report, a warning line in the run summary, the `kill_switch_active` gauge on `/metrics`, `kill_switch_active` in `/healthz` (status stays `ok` — halted is not unhealthy), and a header line plus a limitations entry in the results table.
- **Determinism (A5) is unchanged in substance**: `route()` remains a pure function of its inputs plus one environment read, and the same input under the same environment gives the same decision. The reason string names the switch, so the decision log records why.
- **Tested, and the test is the drill**: `tests/test_route.py` asserts that a ticket at 0.99 confidence clearing every rule still escalates, that the halt outranks a PII block, that the bundle survives, that the flag is read per call for each accepted spelling, and that clearing it resumes service with no restart. `tests/test_api_smoke.py`, `tests/test_harness_smoke.py` and `tests/test_results_table.py` cover the reporting.
- **The old mechanism still works**, because a threshold above 1.0 still escalates at rule 6. It is no longer the documented switch.

## Revisit trigger

- The system is deployed behind a process supervisor or on more than one host: an environment flag then has to be set on every instance, and option C or a control-plane flag becomes the right answer.
- A halt is ever needed for a subset of traffic (one intent, one tier) rather than all of it: rule 0 is all-or-nothing by design.

## Supersedes / superseded by
- Supersedes the `CONFIDENCE_THRESHOLD=1.01` mechanism described in Governance Framework §7 before 2026-09-20.
