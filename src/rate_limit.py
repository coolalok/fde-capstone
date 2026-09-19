"""rate_limit.py — pace model calls, but only once the provider has said no.

Satisfies: NFR-03 (a throttled provider must not end a run), NFR-08 (cost).
Cites:     Build Specification, "Rate limits are a design problem" — "Free tiers
           throttle. Handling that with backoff, queuing and caching is part of
           the engineering, not an obstacle to it."
See:       docs/adr/D-08-model-response-cache.md

Adaptive on purpose. A fixed delay between calls would slow every run to protect
against a limit we may not be near: the 13 and 17 Sep free-tier failures were
upstream capacity, which no amount of self-pacing would have avoided. So the
pacer stays out of the way until a call actually fails on a rate limit, then
spaces subsequent calls and relaxes again as they succeed.

Where it sits: the OpenAI SDK already retries a 429 internally with exponential
backoff and Retry-After. This wakes up only when those retries are EXHAUSTED —
so on a run that is genuinely over the limit, pacing engages after the first
ticket that fails rather than on the first 429. That is the point at which
spacing calls is cheaper than losing tickets.

Bounded for A9: the interval never exceeds MODEL_RATE_LIMIT_MAX_SECONDS, so an
unattended run still terminates.

Serial by design: the harness processes one ticket at a time, so this keeps no
lock. Add one with the first concurrent caller.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from src.config import (
    MODEL_RATE_LIMIT_INITIAL_SECONDS,
    MODEL_RATE_LIMIT_MAX_SECONDS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Successful calls needed at the current spacing before it is halved. Three is
# enough to show the provider is answering again without giving the quota back
# on a single lucky call.
_RELAX_AFTER_SUCCESSES = 3

_interval_seconds = 0.0
_last_call_at = 0.0
_consecutive_successes = 0


def state() -> dict:
    """Current pacing, for the run log and tests."""
    return {"interval_seconds": round(_interval_seconds, 2),
            "consecutive_successes": _consecutive_successes}


def reset() -> None:
    """Forget any pacing. For tests, and for a new run in the same process."""
    global _interval_seconds, _last_call_at, _consecutive_successes
    _interval_seconds = 0.0
    _last_call_at = 0.0
    _consecutive_successes = 0


def _retry_after_seconds(exc: Exception) -> float | None:
    """The provider's own Retry-After, when it sent one. It knows better than we do."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def penalise(exc: Exception) -> None:
    """A call failed on a rate limit: start pacing, or space calls further apart."""
    global _interval_seconds, _consecutive_successes
    _consecutive_successes = 0
    stated = _retry_after_seconds(exc)
    if stated is not None:
        proposed = stated
    elif _interval_seconds == 0.0:
        proposed = MODEL_RATE_LIMIT_INITIAL_SECONDS
    else:
        proposed = _interval_seconds * 2
    _interval_seconds = min(proposed, MODEL_RATE_LIMIT_MAX_SECONDS)
    logger.warning("rate_limit.engaged",
                   extra={"interval_seconds": round(_interval_seconds, 2),
                          "retry_after_header": stated})


def relax() -> None:
    """A call succeeded. After a few in a row, give the spacing back."""
    global _interval_seconds, _consecutive_successes
    if _interval_seconds == 0.0:
        return
    _consecutive_successes += 1
    if _consecutive_successes < _RELAX_AFTER_SUCCESSES:
        return
    _consecutive_successes = 0
    # Below a second the spacing is doing nothing a fast provider notices, so
    # switch it off rather than trailing a token delay through the whole run.
    _interval_seconds = 0.0 if _interval_seconds <= 1.0 else _interval_seconds / 2
    logger.info("rate_limit.relaxed",
                extra={"interval_seconds": round(_interval_seconds, 2)})


def wait() -> float:
    """Sleep until the current spacing has elapsed since the last call.

    Returns the seconds waited, which is 0.0 whenever pacing is not engaged —
    the normal case, and the reason this costs nothing on a healthy provider.
    """
    global _last_call_at
    now = time.monotonic()
    if _interval_seconds <= 0.0:
        _last_call_at = now
        return 0.0
    due_at = _last_call_at + _interval_seconds
    delay = max(0.0, due_at - now)
    if delay > 0:
        time.sleep(delay)
    _last_call_at = time.monotonic()
    return delay


def guarded(call: Callable[[], T]) -> T:
    """Run one provider call through the pacer. Re-raises whatever it raises.

    Rate-limit errors are identified by class name rather than by importing
    openai, so this module stays importable without the SDK — the same reason
    the call sites import it lazily.
    """
    wait()
    try:
        result = call()
    except Exception as exc:
        if type(exc).__name__ == "RateLimitError" or getattr(
                getattr(exc, "response", None), "status_code", None) == 429:
            penalise(exc)
        raise
    relax()
    return result
