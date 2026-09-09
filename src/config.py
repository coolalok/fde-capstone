"""Central configuration loaded from environment via .env.

Every threshold, path, model name and timeout comes from here.
No literals scattered through the codebase — that's the D-XX rule.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Model provider (OpenRouter free tier by default)
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
MODEL_NAME: str = os.environ.get("MODEL_NAME", "meta-llama/llama-3.1-8b-instruct")

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
# A healthy call runs ~2s, so 60s is ~30x headroom while keeping the worst
# case per call bounded at (1 + retries) * timeout.
MODEL_TIMEOUT_SECONDS: float = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "60.0"))
MODEL_MAX_RETRIES: int = int(os.environ.get("MODEL_MAX_RETRIES", "2"))

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

# Logging
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
# Optional second destination for structured logs. Empty = stderr only.
# An unattended run (A9) has nobody watching stderr, so B-19/B-21 should
# set this. Applied by src/logging_config.configure_logging().
LOG_FILE: str = os.environ.get("LOG_FILE", "")


def require_key() -> str:
    """Fail loudly if the model provider key is missing."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return OPENROUTER_API_KEY
