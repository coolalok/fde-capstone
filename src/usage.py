"""usage.py — token counts and cost for every model call.

Satisfies: FR-22 (metrics report), NFR-08 (cost).

Every provider already returns prompt and completion token counts on each call
(``completion.usage``); until now they were discarded, so cost could only be
estimated. Each call site records them here, the harness drains the record once
per ticket, and the metrics report carries the run's totals.

Cost uses PRICES_PER_MILLION, list prices checked 2026-09-14/15 on the
providers' pricing pages. An OpenRouter model id ending ``:free`` costs 0. A
model with no listed price is counted as unpriced rather than guessed.

Only calls that returned a response are recorded: a call that raised consumed
quota but returned no token counts.
"""
from __future__ import annotations

from typing import Any, Optional

# USD per million tokens: (input, output).
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gemini-3.8-flash": (0.75, 3.75),
}

_calls: list[dict[str, Any]] = []


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """USD cost of one call, or None when the model has no listed price."""
    if model.endswith(":free"):
        return 0.0
    price = PRICES_PER_MILLION.get(model)
    if price is None:
        return None
    return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000


def record(stage: str, model: str, usage: Any) -> None:
    """Record one call. A response without usage is recorded with None counts,
    so a missing count stays visible instead of reading as zero tokens."""
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    counted = prompt is not None and completion is not None
    _calls.append({
        "stage": stage,
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cost_usd": cost_usd(model, prompt, completion) if counted else None,
    })


def drain() -> list[dict[str, Any]]:
    """Return every call recorded since the last drain, and clear the record."""
    calls = list(_calls)
    _calls.clear()
    return calls


def summarise(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over a list of recorded calls, overall and by stage."""
    counted = [c for c in calls if c["prompt_tokens"] is not None]
    priced = [c for c in counted if c["cost_usd"] is not None]
    by_stage: dict[str, dict[str, int]] = {}
    for c in counted:
        s = by_stage.setdefault(c["stage"], {"calls": 0, "prompt_tokens": 0,
                                             "completion_tokens": 0})
        s["calls"] += 1
        s["prompt_tokens"] += c["prompt_tokens"]
        s["completion_tokens"] += c["completion_tokens"]
    return {
        "calls": len(calls),
        "calls_without_usage": len(calls) - len(counted),
        "prompt_tokens": sum(c["prompt_tokens"] for c in counted),
        "completion_tokens": sum(c["completion_tokens"] for c in counted),
        "cost_usd": round(sum(c["cost_usd"] for c in priced), 6),
        "unpriced_calls": len(counted) - len(priced),
        "by_stage": by_stage,
    }
