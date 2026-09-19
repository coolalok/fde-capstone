"""The model-response cache: keys, hits, bypass, and replay without a provider.

Build Spec asks for this twice — "Rate limits are a design problem ... backoff,
queuing and caching is part of the engineering" and "Caching is encouraged.
Cache model responses during development. It saves your allowance, makes runs
reproducible". The free tier is the graded configuration (D-01a), so a re-run
that costs no quota is the difference between one attempt a day and as many as
we need.

No network anywhere: the provider is a fake, and the last test proves a cached
run needs no key at all.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Point the cache at a temp directory for the duration of one test."""
    import src.config as config
    import src.model_cache as model_cache

    monkeypatch.setattr(config, "MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DISABLED", False)
    return tmp_path


def _key(**overrides):
    from src.model_cache import key

    fields = {"model": "m", "system": "sys", "user": "usr", "seed": 0, "temperature": 0.0}
    fields.update(overrides)
    return key(**fields)


def test_the_same_request_gives_the_same_key():
    assert _key() == _key()


@pytest.mark.parametrize("field,value", [
    ("model", "other-model"),
    ("system", "a different system prompt"),   # a prompt version bump lands here
    ("user", "a different ticket"),
    ("seed", 1),
    ("temperature", 0.7),
])
def test_any_change_to_the_request_changes_the_key(field, value):
    """A prompt edit must not be served a reply drafted by the previous version."""
    assert _key(**{field: value}) != _key()


def test_a_stored_reply_comes_back(cache_dir):
    from src.model_cache import get, put

    put(_key(), '{"intent": "billing_query"}', stage="classification", model="m")
    assert get(_key(), stage="classification") == '{"intent": "billing_query"}'


def test_a_miss_is_none_not_an_error(cache_dir):
    from src.model_cache import get

    assert get(_key(user="never asked"), stage="classification") is None


def test_a_corrupt_entry_is_a_miss_not_a_crash(cache_dir):
    """A half-written file from a killed run must not end a ticket."""
    from src.model_cache import get

    (cache_dir / f"{_key()}.json").write_text("{not json")
    assert get(_key()) is None


def test_the_cache_can_be_bypassed(cache_dir, monkeypatch):
    """A gate run measuring live behaviour must be able to force real calls."""
    import src.model_cache as model_cache

    model_cache.put(_key(), "stored")
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DISABLED", True)
    assert model_cache.get(_key()) is None
    model_cache.put(_key(user="fresh"), "not stored either")
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DISABLED", False)
    assert model_cache.get(_key(user="fresh")) is None


class _FakeOpenAI:
    """Counts how many times the provider was actually called."""

    calls = 0

    def __init__(self, **kwargs):
        pass

    class chat:  # noqa: N801 - mirrors the SDK shape
        class completions:
            @staticmethod
            def create(**kwargs):
                _FakeOpenAI.calls += 1

                class _Msg:
                    content = '{"intent": "api_key_issue", "urgency": "medium", ' \
                              '"confidence": 0.9, "alternatives": [], "reasoning": "k"}'

                class _Choice:
                    message = _Msg()
                    finish_reason = "stop"

                class _Completion:
                    choices = [_Choice()]
                    usage = None

                return _Completion()


def test_the_second_identical_call_does_not_reach_the_provider(cache_dir, monkeypatch):
    import openai

    import src.classify as classify

    _FakeOpenAI.calls = 0
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(classify, "require_key", lambda: "k", raising=False)

    first = classify._openrouter_call("system", "user", 0)
    second = classify._openrouter_call("system", "user", 0)

    assert first == second
    assert _FakeOpenAI.calls == 1, "the second call should have been served from the cache"


def test_a_cached_reply_is_served_with_no_api_key(cache_dir, monkeypatch):
    """The demo case: replay a previous run on a machine with no provider access.

    The cache is checked before the key guard and before the client is built, so
    a warmed cache replays without credentials. A miss still raises, because
    inventing an answer would be worse than failing.
    """
    import openai

    import src.classify as classify

    _FakeOpenAI.calls = 0
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(classify, "require_key", lambda: "k", raising=False)
    warmed = classify._openrouter_call("system", "user", 0)

    def no_key():
        raise RuntimeError("MODEL_API_KEY is not set")

    monkeypatch.setattr(classify, "require_key", no_key, raising=False)

    assert classify._openrouter_call("system", "user", 0) == warmed
    assert _FakeOpenAI.calls == 1
    with pytest.raises(RuntimeError, match="not set"):
        classify._openrouter_call("system", "a ticket never seen before", 0)
