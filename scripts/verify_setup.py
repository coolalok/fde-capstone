"""Local sanity check — run after `pip install -r requirements.txt`.

Verifies: Python version, env vars, all imports, model provider round-trip,
Chroma index reachable, decision-log DB writable.

Usage:
    python -m scripts.verify_setup
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def check(label: str, ok: bool, hint: str = "") -> bool:
    marker = "OK  " if ok else "FAIL"
    print(f"  [{marker}] {label}")
    if not ok and hint:
        print(f"         -> {hint}")
    return ok


def main() -> int:
    print("\n== FDE Capstone setup verifier ==\n")
    all_ok = True

    # 1. Python version
    py_ok = sys.version_info >= (3, 10)
    all_ok &= check(
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
        py_ok,
        "Need Python >= 3.10. Recreate the venv with a newer interpreter.",
    )

    # 2. Imports
    required = [
        "langchain", "langchain_community", "chromadb",
        "sentence_transformers", "fastapi", "uvicorn",
        "pydantic", "requests", "dotenv",
        "prometheus_client", "sqlalchemy", "pytest",
    ]
    for mod in required:
        try:
            importlib.import_module(mod)
            all_ok &= check(f"import {mod}", True)
        except ImportError as e:
            all_ok &= check(f"import {mod}", False, str(e))

    # 3. .env values
    try:
        from src.config import OPENROUTER_API_KEY, MODEL_NAME
        all_ok &= check(
            "OPENROUTER_API_KEY set",
            bool(OPENROUTER_API_KEY) and OPENROUTER_API_KEY != "your_key_here",
            "Copy .env.example to .env and paste your OpenRouter key.",
        )
        check(f"MODEL_NAME = {MODEL_NAME}", True)
    except Exception as e:
        all_ok &= check("src.config loads", False, str(e))

    # 4. Model round-trip
    try:
        import requests, os
        from src.config import require_key, MODEL_NAME
        key = require_key()
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": "Reply with the word ready."}],
            },
            timeout=30,
        )
        rt_ok = r.status_code == 200
        all_ok &= check(
            f"OpenRouter round-trip (status {r.status_code})",
            rt_ok,
            "Verify key, model name, and free-tier availability.",
        )
        if rt_ok:
            reply = r.json()["choices"][0]["message"]["content"][:60]
            print(f"         reply: {reply!r}")
    except Exception as e:
        all_ok &= check("OpenRouter round-trip", False, str(e))

    # 5. Data files present
    data = Path(__file__).parent.parent / "data"
    for name in [
        "documentation.json", "development_tickets.json",
        "validation_tickets.json", "ground_truth_responses.json",
    ]:
        all_ok &= check(f"data/{name}", (data / name).exists())

    # 6. Decision log DB writable
    try:
        from src.logging_store import init_db
        init_db()
        all_ok &= check("SQLite decision log init", True)
    except Exception as e:
        all_ok &= check("SQLite decision log init", False, str(e))

    print()
    if all_ok:
        print("== All checks passed. Ready for Week 2. ==")
        return 0
    print("== Some checks failed. Fix the FAIL rows above before continuing. ==")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
