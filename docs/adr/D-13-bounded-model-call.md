# D-13 — Every model call gets a wall-clock deadline

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** NFR-03, A9, A11
**Affects:** `src/model_call.py` (new), `src/classify.py`, `src/generate.py`, `src/guardrails.py`, `src/config.py`, `.env.example`

## Context

`MODEL_TIMEOUT_SECONDS` (60 s) is passed to the OpenAI SDK, which passes it to httpx. An httpx read timeout is the maximum time **between bytes**, not for the request. A provider that dribbles bytes resets it indefinitely, and OpenRouter does exactly that: it sends periodic keep-alive comments on a waiting request so the connection is not dropped.

Measured today, run `harness-20260920T010351Z-a503e3e6` (llama-3.1-8b-instruct drafting, nemotron-3-super-120b-a12b:free judging): the harness stopped after ticket 8 with one connection open and silent for over seven minutes, while a direct probe of the same endpoint answered in 0.8 s. Nothing in the process was going to end that call. The run had to be killed.

This falsifies the claim in `src/config.py` that the worst case per call is `(1 + MODEL_MAX_RETRIES) * MODEL_TIMEOUT_SECONDS`, and it breaks A9: the evaluation set must be processed unattended in one command. It is also the most likely explanation for part of what D-01a records as free-tier "outages" on 13 and 17 Sep: a hung call looks like a dead run.

## Options considered

**A. Lower `MODEL_TIMEOUT_SECONDS`.** Does not help: the clock resets on every keep-alive byte, whatever its value.

**B. `signal.alarm` / `SIGALRM` around each call.** Main thread only, and the guardrails now call the provider from a thread pool (D-12), where signals cannot be delivered.

**C. Run each call in a daemon thread and wait a bounded time for it.** The waiting side always returns; a hung call is abandoned, the caller raises, and the pipeline's existing A11 paths turn that into a fallback or a fail-safe block. A daemon thread does not keep the process alive at exit.

**D. Move to the async client with `asyncio.wait_for`.** Correct, and a rewrite of every call site, the guardrail pool and the harness on the day of submission.

## Chosen

**Option C**, in `src/model_call.py` as `bounded(call)`, with `MODEL_CALL_DEADLINE_SECONDS` (default 180 s) from the environment. It wraps only the HTTP call, inside the D-08 pacer, so pacing sleeps do not count against the deadline.

## Rationale

180 s is about 13x a healthy nemotron guardrail call (13.8 s mean, the slowest judge measured) and covers the SDK's own retry chain in the normal case, while bounding the pathological one. The existing failure paths need no change: `classify` returns its unknown fallback, `generate` returns `unknown_fallback`, and each guardrail fails safe and blocks, all of which are already tested.

An abandoned thread may still hold a socket until the provider closes it. That is a leaked resource, not a stall: the run continues and the process can exit, because the thread is a daemon.

## Consequences

- Positive: A9 holds against a provider that keeps a connection alive without answering. The worst case per call is now the deadline, whatever the provider streams.
- Negative: a call abandoned at the deadline may still be billed by the provider, and its reply is discarded rather than cached. A run on a slow provider can therefore pay for work it does not use.
- `MODEL_TIMEOUT_SECONDS` and `MODEL_MAX_RETRIES` keep their meaning for well-behaved providers; the deadline is the outer bound.

## Revisit trigger

A run where calls are abandoned at the deadline while the provider is healthy (visible as `model_call.deadline_exceeded` in the log with no other failures) — then the deadline is too tight for that provider, or the retry budget needs lowering so the chain fits inside it.

## Supersedes / superseded by

None. Corrects the worst-case claim in `src/config.py` that D-08 relied on.
