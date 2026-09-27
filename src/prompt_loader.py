"""Load a versioned prompt from prompts/build/ or prompts/evaluation/ by ID.

Prompts are markdown files with a YAML-ish frontmatter and a fixed section
structure — see capstone-prompt-writer skill for the format.

Reads:
  - the frontmatter (id, version, purpose, requirement, model, temperature,
    last_changed)
  - the model-facing content — everything between `## System` and
    `## User (template)` inclusive of the system + task + intent codes +
    urgency + confidence bands + output schema sections
  - the user template code block, so ticket fields can be interpolated at
    call time
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
_BUILD_DIR = _REPO_ROOT / "prompts" / "build"
_EVAL_DIR = _REPO_ROOT / "prompts" / "evaluation"


# Every prompt wraps customer text in markers like <<TICKET_END>> and tells the
# model that what sits between them is data. A ticket body containing those
# markers can therefore claim to close the data block and open a system one —
# the INJ-02 probe on 2026-09-20 sent exactly that. The model resisted, but a
# defence that depends on the model resisting is not a defence, so the markers
# are neutralised in substituted VALUES before they reach the prompt (D-16).
#
# Escaped, not stripped: the reviewer reading the escalation must see what the
# customer actually sent, and a guardrail must still be able to judge it. The
# template's own markers are untouched — only values passed to render_user are
# rewritten.
_DELIMITER_RE = re.compile(r"<<\s*([A-Za-z_]{3,})\s*>>")


def escape_delimiters(value: str) -> str:
    """Neutralise prompt-boundary markers inside customer-supplied text."""
    return _DELIMITER_RE.sub(lambda m: f"[[{m.group(1)}]]", value)


@dataclass
class LoadedPrompt:
    prompt_id: str
    version: str
    metadata: dict[str, Any]
    system: str
    user_template: str

    def render_user(self, **kwargs: Any) -> str:
        """Fill ``{{key}}`` placeholders in the user template.

        Single-pass substitution (Bug 4 fix). The previous implementation
        ran ``str.replace`` once per key, so a substituted value's contents
        could themselves match a later ``{{key}}`` placeholder — meaning a
        customer body containing literal ``{{passages}}`` would splice the
        system-controlled passages block into a customer-controlled region
        of the rendered prompt. The regex substitution below rewrites every
        matched placeholder in one pass, so a substituted value is inert
        against the remaining keys regardless of iteration order.

        Placeholders whose keys are not in ``kwargs`` are left untouched
        (same behaviour as the previous implementation). If ``kwargs`` is
        empty, the template is returned as-is.
        """
        if not kwargs:
            return self.user_template
        pattern = re.compile(
            r"\{\{(" + "|".join(re.escape(k) for k in kwargs) + r")\}\}"
        )
        return pattern.sub(
            lambda m: escape_delimiters(str(kwargs[m.group(1)])), self.user_template
        )


def load_prompt(prompt_id: str) -> LoadedPrompt:
    """Load one prompt by ID. Searches prompts/build/ then prompts/evaluation/."""
    for base in (_BUILD_DIR, _EVAL_DIR):
        path = base / f"{prompt_id}.md"
        if path.exists():
            return _parse(prompt_id, path.read_text(encoding="utf-8"))
    searched = [str(_BUILD_DIR), str(_EVAL_DIR)]
    raise FileNotFoundError(f"Prompt not found: {prompt_id!r}. Searched: {searched}")


def _parse(prompt_id: str, text: str) -> LoadedPrompt:
    # Frontmatter — between the first two lines that are exactly '---'
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not fm_match:
        raise ValueError(f"Prompt {prompt_id!r} is missing YAML frontmatter")
    metadata = _parse_frontmatter(fm_match.group(1))
    body = fm_match.group(2)

    version = str(metadata.get("version", "?"))

    # System = everything from '## System' up to '## User (template)'
    sys_match = re.search(
        r"^## System\s*\n(.*?)^## User \(template\)",
        body,
        re.DOTALL | re.MULTILINE,
    )
    if not sys_match:
        raise ValueError(f"Prompt {prompt_id!r} is missing System / User (template) sections")
    system = sys_match.group(1).rstrip()

    # User template = the first fenced code block after '## User (template)'
    user_match = re.search(
        r"^## User \(template\)\s*\n\s*```[a-zA-Z]*\s*\n(.*?)\n```",
        body,
        re.DOTALL | re.MULTILINE,
    )
    if not user_match:
        raise ValueError(
            f"Prompt {prompt_id!r} is missing a fenced code block in User (template)"
        )
    user_template = user_match.group(1).rstrip()

    return LoadedPrompt(
        prompt_id=prompt_id,
        version=version,
        metadata=metadata,
        system=system,
        user_template=user_template,
    )


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Tiny key: value parser. Handles str and float. Enough for our prompt files."""
    out: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip matching quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Try float
        try:
            out[key] = float(value) if "." in value else int(value)
            continue
        except ValueError:
            pass
        out[key] = value
    return out
