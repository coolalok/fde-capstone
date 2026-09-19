# D-12 — Guardrails run concurrently

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-16, FR-17, FR-18, FR-19, NFR-02 (latency)
**Affects:** `src/guardrails.py` (`run_all`), `src/rate_limit.py` (lock), `src/config.py` (`GUARDRAIL_MAX_WORKERS`), `.env.example`

## Context

The first run with per-stage timing (b21_openai_gemini_80_20260920, gpt-4o-mini drafting, gemini-3.8-flash judging) put the guardrail stage at a mean of 10.5 s (p95 20.4 s) of a 14 s ticket: six checks, four of them a model call each, run one after another. The checks are independent: each reads the same draft and context and none reads another's verdict. The router needs all six before it decides, so nothing is gained by ordering them.

## Options considered

**A. In turn (as before).** Simplest; stage time is the sum of the calls.

**B. Concurrently in a thread pool, results returned in guardrail order.** Stage time approaches the slowest call. The provider client is synchronous, so threads need no rewrite of the call sites.

**C. Only call an LLM guardrail when a cheap check is inconclusive** (the external review's "regex first" proposal). Fewer calls, but it removes checks from the path of every draft: a safety change, not a latency change, and out of scope here.

## Chosen

**Option B**, at most `GUARDRAIL_MAX_WORKERS` (default 4) at once. `GUARDRAIL_MAX_WORKERS=1` reproduces Option A exactly.

## Rationale

Measured with `evaluation/guardrail_parallel_check.py` on 20 stored drafts from b21_local_80_20260919, local judge `qwen2.5-7b-ctx8k`, model cache off, three separate passes (`evaluation/results/guardrail_parallel_check_20260920/report.json`):

| Pass | p50 | p95 | Mean |
|---|---|---|---|
| In turn | 10.55 s | 12.55 s | 10.71 s |
| Concurrent, 4 workers | 9.28 s | 11.32 s | 9.54 s |
| In turn, again | 10.31 s | 11.99 s | 10.44 s |

- **Same verdicts:** all 20 drafts got identical verdicts from every guardrail in turn and concurrently, and in both in-turn passes. Concurrency changes no decision.
- **Local speed-up: 1.11x.** The local server only overlaps requests when started with `OLLAMA_NUM_PARALLEL` above 1. On this 16 GB machine Ollama otherwise chooses one slot, and four concurrent calls took as long as four in turn (a probe measured 1.05x). With four slots a probe of four short generations measured 1.75x, but guardrail calls are dominated by long prompts, and prompt processing on one local GPU barely overlaps. On a local judge the gain is real but small.
- **Hosted providers: 3.3x.** Two 80-ticket runs on the same models (gpt-4o-mini drafting, gemini-3.8-flash judging, cache off): b21_openai_gemini_80_20260920 in turn at 562f943, b21_openai_gemini_80_d12_20260920 concurrent at be776a6. Compared on tickets 1-70, because the Gemini account's prepaid credit ran out at ticket 71 of the concurrent run (HTTP 402; tickets 71-80 were fail-safe blocked, as A11 requires):

  | Tickets 1-70 | Guardrails mean | Guardrails p95 | Ticket mean | Ticket p95 |
  |---|---|---|---|---|
  | In turn | 10.14 s | 20.05 s | 13.99 s | 24.23 s |
  | Concurrent | 3.10 s | 8.90 s | 6.59 s | 12.19 s |

  4 of the 70 decisions differ between the runs, and every one had a different draft or classifier confidence (the drafting model varies run to run). On the 19 tickets whose drafts were identical in both runs, every guardrail verdict was identical. No rate-limit pacing engaged in either run.

The check first alternated the modes per ticket. That design was discarded: Ollama keeps each slot's last prompt, so whichever mode ran second on a ticket reused the first one's work (VAL-0001: 33.9 s, then 4.5 s).

## Consequences

- Positive: shorter guardrail stage wherever the judge serves requests in parallel; identical verdicts and identical decision-log rows (results keep guardrail order).
- Negative: up to four simultaneous calls to the judge's provider. On a rate-limited free tier that is a burst D-08 did not have to consider ("the harness is serial"). The D-08 pacer is now locked and shared across threads, so once a 429 engages it, concurrent calls are spaced one interval apart.
- The measured local gain is small; the latency target (p95 < 3 s) stays out of reach on local models whatever this setting is.

## Revisit trigger

A run where rate-limit pacing engages more often than in the equivalent in-turn run, or a hosted-provider run whose guardrail stage mean rises back towards the 10.1 s measured in turn.

## Supersedes / superseded by

None. Amends the D-08 note that the harness makes one call at a time.
