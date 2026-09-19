"""usage.py — token counts and cost for every model call, live or cached.

Satisfies: FR-22 (metrics report), NFR-08 (cost).

Every provider already returns prompt and completion token counts on each call
(``completion.usage``); until now they were discarded, so cost could only be
estimated. Each call site records them here, the harness drains the record once
per ticket, and the metrics report carries the run's totals.

Replies served from the model cache (D-08) are recorded too, marked
``cached``. The Build Specification encourages the cache; it does not excuse a
run from saying how much of it was replayed. A cached call is billed nothing,
so its stored token counts are reported as replayed tokens and cost saved,
never mixed into the tokens and cost actually spent.

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
    # Local Ollama models (8192-token context variants): no per-token charge.
    "llama3.1-8b-ctx8k": (0.0, 0.0),
    "qwen2.5-7b-ctx8k": (0.0, 0.0),
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


def _count(usage: Any, name: str) -> Optional[int]:
    """A token count from an SDK usage object or from a dict stored in the cache."""
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def record(stage: str, model: str, usage: Any, *, cached: bool = False) -> None:
    """Record one call. A response without usage is recorded with None counts,
    so a missing count stays visible instead of reading as zero tokens.

    For a cached reply, the counts are those of the live call that filled the
    cache; its cost is reported as saved, and nothing is billed."""
    prompt = _count(usage, "prompt_tokens")
    completion = _count(usage, "completion_tokens")
    price = cost_usd(model, prompt, completion) if prompt is not None and \
        completion is not None else None
    _calls.append({
        "stage": stage,
        "model": model,
        "cached": cached,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cost_usd": 0.0 if cached else price,
        "cost_saved_usd": price if cached else 0.0,
    })


def drain() -> list[dict[str, Any]]:
    """Return every call recorded since the last drain, and clear the record."""
    calls = list(_calls)
    _calls.clear()
    return calls


def summarise(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over a list of recorded calls, live and cached kept apart."""
    live = [c for c in calls if not c.get("cached")]
    cached = [c for c in calls if c.get("cached")]
    live_counted = [c for c in live if c["prompt_tokens"] is not None]
    cached_counted = [c for c in cached if c["prompt_tokens"] is not None]
    priced = [c for c in live_counted if c["cost_usd"] is not None]
    by_stage: dict[str, dict[str, int]] = {}
    for c in calls:
        s = by_stage.setdefault(c["stage"], {"calls": 0, "cached_calls": 0,
                                             "prompt_tokens": 0, "completion_tokens": 0})
        s["calls"] += 1
        if c.get("cached"):
            s["cached_calls"] += 1
        elif c["prompt_tokens"] is not None:
            s["prompt_tokens"] += c["prompt_tokens"]
            s["completion_tokens"] += c["completion_tokens"]
    return {
        "calls": len(calls),
        "live_calls": len(live),
        "cached_calls": len(cached),
        "calls_without_usage": len(live) - len(live_counted),
        # Tokens and cost actually spent: live calls only.
        "prompt_tokens": sum(c["prompt_tokens"] for c in live_counted),
        "completion_tokens": sum(c["completion_tokens"] for c in live_counted),
        "cost_usd": round(sum(c["cost_usd"] for c in priced), 6),
        "unpriced_calls": len(live_counted) - len(priced),
        # Replayed from the cache: what those replies cost when first made.
        "cached_prompt_tokens": sum(c["prompt_tokens"] for c in cached_counted),
        "cached_completion_tokens": sum(c["completion_tokens"] for c in cached_counted),
        "cached_calls_without_counts": len(cached) - len(cached_counted),
        "cost_saved_usd": round(sum(c["cost_saved_usd"] or 0.0 for c in cached_counted), 6),
        "by_stage": by_stage,
    }
