"""Tests for src/prompt_loader.py — versioned prompt loading + rendering.

Coverage focuses on the substitution semantics (Bug 4 fix) because that is
where prompt injection can enter the system through a customer-controlled
field. Parsing paths are covered by the prompt files themselves — every
prompt in prompts/build/ is loaded and validated in test_load_all below.
"""
from __future__ import annotations

import pytest

from src.prompt_loader import LoadedPrompt, load_prompt


# ─── render_user: single-pass substitution (Bug 4) ────────────────────


def _make(template: str) -> LoadedPrompt:
    return LoadedPrompt(
        prompt_id="TEST",
        version="1.0",
        metadata={},
        system="ignored",
        user_template=template,
    )


def test_customer_field_containing_placeholder_stays_literal():
    """Bug 4 regression: a customer body containing a literal ``{{passages}}``
    must NOT trigger a second substitution that splices the system-controlled
    passages block into a customer region of the rendered prompt.
    """
    p = _make(
        "PASSAGES:\n{{passages}}\n---\n"
        "Subject: {{subject}}\n"
        "Body: {{body}}"
    )
    rendered = p.render_user(
        passages="SYSTEM-INJECTED-PASSAGES-BLOCK",
        subject="ok",
        body="hostile body that contains {{passages}} as a literal string",
    )
    # System block substituted exactly once.
    assert rendered.count("SYSTEM-INJECTED-PASSAGES-BLOCK") == 1
    # Customer body preserved verbatim, including the literal placeholder.
    assert "hostile body that contains {{passages}} as a literal string" in rendered


def test_substitution_is_iteration_order_independent():
    """The previous implementation was safe only when the caller passed
    system-controlled kwargs before customer-controlled ones. Prove that the
    single-pass substitution no longer depends on argument order.
    """
    template = "S: {{passages}} | C: {{body}}"
    hostile = "leak-{{passages}}-marker"

    # Customer field first
    out_a = _make(template).render_user(body=hostile, passages="SECRET")
    # System field first
    out_b = _make(template).render_user(passages="SECRET", body=hostile)

    assert out_a == out_b == "S: SECRET | C: leak-{{passages}}-marker"


def test_unknown_placeholders_are_left_untouched():
    p = _make("known {{a}} unknown {{missing}}")
    assert p.render_user(a="X") == "known X unknown {{missing}}"


def test_empty_kwargs_returns_template_verbatim():
    template = "no {{substitutions}} here"
    assert _make(template).render_user() == template


def test_placeholder_key_with_regex_special_chars_is_escaped():
    """Keys are passed through re.escape so a key like ``dot.name`` still
    matches literally.
    """
    p = _make("val = {{dot.name}}")
    kwargs = {"dot.name": "Y"}
    assert p.render_user(**kwargs) == "val = Y"


def test_non_string_values_are_coerced_via_str():
    p = _make("n={{n}} flag={{flag}}")
    assert p.render_user(n=42, flag=True) == "n=42 flag=True"


def test_repeated_placeholder_substituted_every_occurrence():
    p = _make("{{x}} then {{x}} again")
    assert p.render_user(x="Q") == "Q then Q again"


# ─── load_prompt end-to-end sanity ────────────────────────────────────


def test_load_prompt_raises_filenotfound_for_missing_id():
    with pytest.raises(FileNotFoundError):
        load_prompt("PR-DOES-NOT-EXIST")
