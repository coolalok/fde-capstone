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

# Embeddings (local — no key)
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Storage paths
_ROOT = Path(__file__).parent.parent
CHROMA_PATH: Path = Path(os.environ.get("CHROMA_PATH", _ROOT / "storage" / "chroma"))
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", f"sqlite:///{_ROOT / 'storage' / 'decisions.db'}"
)

# Runtime thresholds (illustrative — set from data per D-05 ADR)
CONFIDENCE_THRESHOLD: float = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.80"))
RETRIEVAL_TOP_K: int = int(os.environ.get("RETRIEVAL_TOP_K", "5"))
RETRIEVAL_THRESHOLD: float = float(os.environ.get("RETRIEVAL_THRESHOLD", "0.35"))

# Logging
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


def require_key() -> str:
    """Fail loudly if the model provider key is missing."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return OPENROUTER_API_KEY
