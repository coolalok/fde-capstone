"""Central configuration loaded from environment via .env.

Every threshold, path, model name and timeout comes from here.
No literals scattered through the codebase — that's the D-XX rule.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

# Model provider (OpenRouter free tier by default)
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
MODEL_NAME: str = os.environ.get("MODEL_NAME", "meta-llama/llama-3.1-8b-instruct")

# Provider endpoint and key. Both default to OpenRouter, so a clean checkout
# behaves exactly as D-01 specifies and the cost-nothing rule holds — the
# assessor runs this on their own machine and must not need a paid account.
#
# They are overridable ONLY so a paid endpoint can be pointed at for DIAGNOSIS
# (e.g. separating a model-capability failure from a free-tier rate limit,
# which the free tier cannot answer on its own). Results from another provider
# are a SEPARATE experiment, not an update to the llama-3.1-8b measurements
# that D-05b, B-16 and B-21 rest on — label them as such or the report ends up
# mixing two systems.
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def resolve_api_key(explicit: str, fallback_key: str, base_url: str,
                    fallback_base_url: str) -> str:
    """The key for an endpoint: the one set for it, else a fallback key ONLY when
    the fallback belongs to the same provider (same host).

    A key must never travel to a provider it was not issued by. On 14 Sep the
    judge was pointed at api.openai.com with no OpenAI key set; the old
    unconditional fallback filled the gap with the OpenRouter key, and 36
    guardrail calls sent it to OpenAI, which answered 401. Returning "" here
    instead makes the call site raise its own "no key set" error before any
    request leaves the machine.
    """
    if explicit:
        return explicit
    same_host = urlparse(base_url).netloc.lower() == urlparse(fallback_base_url).netloc.lower()
    return fallback_key if same_host else ""


# Providers whose OpenAI-compatible endpoint REJECTS the `seed` parameter with
# HTTP 400 rather than ignoring it. Observed 14 Sep: Gemini answered
# 400 "Unknown name \"seed\": Cannot find field." A judge there failed every call,
# so every guardrail would have failed safe and blocked every reply. A deny-list,
# not an allow-list, so providers that honour seed (OpenAI, OpenRouter) keep it
# and determinism is not weakened where it works.
_SEED_REJECTING_HOSTS = frozenset({"generativelanguage.googleapis.com"})


def accepts_seed(base_url: str) -> bool:
    return urlparse(base_url).netloc.lower() not in _SEED_REJECTING_HOSTS


MODEL_BASE_URL: str = os.environ.get("MODEL_BASE_URL", _OPENROUTER_BASE_URL)
MODEL_API_KEY: str = resolve_api_key(
    os.environ.get("MODEL_API_KEY", ""), OPENROUTER_API_KEY, MODEL_BASE_URL, _OPENROUTER_BASE_URL
)

# Endpoint and key for the JUDGE, separate from the generator's.
#
# Both default to the generator's values, so an unset config behaves exactly as
# before. They exist because the judge must be independent of the generator
# (D-07/Bug 5) and independence can require a different PROVIDER, not just a
# different model name — OpenRouter's free tier caps :free models at 50
# requests/day, which is 16 tickets' worth of guardrail calls and cannot carry
# an 80-ticket gate run. Without this split the only way to get a working judge
# was to move the generator too, which would invalidate every measurement taken
# on llama-3.1-8b.
GUARDRAIL_BASE_URL: str = (
    os.environ.get("GUARDRAIL_BASE_URL", "") or MODEL_BASE_URL
)
# Falls back to the generator's key only when the judge is on the generator's
# provider — see resolve_api_key.
GUARDRAIL_API_KEY: str = resolve_api_key(
    os.environ.get("GUARDRAIL_API_KEY", ""), MODEL_API_KEY, GUARDRAIL_BASE_URL, MODEL_BASE_URL
)

# Judge model for the LLM-backed guardrails (PII, grounding, tone/scope).
#
# Deliberately NOT MODEL_NAME. The 8B generator model cannot perform claim-level
# verification: measured on the validation set it blocked 71 of 71 drafts it
# judged, including 48 whose ground truth says auto-respond, and it rejected text
# that was byte-for-byte present in the cited passage. Recalibrating the prompt
# (PR-GUARDRAIL-GROUNDING-01 v2.0) changed nothing, so the limit is capability.
# On pinned drafts nemotron-120b gets both directions right where llama-8b gets
# one wrong. See Bug 5 in the Stage 5 revision log.
#
# Using a different model family for the judge also matches the self-preference
# rule capstone-prompt-writer sets for evaluation judges.
GUARDRAIL_MODEL: str = os.environ.get(
    "GUARDRAIL_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
)

# Embeddings (local — no key)
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Per-request timeout and retry cap for every model call.
#
# The OpenAI SDK defaults to a 600s read timeout with 2 retries, so an
# unresponsive call can occupy ~30 minutes before it fails and nothing in our
# code caps it. A9 promises the evaluation set is processed unattended in one
# command; without an explicit bound, a single hung call stalls that run
# indefinitely. Found 2026-09-04 when a validation sweep hung for two hours at
# ticket 40 of 80.
#
# A healthy call runs ~2s, so 60s is ~30x headroom. It does NOT bound the call:
# httpx reads it as the maximum gap between bytes, and a provider that streams
# keep-alive comments resets it indefinitely (D-13). MODEL_CALL_DEADLINE_SECONDS
# is the actual bound.
MODEL_TIMEOUT_SECONDS: float = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "60.0"))
# 5, not the SDK default of 2. The SDK already backs off exponentially with
# jitter and honours Retry-After, but it starts at 0.5s and caps at 8s, so two
# retries spend under 2 seconds before a ticket gives up — nothing against an
# upstream 429 (Build Spec: "Rate limits are a design problem"). Five keeps the
# retry chain inside the D-13 deadline, which is what bounds it for A9.
MODEL_MAX_RETRIES: int = int(os.environ.get("MODEL_MAX_RETRIES", "5"))

# The wall-clock bound on one provider call, enforced by the caller (D-13).
# 180s is ~13x the slowest judge measured (nemotron-120b, 13.8s mean) and covers
# the SDK's retry chain on a healthy provider; past it the call is abandoned and
# the stage takes its A11 path. This is the only limit a provider cannot reset
# by keeping the connection alive.
MODEL_CALL_DEADLINE_SECONDS: float = float(
    os.environ.get("MODEL_CALL_DEADLINE_SECONDS", "180.0"))

# Storage paths
_ROOT = Path(__file__).parent.parent
CHROMA_PATH: Path = Path(os.environ.get("CHROMA_PATH", _ROOT / "storage" / "chroma"))
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", f"sqlite:///{_ROOT / 'storage' / 'decisions.db'}"
)
# How long a decision-log write waits for the SQLite lock before giving up.
# SQLite's own default is 5s, which a parallel harness run can exceed; a write
# that times out becomes an A8 reconciliation gap, so give it room.
DECISION_LOG_TIMEOUT_SECONDS: float = float(
    os.environ.get("DECISION_LOG_TIMEOUT_SECONDS", "30.0")
)

# Runtime thresholds (illustrative — set from data per D-05 ADR)
# 0.85 set by the B-16 sweep on the validation set (D-05b), NOT by feel.
# Caveat recorded in D-05b: no threshold reached the EV-M3 precision floor of
# 0.95 — the measured ceiling is 0.760 here. The binding constraint is
# answerability, not confidence, so this number is provisional until the
# FR-17 grounding guardrail is measured in the loop.
CONFIDENCE_THRESHOLD: float = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))

# ── Kill switch (Governance Framework §5) ────────────────────────────
# Read at CALL time, not at import: every other setting in this module is a
# module-level constant, so a change needs a restart. A kill switch that needs
# a restart is not a kill switch — the pack asks for a way to stop the system
# answering "immediately, without a deployment". Setting KILL_SWITCH=1 in the
# environment of a running process therefore takes effect on the next ticket.
#
# It replaces the documented CONFIDENCE_THRESHOLD=1.01 trick, which needed a
# restart and was indistinguishable in the log from a badly tuned threshold
# (D-15).
KILL_SWITCH_ENV = "KILL_SWITCH"
_TRUTHY = frozenset({"1", "true", "on", "yes"})


def kill_switch_active() -> bool:
    """True when automatic answering is halted. Read on every routing call."""
    return os.environ.get(KILL_SWITCH_ENV, "0").strip().lower() in _TRUTHY


RETRIEVAL_TOP_K: int = int(os.environ.get("RETRIEVAL_TOP_K", "5"))
# 0.25 set by measurement, not by feel — see D-02a. Calibrated against COSINE
# relevance scores; the index must be built in cosine space or this number
# means something different (src/index_docs.py DISTANCE_SPACE).
RETRIEVAL_THRESHOLD: float = float(os.environ.get("RETRIEVAL_THRESHOLD", "0.25"))

# Generation
# Self-RAG groundedness check retry cap (D-06 — retry once, then escalate).
GENERATE_MAX_RETRIES: int = int(os.environ.get("GENERATE_MAX_RETRIES", "1"))
# Model temperature for generation — 0.0 = deterministic per D-06 A5.
GENERATE_TEMPERATURE: float = float(os.environ.get("GENERATE_TEMPERATURE", "0.0"))

# Adaptive pacing between model calls (D-08). Zero until a call actually fails
# on a rate limit, then calls are spaced and the spacing relaxes as they
# succeed. The maximum is what keeps an unattended run terminating (A9).
MODEL_RATE_LIMIT_INITIAL_SECONDS: float = float(
    os.environ.get("MODEL_RATE_LIMIT_INITIAL_SECONDS", "2.0"))
MODEL_RATE_LIMIT_MAX_SECONDS: float = float(
    os.environ.get("MODEL_RATE_LIMIT_MAX_SECONDS", "15.0"))

# Guardrails run concurrently, at most this many at once (D-12). They are
# independent checks of the same draft, so the order they finish in cannot
# change a verdict. 1 runs them one after another, as before D-12.
GUARDRAIL_MAX_WORKERS: int = max(1, int(os.environ.get("GUARDRAIL_MAX_WORKERS", "4")))

# Model response cache (Build Spec: "Caching is encouraged"). A hit costs no
# tokens and no quota, which is what makes a re-run on a throttled free tier
# affordable. Set MODEL_CACHE_DISABLED=1 for a run that must call the provider
# for every ticket — a gate run measuring live behaviour, for instance.
MODEL_CACHE_DIR: str = os.environ.get("MODEL_CACHE_DIR", str(_ROOT / "storage" / "model_cache"))
MODEL_CACHE_DISABLED: bool = os.environ.get("MODEL_CACHE_DISABLED", "0") == "1"

# Monitoring — port for the Prometheus /metrics endpoint (Setup Guide §06).
# 0 = do not start the server, which is the default: a graded run must not need
# a free port, and the metrics report (A10) is the artefact that is assessed.
METRICS_PORT: int = int(os.environ.get("METRICS_PORT", "0"))

# Logging
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
# Optional second destination for structured logs. Empty = stderr only.
# An unattended run (A9) has nobody watching stderr, so B-19/B-21 should
# set this. Applied by src/logging_config.configure_logging().
LOG_FILE: str = os.environ.get("LOG_FILE", "")


def require_key() -> str:
    """Fail loudly if the model provider key is missing."""
    if not MODEL_API_KEY:
        raise RuntimeError(
            "No model provider key set. Copy .env.example to .env and fill in "
            "OPENROUTER_API_KEY (or MODEL_API_KEY if pointing at another provider)."
        )
    return MODEL_API_KEY
