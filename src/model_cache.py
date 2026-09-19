"""model_cache.py — on-disk cache of model replies, keyed on the request.

Satisfies: NFR-08 (cost), NFR-03 (a rate-limited provider must not end a run).
Cites:     Build Specification, "Rate limits are a design problem" ("Free tiers
           throttle. Handling that with backoff, queuing and caching is part of
           the engineering, not an obstacle to it") and "Caching is encouraged"
           ("Cache model responses during development. It saves your allowance,
           makes runs reproducible, and is good practice regardless.").
See:       docs/adr/D-08-model-response-cache.md

A hit costs no tokens and no quota, so a re-run after a crash, a debugging pass
over the same tickets, or a second look at one ticket is free. That matters here
because the free tier is the graded configuration (D-01a) and every failed
free-tier attempt so far started from a fresh quota position.

What it does NOT do: make the system deterministic. The generator is not
reproducible run to run even at temperature 0 with a seed (Stage 5 log, Bug 6);
a cache replays a stored reply rather than removing that variance. A5 (routing
determinism) holds for its own reason — route() is a pure function of values
computed upstream.

Keyed on model, system prompt, user prompt, seed and temperature. A prompt
version bump changes the text, so it changes the key: stale replies cannot
survive a prompt edit.

Layout: one JSON file per key under MODEL_CACHE_DIR (storage/, gitignored).
Files, not SQLite, because the decision log already owns the database and a
cache write must never block on it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional

from src.config import MODEL_CACHE_DIR, MODEL_CACHE_DISABLED
from src.metrics import MODEL_CACHE_HITS

logger = logging.getLogger(__name__)


def key(*, model: str, system: str, user: str, seed: int, temperature: float) -> str:
    """Stable key for one request. Any change to any field is a different key."""
    payload = json.dumps(
        {"model": model, "system": system, "user": user, "seed": seed,
         "temperature": temperature},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get(cache_key: str, *, stage: str = "") -> Optional[str]:
    """The stored reply, or None. Never raises: a broken cache is not an outage."""
    if MODEL_CACHE_DISABLED:
        return None
    path = Path(MODEL_CACHE_DIR) / f"{cache_key}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        content = record["content"]
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("model_cache.unreadable",
                       extra={"key": cache_key[:12], "error": str(exc)})
        return None
    MODEL_CACHE_HITS.labels(stage=stage or "unknown").inc()
    logger.info("model_cache.hit", extra={"key": cache_key[:12], "stage": stage})
    return content


def put(cache_key: str, content: str, *, stage: str = "", model: str = "") -> None:
    """Store a reply. Never raises: failing to cache must not fail the ticket."""
    if MODEL_CACHE_DISABLED:
        return
    directory = Path(MODEL_CACHE_DIR)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a killed run cannot leave a half-written entry
        # that later reads as a valid reply.
        with tempfile.NamedTemporaryFile("w", dir=directory, delete=False,
                                         encoding="utf-8") as handle:
            json.dump({"content": content, "stage": stage, "model": model}, handle)
            temporary = Path(handle.name)
        temporary.replace(directory / f"{cache_key}.json")
    except OSError as exc:
        logger.warning("model_cache.unwritable",
                       extra={"key": cache_key[:12], "error": str(exc)})
