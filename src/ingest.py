"""ingest.py — normalise a raw ticket record into a Ticket object.

Satisfies: FR-01 (v2, accept four channels + one shape, evaluation-only fields
                  NOT carried),
           FR-02 (empty subject / body accepted, anomaly recorded),
           FR-03 (preserve original_body, expose cleaned body).

Segment fields (customer_tier, customer_region, customer_name, language_fluency)
are carried on the Ticket for downstream router use — but are NEVER passed to
the classifier (per FR-04 v2, enforced in src/classify.py).

Ground truth (labels.*) and outcome data (history.*) are explicitly dropped:
these are evaluation-time fields the harness reads separately from the raw
record. Passing them through would risk the classifier or router accidentally
reading ground truth at inference — the exact failure the pack's Dataset Guide
warns against.

FR-01 v1 required the opposite ("...and all `labels.*` fields"). That clause was
removed on 2026-09-03 — see Stage_5_PRD_Revision_Log.docx Table 3, FR-01 row.
Until then this module claimed to satisfy a requirement whose text it
contradicted.

Design note on FR-25 (docs_comment channel handling): the earlier PRD v2 had
an FR-25 to strip article references from docs_comment ticket bodies before
retrieval. A data check during this implementation (workbooks/Stage_5_PRD_Revision_Log.docx
Table 3) found that zero of 78 docs_comment tickets in the dev set actually
carry any such references. FR-25 was cut. This module therefore has NO
docs_comment special case — the four channel normalisers differ only in
cleaning defaults (chat has empty subject by design, per EV-DATA-11), not in
retrieval-time preprocessing.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from src.schema import Ticket

logger = logging.getLogger(__name__)

# The four channels the pack ships in this data set. Order matches EV-DATA-09.
KNOWN_CHANNELS: frozenset[str] = frozenset({"email", "chat", "docs_comment", "forum"})

# Fields the ingest step deliberately drops from the raw record.
# labels.* is ground truth for evaluation — never seen by production code.
# history.* is outcome data — recorded after human handling, not available at
# inference time. Passing either through Ticket would be a governance failure.
_EVAL_ONLY_KEYS: frozenset[str] = frozenset({"labels", "history"})

# Control characters we always strip (except LF and TAB which are legitimate
# whitespace in ticket bodies).
_CONTROL_CHARS_TO_STRIP = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalise_any(raw: dict[str, Any]) -> Ticket:
    """Dispatch to the per-channel normaliser and return a Ticket.

    Never raises. An unknown channel returns a Ticket normalised by the
    generic path with a 'unknown_channel:<name>' warning; the router sees
    that and escalates.
    """
    channel = str(raw.get("channel", "")).strip()
    if channel == "email":
        return _normalise_email(raw)
    if channel == "chat":
        return _normalise_chat(raw)
    if channel == "docs_comment":
        return _normalise_docs_comment(raw)
    if channel == "forum":
        return _normalise_forum(raw)
    return _normalise_generic(raw, unknown_channel=True)


# ─── per-channel normalisers ─────────────────────────────────────────


def _normalise_email(raw: dict) -> Ticket:
    """Email — the fullest-featured channel. Subject and body both present."""
    return _build_ticket(raw, expect_subject=True)


def _normalise_chat(raw: dict) -> Ticket:
    """Chat — subject is empty by design (EV-DATA-11: 155 of 155 chat tickets
    in the dev set have empty subject). Not a warning."""
    return _build_ticket(raw, expect_subject=False)


def _normalise_docs_comment(raw: dict) -> Ticket:
    """Comments filed against a help article page. Subject usually present.

    Historical note: FR-25 (removed 2026-09-02) proposed stripping article
    references from the body here. A data check found zero of 78 dev tickets
    carry such references. This function therefore has no special case.
    """
    return _build_ticket(raw, expect_subject=True)


def _normalise_forum(raw: dict) -> Ticket:
    """Forum posts. Subject present. Community may have replied before the
    ticket reaches support — that's handled downstream by the router, not
    here."""
    return _build_ticket(raw, expect_subject=True)


def _normalise_generic(raw: dict, unknown_channel: bool = False) -> Ticket:
    """Fallback for channels we don't recognise. Cleans conservatively and
    tags the anomaly on Ticket.warnings so the router can escalate."""
    ticket = _build_ticket(raw, expect_subject=True)
    if unknown_channel:
        ticket.warnings.append(f"unknown_channel:{raw.get('channel', '')}")
    return ticket


# ─── the actual building work ────────────────────────────────────────


def _coerce_str(value: Any) -> tuple[str, list[str]]:
    """Coerce one raw JSON field to text. Returns (text, notes).

    JSON null becomes "" and NOT the string "None". The distinction is the
    whole point of this function: `str(None)` yields four characters that look
    like real content, so a null body would sail past the FR-02 `empty_body`
    warning and be handed to the classifier as the word "None".

    Any other non-string type is converted and flagged, so a malformed record
    still ingests (FR-02 says never raise) but the anomaly reaches the router.
    """
    if value is None:
        return "", []
    if isinstance(value, str):
        return value, []
    return str(value), [f"non_string_type:{type(value).__name__}"]


def _build_ticket(raw: dict, *, expect_subject: bool) -> Ticket:
    """Build a Ticket from the raw record. All cleaning happens here."""
    warnings: list[str] = []

    raw_body, body_type_notes = _coerce_str(raw.get("body"))
    raw_subject, subject_type_notes = _coerce_str(raw.get("subject"))
    warnings.extend(f"body:{n}" for n in body_type_notes)
    warnings.extend(f"subject:{n}" for n in subject_type_notes)

    # FR-02: empty body is possible in the hidden set. Log a warning; downstream
    # is expected to escalate (a ticket with no body has nothing to classify).
    if raw_body == "":
        warnings.append("empty_body")
    if raw_subject == "" and expect_subject:
        # For chat (`expect_subject=False`) this is normal. For everything else
        # it's a mild anomaly worth flagging.
        warnings.append("empty_subject")

    cleaned_body, body_notes = _clean_text(raw_body)
    cleaned_subject, subject_notes = _clean_text(raw_subject)
    warnings.extend(f"body:{n}" for n in body_notes)
    warnings.extend(f"subject:{n}" for n in subject_notes)

    # Silent guarantee: labels and history are stripped before Ticket is built.
    # Using pydantic's extra="ignore" (Ticket schema config) would silently
    # drop them anyway, but explicit is safer than implicit here — this is a
    # governance guarantee, not a schema convenience.
    if any(k in raw for k in _EVAL_ONLY_KEYS):
        logger.debug(
            "ingest.dropped_eval_only_keys",
            extra={
                "ticket_id": raw.get("ticket_id", "?"),
                "dropped": [k for k in _EVAL_ONLY_KEYS if k in raw],
            },
        )

    # Metadata fields go through the same null-safe coercion. A null
    # customer_tier must become "" and not "None": the router's tier-aware
    # policy (D-05a) compares against tier names, and "None" would look
    # populated while matching nothing. Type notes are dropped for these
    # fields — they are not classified, so the anomaly isn't worth a warning.
    ticket = Ticket(
        ticket_id=_coerce_str(raw.get("ticket_id"))[0],
        channel=_coerce_str(raw.get("channel"))[0],
        subject=cleaned_subject,
        body=cleaned_body,
        received_at=_coerce_str(raw.get("received_at"))[0],
        original_body=raw_body,
        warnings=warnings,
        # Segment fields — carried, not classifier-exposed
        customer_id=_coerce_str(raw.get("customer_id"))[0],
        customer_name=_coerce_str(raw.get("customer_name"))[0],
        customer_tier=_coerce_str(raw.get("customer_tier"))[0],
        customer_region=_coerce_str(raw.get("customer_region"))[0],
        language_fluency=_coerce_str(raw.get("language_fluency"))[0],
    )
    return ticket


def _clean_text(text: str) -> tuple[str, list[str]]:
    """Normalise and clean a text field. Returns (cleaned, notes).

    The notes list carries small anomalies worth recording without failing
    (e.g. control characters found and stripped). Written this way so the
    caller can prefix the notes with the field name.
    """
    notes: list[str] = []
    if not text:
        return "", notes

    # Unicode NFC — a customer who typed 'é' as one character or two should
    # end up in one form so retrieval hashes / index matches consistently.
    original = text
    text = unicodedata.normalize("NFC", text)
    if text != original:
        notes.append("unicode_nfc_normalised")

    # Normalise line endings to LF before anything else looks at them. CR is
    # deliberately absent from _CONTROL_CHARS_TO_STRIP (it is a line ending,
    # not noise), so without this step a bare CR — an old-Mac line ending, or
    # a stray CR mid-line — would survive into the body and into the embedded
    # text. CRLF used to come out right only by accident: the rstrip() below
    # ate the CR after the split on LF, which does nothing for a lone CR.
    before = text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text != before:
        notes.append("newlines_normalised")

    # Strip control characters except LF (\x0a) and TAB (\x09).
    before = text
    text = _CONTROL_CHARS_TO_STRIP.sub("", text)
    if text != before:
        notes.append("control_chars_stripped")

    # Trim leading/trailing whitespace. Do NOT collapse internal newlines —
    # some tickets carry list structure that the generator wants to preserve
    # for citation. Do collapse runs of horizontal whitespace only.
    before = text
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = text.strip()
    if text != before.strip():
        notes.append("whitespace_normalised")

    return text, notes
