# D-08 — Model response cache, and how rate limits are handled

**Status:** Accepted
**Date:** 2026-09-19
**Decider:** Alok Kulkarni
**Constrains:** FR-23, NFR-03, NFR-08; supports A5, A9, A11
**Affects:** `src/model_cache.py`, `src/rate_limit.py`, `src/config.py`, `src/classify.py`, `src/generate.py`, `src/guardrails.py`, `.env.example`, `tests/conftest.py`

## Context

The Build Specification states the position twice, and a third time as an instruction:

> "Rate limits are a design problem. Free tiers throttle. Handling that with backoff, queuing and caching is part of the engineering, not an obstacle to it."

> "Caching is encouraged. Cache model responses during development. It saves your allowance, makes runs reproducible, and is good practice regardless."

> "If you find yourself unable to complete a run within a free allowance, raise it rather than paying for capacity or quietly reducing your scope. It is a solvable problem and almost always indicates a design issue, such as calling the model where a cache or a rule would do."

D-01a keeps the free tier as the graded configuration, and no free configuration has completed a validation run. Three attempts failed on provider availability: 13 Sep lost 46 of 80 classifications to connection errors; 17 Sep returned 429 on 7 of 8; 18 Sep completed 8 tickets but lost about 40% of judge calls to empty responses. Each attempt started from a fresh quota position and re-called the model for every ticket, including tickets that had already been answered correctly in an earlier attempt.

The third quote describes what happened on 14 Sep exactly: the response to an allowance problem was to pay, when a cache was the missing design.

## Options considered

**A. Leave it. Treat throttling as an environmental fact.**
Defensible on one reading — the same document says a throttling provider "is not a defect in your work and it will not reduce your marks", and A11 covers degradation. But it declines the engineering the other two quotes ask for.

**B. On-disk response cache, a larger retry budget, and pacing that engages only after a rate limit.**
A cache keyed on the request; retries raised from 2 to 5 so the SDK's existing backoff gets a real chance to work; call spacing that stays at zero until the provider actually refuses.

**C. B, plus `tenacity` for backoff and a concurrency semaphore.**
What a first reading of the Build Spec sentence suggests: backoff, queuing, caching.

**D. Keep paying.**
Rejected by the maintainer on 17 Sep, and the final demonstration must run on the free tier.

## Chosen

**Option B.**

Option C was rejected on inspection rather than principle:

- **Backoff already exists.** The OpenAI SDK (1.30.0) retries with exponential backoff and jitter and honours `Retry-After` (`openai/_base_client.py::_calculate_retry_timeout`). Adding `tenacity` would wrap machinery we already run. What was wrong was the *budget*: `INITIAL_RETRY_DELAY` 0.5s and `MAX_RETRY_DELAY` 8s, so two retries spend under two seconds before a ticket gives up. That is nothing against an upstream 429. `MODEL_MAX_RETRIES` is now 5.
- **There is no queue to bound.** The harness processes tickets strictly one at a time (`evaluation/harness.py`), so a concurrency semaphore set to 1 is a no-op with a configuration knob attached. If concurrency is ever added, the semaphore comes with it.

Pacing, the other half of "queuing", is in Option B but **adaptive rather than fixed**. A fixed delay before every call slows a healthy run to guard against a limit we may not be near, and the failures recorded so far were upstream capacity rather than our own request rate — no self-pacing would have avoided them. `src/rate_limit.py` therefore waits zero until a call fails on a rate limit, then spaces calls (from `MODEL_RATE_LIMIT_INITIAL_SECONDS`, doubling, capped at `MODEL_RATE_LIMIT_MAX_SECONDS`, or the provider's own `Retry-After` where it sends one) and relaxes back to zero after calls succeed again.

## Rationale

The cache is the piece with no existing equivalent, and it is the one the third quote names. A hit costs no tokens and no quota, so re-running after a crash, re-examining one ticket, or replaying a whole run is free. On a free tier that is the difference between one attempt per quota window and as many as the work needs.

Keyed on model, system prompt, user prompt, seed and temperature. A prompt version bump changes the system text, so it changes the key: a reply drafted by an older prompt version can never be served to a newer one.

The lookup happens before the API-key check and before the client is built, so a warmed cache replays with no provider access at all. A miss still raises — inventing an answer would be worse than failing.

## Consequences

- **A cached run does not measure live behaviour.** A gate run that reports provider health, latency or failure rates must set `MODEL_CACHE_DISABLED=1`. The figures in a cached run describe the run that filled the cache.
- **The cache does not make the system deterministic.** Generation is not reproducible run to run even at temperature 0 with a seed (Stage 5 log, Bug 6); the cache replays a stored reply rather than removing that variance. A5 holds for its own reason: `route()` is a pure function of values computed upstream. Claiming the cache satisfies A5 would be claiming a property we have not got.
- **Tests run with the cache off, by an autouse fixture.** Found immediately on landing: a test with a stubbed provider wrote its fake reply into the real cache, where a live run could have served it, and tests asserting "the provider was called with X" began failing as soon as an earlier test had cached that prompt. Both faults were invisible in a single test file and only appeared across the suite.
- Cache entries live under `storage/` (gitignored), so nothing about them ships in the submission.
- **Pacing engages later than a first 429.** The SDK swallows rate-limit responses inside its own retries, so `rate_limit` only sees one when all five are exhausted — that is, after a ticket has already been lost. It protects the rest of the run rather than the ticket that triggered it. Seeing the first 429 instead would mean reading response headers on every call, which is more machinery than the evidence justifies today.
- **A paced run is slower by construction**, and the interval is capped so an unattended run still terminates (A9). `rate_limit.state()` reports the current spacing for the run log.

## Revisit trigger

- A free configuration still cannot complete an 80-ticket run with the cache warm and five retries: then either add real queueing (rate-aware pacing between calls) or, per the Build Spec, record that the run cannot complete within the free allowance and say so in the report rather than paying.
- Concurrency is added to the harness: revisit the semaphore rejected above.

## Supersedes / superseded by

None. Extends D-01a, which chose the free tier and left the model open.
