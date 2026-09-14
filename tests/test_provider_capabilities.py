"""Providers differ in which OpenAI parameters they accept.

Gemini's OpenAI-compatible endpoint rejects `seed` with HTTP 400 (observed
14 Sep), so a Gemini judge failed every call and would have blocked every
reply. seed is sent only where the provider accepts it.
"""
from __future__ import annotations

import importlib

import pytest

from src.config import accepts_seed

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI = "https://api.openai.com/v1"
OPENROUTER = "https://openrouter.ai/api/v1"


@pytest.mark.parametrize("url, expected", [(OPENAI, True), (OPENROUTER, True), (GEMINI, False)])
def test_accepts_seed(url, expected):
    assert accepts_seed(url) is expected


class _Choice:
    finish_reason = "stop"

    class message:
        content = '{"passed": true}'


class _Completion:
    choices = [_Choice()]


@pytest.mark.parametrize("module, base_attr, key_attr", [
    ("src.guardrails", "GUARDRAIL_BASE_URL", "GUARDRAIL_API_KEY"),
    ("src.classify", "MODEL_BASE_URL", "MODEL_API_KEY"),
    ("src.generate", "MODEL_BASE_URL", "MODEL_API_KEY"),
])
@pytest.mark.parametrize("url, seed_sent", [(OPENAI, True), (GEMINI, False)])
def test_call_sites_send_seed_only_where_accepted(module, base_attr, key_attr, url, seed_sent,
                                                  monkeypatch):
    import openai

    mod = importlib.import_module(module)
    sent: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            sent.update(kwargs)
            return _Completion()

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(mod, base_attr, url, raising=False)
    monkeypatch.setattr(mod, key_attr, "test-key", raising=False)
    monkeypatch.setattr(mod, "require_key", lambda: "test-key", raising=False)
    mod._openrouter_call("system", "user", 7)
    assert ("seed" in sent) is seed_sent
    if seed_sent:
        assert sent["seed"] == 7
    assert sent["response_format"] == {"type": "json_object"}   # JSON mode kept everywhere
