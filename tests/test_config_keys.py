"""An API key must never be sent to a provider that did not issue it.

On 14 Sep the judge was pointed at api.openai.com with no OpenAI key set, and
an unconditional fallback sent the OpenRouter key there 36 times.
"""
from __future__ import annotations

import subprocess
import sys

from src.config import resolve_api_key

OPENROUTER = "https://openrouter.ai/api/v1"
OPENAI = "https://api.openai.com/v1"


def test_an_explicit_key_always_wins():
    assert resolve_api_key("sk-judge", "sk-or-x", OPENAI, OPENROUTER) == "sk-judge"


def test_fallback_is_used_on_the_same_provider():
    assert resolve_api_key("", "sk-or-x", OPENROUTER, OPENROUTER) == "sk-or-x"


def test_same_host_with_a_different_path_is_the_same_provider():
    assert resolve_api_key("", "sk-or-x", "https://openrouter.ai/api/v2", OPENROUTER) == "sk-or-x"


def test_the_openrouter_key_is_never_resolved_for_openai():
    """The exact 14 Sep incident."""
    assert resolve_api_key("", "sk-or-x", OPENAI, OPENROUTER) == ""


def test_config_import_with_the_incident_settings_yields_no_judge_key():
    """End to end through the module, in a clean interpreter so the test does
    not disturb the configuration other tests imported.
    """
    code = (
        "from src.config import GUARDRAIL_API_KEY, MODEL_API_KEY;"
        "print(repr(GUARDRAIL_API_KEY)); print(bool(MODEL_API_KEY))"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENROUTER_API_KEY": "sk-or-test",
        "MODEL_BASE_URL": OPENROUTER,
        "MODEL_API_KEY": "",
        "GUARDRAIL_BASE_URL": OPENAI,
        "GUARDRAIL_API_KEY": "",
    }
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                         text=True, check=True).stdout.split()
    assert out[0] == "''", "judge must get no key rather than the OpenRouter key"
    assert out[1] == "True", "the generator on OpenRouter still gets its key"
