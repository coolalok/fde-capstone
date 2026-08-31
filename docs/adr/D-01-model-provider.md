# D-01 — Model provider

**Status:** Accepted
**Date:** 2026-08-30
**Decider:** Alok Kulkarni
**Constrains:** FR-04, FR-05, FR-13, FR-14, FR-15, FR-22, FR-23; NFR-02, NFR-03, NFR-08
**Affects:** `src/config.py`, `src/classify.py`, `src/generate.py`, all `prompts/build/*.md`, `.env.example`

## Context

Every LLM call in the system (classification, retrieval query rewriting, generation, judge prompts) needs a chat-completion API. The pack requires the whole stack to fit inside a free tier (NFR-08). The provider needs to be reachable from a clean assessment machine with only an API key.

## Options considered

**A. OpenRouter free tier (Llama 3.1 8B).**
Setup Guide default. Broadest model catalog on a single API — we can swap the model via `MODEL_NAME` env var without switching provider code if a specific model degrades. Rate-limited (10 req/min free tier last observed) but the harness batches naturally by ticket.

**B. Groq free tier (Llama 3.1 8B).**
Faster latency (~3× OpenRouter). Free tier is stricter on daily tokens. Different API surface — a switch would touch the calling code plus prompt schemas.

**C. Local Ollama running Llama 3.1 8B.**
No rate limits. No network dependency, so A11 becomes trivial. But requires a GPU or 16GB+ RAM on the assessment machine, and Ollama itself becomes a setup dependency in the README. Assessment machine is not guaranteed to have Ollama pre-installed.

## Chosen

**Option A — OpenRouter free tier, model `meta-llama/llama-3.1-8b-instruct`.**

## Rationale

- Matches Setup Guide (§03), which the assessment machine's operator will already be familiar with.
- Single API key + one env var covers 20+ models we might want to try. Model swaps for the D-02-adjacent decision on the judge (bias mitigation requires the judge to be a different family — `mistralai/*` or `google/gemma-*`) don't need code changes.
- Free tier is sufficient for 500 dev + 80 validation + 120 hidden = 700 tickets × up to 4 model calls per ticket if we cache aggressively. Well within daily token limits.
- Requires zero infrastructure on the assessment machine — API key only.

## Consequences

- Positive: minimal setup burden, easy model swap, one API surface for all stages.
- Negative: rate-limited (10 req/min on free tier). Serial harness runs are fine; concurrent workers would need backoff coordination.
- Mitigation: exponential backoff + response cache in `src/config.py` (already implemented). NFR-08 tracked via call counts in `metrics_report.json`.

## Revisit trigger

- If free-tier rate limits force more than 15% of tickets into degraded routing (A11) on a validation run, evaluate Groq as a secondary provider with automatic failover.
- If OpenRouter drops the free tier for Llama 3.1 8B, switch to Groq or Ollama within 24 hours (assessment machine allowing) rather than paying.

## Supersedes / superseded by

None. This is the first model-provider decision.
