"""injection.py — input-side detection of prompt-injection attempts.

Mitigates: R-03 (a customer's input is treated as an instruction).
Cites:     EV-RAGD-INJ (the RAG_demo reference implementation's heuristic list).
See:       docs/adr/D-16-input-side-injection-detection.md

The system already defends the OUTPUT: FR-18 blocks a draft that shows signs of
having followed an injected instruction, and every prompt wraps ticket text in
delimiters and says to treat it as data. The 2026-09-20 probe ran six crafted
attacks through the live pipeline: none succeeded, every one was blocked, and
FR-18 fired on none of them. The blocks came from answer relevance and
tone/scope — the attempts were invisible as attempts.

This module closes that gap on the input side. It is a cheap, deterministic
pattern match with no model call and no latency, and it is deliberately NOT a
classifier: it catches the common "override the instructions" shapes and will
miss a careful attacker. What it buys is that an attempt is RECORDED and the
ticket reaches a person, which is what R-03 asks for.

What it must never do is refuse the customer. A support ticket containing
"ignore previous instructions" may be a quoted error message, a developer
describing their own prompt, or an attack. All three go to a human; none gets
a refusal written by the automation.
"""
from __future__ import annotations

import re

# Adapted from the RAG_demo reference implementation (EV-RAGD-INJ). Two
# deliberate changes for this project:
#   - `act as (?!a helpful)` is dropped: support tickets legitimately say "act
#     as an admin", "act as the account owner", and a false flag here sends a
#     real customer to the queue for no reason.
#   - the delimiter spoof is added. It is not in the reference list because
#     that demo has no delimited ticket block; ours does, and a body carrying
#     our own markers is an attempt to forge the boundary (D-16).
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("instruction_override",
     r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?"
     r"(previous|prior|above|earlier|system)\s+(instructions?|prompts?|rules?)"),
    ("persona_override", r"you\s+are\s+now\b"),
    ("system_prompt_probe",
     r"(reveal|show|print|repeat|output)\s+(me\s+)?(your\s+)?"
     r"(system\s+prompt|instructions|system\s+message|configuration)"),
    ("system_prompt_mention", r"\bsystem\s+prompt\b"),
    ("jailbreak", r"\bjailbreak\b|\bdo\s+anything\s+now\b|\bDAN\b"),
    ("role_injection", r"^\s*(system|assistant)\s*:", re.MULTILINE),
    ("delimiter_spoof", r"<<\s*[A-Z_]{3,}\s*>>"),
)

_COMPILED = tuple(
    (name, re.compile(pattern, re.IGNORECASE | (flags[0] if flags else 0)))
    for name, pattern, *flags in _PATTERNS
)


def detect(*texts: str) -> list[str]:
    """Names of the injection shapes found in the given text, sorted.

    Returns [] when nothing matches. Never raises: a detection failure must
    not stop a ticket being processed.
    """
    joined = "\n".join(t for t in texts if t)
    if not joined:
        return []
    return sorted({name for name, pattern in _COMPILED if pattern.search(joined)})
