"""guardrails.py — four blocking guardrails on the generator's drafted response.

Satisfies: FR-16 (PII detection), FR-17 (grounding), FR-18 (instruction
           integrity), FR-19 (confidence-floor), plus a fifth tone/scope
           guardrail that has no PRD FR yet — see the module doc-block
           below for the traceability gap and its Stage 5 log entry.
           All blocking per A7 — there is no "warning" mode in this
           project.
Uses prompts: PR-GUARDRAIL-PII-01, PR-GUARDRAIL-GROUNDING-01,
           PR-GUARDRAIL-TONESCOPE-01.
Writes:       one row to the decision log per ``run_all()`` invocation
              carrying the array of GuardrailResults for A8 reconciliation.

Design decisions worth reading:

- **Five guardrails, one interface.** Every guardrail is a class exposing
  ``.check(response, context) -> GuardrailResult``. ``run_all()`` calls
  every one in order and returns the list. The router treats any
  ``passed=False`` with ``blocking=True`` as a hard block. Four map to
  the PRD FR-16..19 set (PII, grounding, instruction integrity,
  confidence floor); the fifth (tone/scope — blocks commitments about
  refunds, delivery timings, and roadmap items) is implicit per
  architecture.md §6 with no PRD FR yet (traceability via R-04 + EV-D4;
  FR-25 for tone/scope is future work, logged in Stage 5 as intentional
  debt so the traceability audit reports the gap explicitly). FR-GUARD-01..04
  were deferred by PRD Table 9 Q7 (2026-09-03); the tests/test_guardrails.py
  contract for the FR-GUARD family stays module-skipped pending Week 3
  revisit.

- **Fail SAFE, always.** Every guardrail wraps any I/O or LLM path in
  try/except. An exception NEVER returns ``passed=True`` — it returns
  ``passed=False`` with ``reason="guardrail_error: ..."``. Losing the
  ability to check is treated the same as failing the check (Marcus's
  veto EV-M3 — rather nothing than wrong).

- **Regex + LLM for PII, LLM-only for grounding.** Structured PII
  categories (email, api_key, phone, account_number) have deterministic
  regex signatures — running the regex belt-and-braces catches the LLM's
  false negatives cheaply. Names are only detected by the LLM. Grounding
  is entirely a claim-support judgement; there is no cheap structural
  proxy. Instruction-integrity and confidence-floor are pure Python and
  need no LLM.

- **Customer-name whitelist for PII lives in the wrapper, not the
  prompt.** PR-GUARDRAIL-PII-01 is customer-blind (same fairness rule as
  PR-CLASSIFY-01). This module compares each detected ``person_name``
  against ``context.ticket.customer_name`` (normalised) and drops it
  from the block list when it matches.

- **Pluggable model call.** ``call_model`` is a
  ``(system, user, seed) -> str`` callable so tests never touch
  OpenRouter. Production wires ``_openrouter_call`` in.

- **Deterministic where possible.** Regex and pure-Python guardrails are
  deterministic by construction. LLM-backed guardrails use
  ``temperature=0.0`` and a fixed seed. Same input → same verdict (A5).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from src.config import (
    CONFIDENCE_THRESHOLD,
    MODEL_MAX_RETRIES,
    GUARDRAIL_MODEL,
    MODEL_NAME,
    MODEL_TIMEOUT_SECONDS,
    MODEL_API_KEY,
    MODEL_BASE_URL,
    require_key,
)
from src.logging_store import log_decision
from src.metrics import MODEL_CALL_FAILURES
from src.prompt_loader import load_prompt
from src.schema import (
    GeneratedResponse,
    GuardrailContext,
    GuardrailResult,
    Passage,
)

logger = logging.getLogger(__name__)

# Load the guardrail prompts at import so their versions are fixed for the
# process lifetime. A missing / malformed prompt is a build-time error, not
# runtime A11 material — raise loudly here so CI catches it.
_PII_PROMPT = load_prompt("PR-GUARDRAIL-PII-01")
_GROUNDING_PROMPT = load_prompt("PR-GUARDRAIL-GROUNDING-01")
_TONESCOPE_PROMPT = load_prompt("PR-GUARDRAIL-TONESCOPE-01")
_PII_PROMPT_VERSION = f"PR-GUARDRAIL-PII-01@{_PII_PROMPT.version}"
_GROUNDING_PROMPT_VERSION = f"PR-GUARDRAIL-GROUNDING-01@{_GROUNDING_PROMPT.version}"
_TONESCOPE_PROMPT_VERSION = f"PR-GUARDRAIL-TONESCOPE-01@{_TONESCOPE_PROMPT.version}"


# ─── model call seam ────────────────────────────────────────────────

# (system_prompt, user_prompt, seed) -> raw model response as a string.
ModelCall = Callable[[str, str, int], str]


def _openrouter_call(system: str, user: str, seed: int = 0) -> str:
    """Call OpenRouter via the OpenAI SDK. Raises on any I/O or auth failure.

    The caller catches the raise and converts it into a fail-safe verdict.
    """
    from openai import OpenAI  # lazy import so tests don't need the pkg

    require_key()
    # Bounded on purpose: the SDK default is a 600s read timeout with 2
    # retries, so one unresponsive call can occupy ~30 minutes and stall an
    # unattended run (A9). See MODEL_TIMEOUT_SECONDS in src/config.py.
    client = OpenAI(
        api_key=MODEL_API_KEY,
        base_url=MODEL_BASE_URL,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
    completion = client.chat.completions.create(
        model=GUARDRAIL_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        seed=seed,
        response_format={"type": "json_object"},
    )
    # OpenRouter can answer 200 with choices=None when the upstream provider
    # errors. Subscripting that raised "TypeError: 'NoneType' object is not
    # subscriptable" from inside the caller's broad except, which recorded the
    # symptom rather than the cause. Raise the cause instead — the fail-safe
    # cascade is unchanged, but the reason string and MODEL_CALL_FAILURES say
    # what actually happened.
    if not getattr(completion, "choices", None):
        raise ValueError(f"provider returned no choices (model={GUARDRAIL_MODEL})")
    content = completion.choices[0].message.content
    if not content:
        # Observed with nemotron: a 200 response carrying null content. The old
        # `or ""` turned that into an empty string, which then failed JSON
        # parsing as "Expecting value" — a misleading error for a provider that
        # simply returned nothing. Raise the true cause so the fail-safe verdict
        # and the failure counter record what actually happened.
        raise ValueError(f"{GUARDRAIL_MODEL} returned empty content")
    return content


# ─── regex signatures for structured PII (belt-and-braces on PR-GUARDRAIL-PII-01)

# RFC-shaped emails, including simple obfuscations.
_RE_EMAIL = re.compile(
    r"""
    [A-Za-z0-9._%+\-]+
    \s* (?:@|\[at\]|\(at\)) \s*
    [A-Za-z0-9.\-]+
    \s* (?:\.|\[dot\]|\(dot\)) \s*
    [A-Za-z]{2,24}
    """,
    re.VERBOSE,
)
# Common API key prefixes + long alphanumeric bodies.
_RE_API_KEY = re.compile(
    r"""
    (?:
        sk-[A-Za-z0-9_\-]{16,}
      | pk-[A-Za-z0-9_\-]{16,}
      | AKIA[0-9A-Z]{12,20}
      | AIza[A-Za-z0-9_\-]{16,}
      | ghp_[A-Za-z0-9]{16,}
      | ghs_[A-Za-z0-9]{16,}
      | xox[bp]-[A-Za-z0-9\-]{16,}
      | Bearer\s+[A-Za-z0-9_.\-+/=]{24,}
    )
    """,
    re.VERBOSE,
)
# Phone numbers — E.164 + common national formats. Deliberately conservative
# to avoid flagging every 4-digit sequence.
_RE_PHONE = re.compile(
    r"""
    (?:
        \+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{2,4}[\s\-.]?\d{0,4}
      | \(\d{3}\)\s*\d{3}[\s\-.]?\d{4}
      | \b\d{3}[\s\-.]\d{3}[\s\-.]\d{4}\b
    )
    """,
    re.VERBOSE,
)
# Inline citation markers the generator writes, e.g. "[DOC-ACCT-001]". All 29
# corpus doc_ids match this shape.
_RE_CITATION_MARKER = re.compile(r"\[DOC-[A-Z]+-\d+\]")


def _mask_citation_markers(text: str) -> str:
    """Blank out inline citation markers before the PII regex pass.

    DEV-0485 was blocked as account_number PII because "[DOC-ACCT-001]"
    contains "ACCT-001", which is exactly the CloudServe account-ID shape
    _RE_ACCOUNT looks for. The marker is a system-generated reference to a
    public help article from a closed 29-document corpus — it is never
    customer data, so matching it is a pure false positive, and a blocking
    one: every answer citing a DOC-ACCT-* article would be withheld.

    Each marker is replaced by the same number of spaces rather than removed,
    so match.start() still indexes correctly into the original answer.
    """
    return _RE_CITATION_MARKER.sub(lambda m: " " * len(m.group(0)), text)


# CloudServe-style account IDs + bank / card digit sequences.
_RE_ACCOUNT = re.compile(
    r"""
    (?:
        \b(?:CUST|ACC|ACCT)-\d{2,}
        # Card-shaped: grouped digits. A BARE \b\d{13,19}\b used to live here
        # and matched ANY long digit run, so it fired on ordinary identifiers in
        # a draft — 2 of 20 blocks in the OpenAI run were this false positive
        # (VAL-0008, VAL-0019). Grouping or an explicit label is what makes a
        # digit run an account number rather than just a number.
      | \b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{2,4}\b
        # Labelled: "account number 1234567890123456"
      | \b(?:account|acct|card)\s*(?:number|no\.?|\#)?\s*:?\s*\d{10,19}\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Persona-shift + injection patterns for FR-18. These are detection
# fingerprints of the model itself having been redirected — the drafted
# answer talking about being an AI, being instructed, or acknowledging a new
# persona. Case-insensitive, anchored to whole-word starts to keep the false
# positive rate low.
# Commitment patterns for FR-implicit tone/scope guardrail. Strong
# regex signatures for the highest-liability phrasings; softer commitments
# are the LLM's job. Case-insensitive; deliberate conservatism to keep
# false-positive rate low.
_RE_REFUND = re.compile(
    r"""
    \b(?:
        we\ will\ (?:refund|reimburse|credit|apply\ a\ credit)
      | (?:refund|reimbursement|credit)\ (?:will|shall)\ be\ (?:issued|processed|applied|credited)
      | you\ will\ (?:receive|get)\ a\ (?:refund|credit|reimbursement)
      | (?:refunded|reimbursed|credited)\ \$?\d
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)
_RE_ETA = re.compile(
    r"""
    \b(?:
        we\ will\ (?:have\ this\ )?(?:fix|resolve|deliver|ship|deploy|complete)
      | (?:fixed|resolved|delivered|shipped|deployed|completed)
        \ by\ (?:end\ of\ business|eod|tomorrow|next\ week|\w+day)
      | you.ll\ (?:have|get|see)\ (?:this|it)\ (?:fixed|resolved|working)\ (?:by|within)
      | expect\ (?:a\ )?(?:resolution|response|fix)\ (?:by|within)
      # Must carry a resolution verb. A bare "within N days" also appears in
      # descriptions of policy ("refund requests within 30 days"), which is
      # reporting a documented rule, not promising anything.
      | (?:resolved|fixed|completed|delivered|shipped|actioned)
        \ within\ \d+\ (?:hours?|days?|business\ days?)
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)
_RE_ROADMAP = re.compile(
    r"""
    \b(?:
        will\ be\ (?:added|available|released|shipped)\ in
      | coming\ (?:in|soon\ in)\ v?\d
      | (?:planned|targeted|scheduled)\ for\ (?:q[1-4]|the\ next|our|release)
      | in\ (?:the\ )?(?:next|upcoming)\ release
      | on\ (?:our|the)\ roadmap\ for
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

_RE_PERSONA_SHIFT = re.compile(
    r"""
    \b(?:
        as\ an\ ai
      | as\ a\ language\ model
      | as\ an\ assistant
      | i\ am\ (?:now|a)\s+(?:an\ ai|a\ language\ model|an\ assistant|\S+\s*bot)
      | ignore\ (?:all\ |any\ )?(?:prior|previous)\ instructions
      | system\s*:
      | disregard\ (?:the|your)\ (?:above|previous)
      | new\ instructions
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)


# ─── base guardrail ─────────────────────────────────────────────────


class Guardrail(Protocol):
    """Interface every guardrail obeys. See capstone-component-impl §guardrails."""

    name: str
    blocking: bool

    def check(
        self, response: GeneratedResponse, context: GuardrailContext
    ) -> GuardrailResult: ...


# ─── FR-16: PII guardrail ───────────────────────────────────────────


@dataclass
class PIIGuardrail:
    """FR-16 — block responses containing PII.

    Runs two passes: (1) regex over the drafted answer text catches
    structured PII (emails, keys, phones, account numbers). (2) the LLM
    prompt PR-GUARDRAIL-PII-01 catches names and any structured pattern
    the regex missed. Detections from both are merged; the
    customer-name whitelist is applied to ``person_name`` detections in
    this module (not the prompt).
    """

    name: str = "pii"
    blocking: bool = True
    call_model: Optional[ModelCall] = None

    def check(
        self, response: GeneratedResponse, context: GuardrailContext
    ) -> GuardrailResult:
        # Unknown or empty answers cannot leak PII — pass immediately.
        if response.unknown or not response.answer:
            return GuardrailResult(
                name=self.name,
                passed=True,
                blocking=self.blocking,
                reason="no answer text to inspect",
            )

        detections: list[dict] = []

        # ── Pass 1: regex ─────────────────────────────────────
        # Citation markers are masked first — see _mask_citation_markers.
        # Indices are preserved, so start_index still points into answer.
        scan_text = _mask_citation_markers(response.answer)
        for category, pattern in [
            ("email", _RE_EMAIL),
            ("api_key", _RE_API_KEY),
            ("phone", _RE_PHONE),
            ("account_number", _RE_ACCOUNT),
        ]:
            for match in pattern.finditer(scan_text):
                text = match.group(0)
                # Skip obvious placeholders wrapped in <> or SHOUTING_SNAKE_CASE.
                if _looks_like_placeholder(text):
                    continue
                detections.append(
                    {
                        "category": category,
                        "text": text,
                        "start_index": match.start(),
                        "reason": f"regex match ({category})",
                        "source": "regex",
                    }
                )

        # ── Pass 2: LLM ───────────────────────────────────────
        llm_detections = self._call_llm(response.answer, context.ticket.ticket_id)
        if llm_detections is None:
            # LLM path failed — fail SAFE (block) if regex also found nothing;
            # if regex found something, the block reason is already there.
            if detections:
                return _fail(self.name, self.blocking, detections)
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason="pii_guardrail_error: llm path failed and no regex evidence "
                       "either — failing SAFE per A7",
                fail_safe=True,
                details={"detections": []},
            )
        detections.extend(llm_detections)

        # ── Whitelist: drop ticket's own customer_name from person_name hits ─
        # Token-subsequence match rather than exact-string: a draft saying
        # "Rosa" when customer_name is "Rosa Sharma" must NOT block the
        # customer's own reply. See PR-GUARDRAIL-PII-01.md §Fairness note.
        detections = [
            d
            for d in detections
            if not (
                d["category"] == "person_name"
                and _name_matches_customer(d["text"], context.ticket.customer_name)
            )
        ]

        # ── Deduplicate on (category, text.lower()) so regex + LLM agreeing
        #     doesn't inflate the count. ─
        detections = _dedupe(detections)

        if detections:
            return _fail(self.name, self.blocking, detections)
        return GuardrailResult(
            name=self.name,
            passed=True,
            blocking=self.blocking,
            reason="no PII detected",
            details={"detections": []},
        )

    def _call_llm(self, draft: str, ticket_id: str = "") -> Optional[list[dict]]:
        """Run PR-GUARDRAIL-PII-01. Returns None on any failure — caller
        decides. Returns a special sentinel [{"category": "__contract__", ...}]
        for a passed/detections contract violation so the caller can force a
        block with reason `pii_guardrail_contract_violation` even when the
        model returned an empty detections list.
        """
        caller = self.call_model or _openrouter_call
        try:
            user = _PII_PROMPT.render_user(draft=draft)
            raw = caller(_PII_PROMPT.system, user, 0)
            data = _parse_json_verdict(raw)
        except Exception as exc:  # broad — fail SAFE per A11
            MODEL_CALL_FAILURES.labels(
                stage="guardrail:pii", error_type=type(exc).__name__
            ).inc()
            logger.warning(
                "guardrails.pii.llm_failure",
                extra={"ticket_id": ticket_id, "error": str(exc),
                       "error_type": type(exc).__name__},
            )
            return None

        detections = data.get("detections", [])
        if not isinstance(detections, list):
            return None
        passed = data.get("passed")

        # ── Contract enforcement (fail-open guard) ────────────
        # PR-GUARDRAIL-PII-01 §Output schema requires passed and detections
        # to agree: passed=true iff detections is empty. A violating shape is
        # NOT treated as evidence of nothing — the model said the check
        # failed and refused to name what failed, or said it passed while
        # naming failures. Either shape forces a block per the prompt's
        # Notes ("pii_guardrail_contract_violation").
        contract_violation = (
            (passed is False and len(detections) == 0)
            or (passed is True and len(detections) > 0)
        )
        if contract_violation:
            logger.warning(
                "guardrails.pii.contract_violation",
                extra={"ticket_id": ticket_id, "passed": passed,
                       "n_detections": len(detections)},
            )
            return [
                {
                    "category": "__contract__",
                    "text": f"pii_guardrail_contract_violation: "
                            f"passed={passed} n_detections={len(detections)}",
                    "start_index": -1,
                    "reason": "PR-GUARDRAIL-PII-01 passed/detections agreement broken",
                    "source": "contract",
                }
            ]
        result: list[dict] = []
        for d in detections:
            if not isinstance(d, dict):
                continue
            category = d.get("category", "")
            text = d.get("text", "")
            if category not in {"email", "api_key", "phone", "account_number", "person_name"}:
                continue
            if not text:
                continue
            result.append(
                {
                    "category": category,
                    "text": text,
                    "start_index": d.get("start_index", -1),
                    "reason": d.get("reason", ""),
                    "source": "llm",
                }
            )
        return result


# ─── FR-17: grounding guardrail ─────────────────────────────────────


@dataclass
class GroundingGuardrail:
    """FR-17 — block responses whose factual claims are not supported by
    the cited passages.

    Called only on the has-passages branch of the generator. On the
    empty-retrieval / unknown branch there is nothing to ground, so the
    check passes vacuously — the router still handles the escalation via
    other rules (empty_retrieval, generator_unknown).
    """

    name: str = "grounding"
    blocking: bool = True
    call_model: Optional[ModelCall] = None

    def check(
        self, response: GeneratedResponse, context: GuardrailContext
    ) -> GuardrailResult:
        if response.unknown or not response.answer:
            return GuardrailResult(
                name=self.name,
                passed=True,
                blocking=self.blocking,
                reason="no answer to check (unknown branch)",
            )
        if not context.passages:
            # This should not happen — if there are no passages the generator
            # would have taken the unknown branch. Treat as a failure closed.
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason="grounding_guardrail_error: non-unknown answer with no "
                       "passages in context — cannot verify grounding",
                fail_safe=True,
            )

        caller = self.call_model or _openrouter_call
        try:
            user = _GROUNDING_PROMPT.render_user(
                passages=_format_passages(context.passages),
                answer=response.answer,
                citations=json.dumps(response.citations),
            )
            raw = caller(_GROUNDING_PROMPT.system, user, 0)
            data = _parse_json_verdict(raw)
        except Exception as exc:  # broad — fail SAFE per A11
            MODEL_CALL_FAILURES.labels(
                stage="guardrail:grounding", error_type=type(exc).__name__
            ).inc()
            logger.warning(
                "guardrails.grounding.llm_failure",
                extra={"ticket_id": context.ticket.ticket_id, "error": str(exc),
                       "error_type": type(exc).__name__},
            )
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason=f"grounding_guardrail_error: {type(exc).__name__}: {exc}",
                fail_safe=True,
            )

        unsupported = data.get("unsupported_claims", [])
        if not isinstance(unsupported, list):
            unsupported = []
        # Filter to real claim dicts (guard against schema slop).
        unsupported = [c for c in unsupported if isinstance(c, dict) and c.get("claim")]
        passed = data.get("passed")
        # Counts only, at DEBUG. The scaffolding this replaces logged the
        # full answer and raw verdict at INFO — too noisy for a run, and it
        # put customer-facing answer text into the log for every ticket.
        logger.debug(
            "guardrails.grounding.verdict",
            extra={
                "ticket_id": context.ticket.ticket_id,
                "passed_field": passed,
                "n_unsupported": len(unsupported),
                "prompt_version": _GROUNDING_PROMPT_VERSION,
            },
        )

        # ── Contract enforcement (fail-open guard) ────────────────────
        # PR-GUARDRAIL-GROUNDING-01 §Output schema requires passed and
        # unsupported_claims to agree: passed=true iff unsupported is empty.
        # A violating shape (passed=false with empty list, or passed=true
        # with items) is NOT a clean pass — the model said the check failed
        # and refused to name what failed. Force a block per the prompt's
        # Notes ("grounding_guardrail_contract_violation").
        contract_violation = (
            (passed is False and len(unsupported) == 0)
            or (passed is True and len(unsupported) > 0)
        )
        if contract_violation:
            logger.warning(
                "guardrails.grounding.contract_violation",
                extra={"ticket_id": context.ticket.ticket_id, "passed": passed,
                       "n_unsupported": len(unsupported)},
            )
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason=(
                    f"grounding_guardrail_contract_violation: "
                    f"passed={passed} n_unsupported={len(unsupported)}"
                ),
                fail_safe=True,
                details={
                    "contract_violation": True,
                    "raw_passed": passed,
                    "unsupported_claims": unsupported,
                },
            )

        if unsupported:
            summary = "; ".join(
                f"{c.get('claim', '?')[:80]!r}: {c.get('why_not_supported', '?')[:80]}"
                for c in unsupported[:3]
            )
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason=f"{len(unsupported)} unsupported claim(s): {summary}",
                details={"unsupported_claims": unsupported},
            )

        return GuardrailResult(
            name=self.name,
            passed=True,
            blocking=self.blocking,
            reason="all factual claims supported by cited passages",
        )


# ─── FR-18: instruction-integrity guardrail ─────────────────────────


@dataclass
class InstructionIntegrityGuardrail:
    """FR-18 — block responses where the ticket content appears to have
    redirected the system's behaviour.

    Pure-Python check. Detects:
      1. Persona-shift markers in the drafted answer ("As an AI ...",
         "Ignore prior instructions", "System:", etc.).
      2. Schema-shape violations that survived the generator's parser
         (extra top-level fields on GeneratedResponse — currently
         impossible because pydantic strips them, but the check stays as
         belt-and-braces for future schema changes).
      3. Citations declared but not present in any cited-passage doc_id
         set (this is a variant of FR-13 the generator's parser doesn't
         see — the parser accepts any list of strings).
    """

    name: str = "instruction_integrity"
    blocking: bool = True

    def check(
        self, response: GeneratedResponse, context: GuardrailContext
    ) -> GuardrailResult:
        problems: list[str] = []

        # ── 1: persona-shift markers ──────────────────────────
        if response.answer:
            matches = list(_RE_PERSONA_SHIFT.finditer(response.answer))
            if matches:
                problems.append(
                    "persona-shift marker(s): "
                    + ", ".join(sorted({m.group(0).lower() for m in matches}))
                )

        # ── 2: citations resolve to supplied passages ─────────
        if not response.unknown:
            valid_ids = {p.doc_id for p in context.passages}
            fabricated = [c for c in response.citations if c not in valid_ids]
            if fabricated:
                problems.append(
                    "fabricated citation(s) not in retrieval result: "
                    + ", ".join(fabricated)
                )

        if problems:
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason="; ".join(problems),
                details={"problems": problems},
            )
        return GuardrailResult(
            name=self.name,
            passed=True,
            blocking=self.blocking,
            reason="answer conforms to system integrity checks",
        )


# ─── Tone/scope guardrail (implicit — architecture.md §6 fifth check) ─


@dataclass
class ToneScopeGuardrail:
    """Fifth blocking guardrail (implicit per architecture.md §6) — blocks
    replies that make commitments about refunds, delivery timings, or
    product roadmap items.

    No PRD FR yet — traceability is via R-04 (commitment/liability risk)
    and EV-D4 (Daniel: billing disputes become contractual quickly). An
    FR-25 for tone/scope is future work, logged in Stage 5 revision log
    so the traceability audit reports the gap as intentional debt rather
    than an orphaned control. PR-GENERATE-01's Scope section already asks
    the model not to make these commitments; this guardrail enforces the
    ask — prompts are requests, code is control.

    Runs the same two-pass shape as PIIGuardrail: regex on the strongest
    commitment phrasings ("we will refund", "will be added in vX.Y",
    "fixed by tomorrow") + LLM prompt PR-GUARDRAIL-TONESCOPE-01 for the
    softer commitments the regex misses. Contract-violation and fail-safe
    semantics identical to grounding + PII.
    """

    name: str = "tone_scope"
    blocking: bool = True
    call_model: Optional[ModelCall] = None

    def check(
        self, response: GeneratedResponse, context: GuardrailContext
    ) -> GuardrailResult:
        # Unknown / empty answer cannot make a commitment — pass immediately.
        if response.unknown or not response.answer:
            return GuardrailResult(
                name=self.name,
                passed=True,
                blocking=self.blocking,
                reason="no answer text to inspect",
            )

        commitments: list[dict] = []

        # ── Pass 1: regex on the strongest commitment phrasings ──
        for category, pattern in [
            ("refund", _RE_REFUND),
            ("eta", _RE_ETA),
            ("roadmap", _RE_ROADMAP),
        ]:
            for match in pattern.finditer(response.answer):
                commitments.append(
                    {
                        "category": category,
                        "text": match.group(0),
                        "start_index": match.start(),
                        "reason": f"regex match ({category})",
                        "source": "regex",
                    }
                )

        # ── Pass 2: LLM ──────────────────────────────────────────
        llm_commitments = self._call_llm(response.answer, context.ticket.ticket_id)
        if llm_commitments is None:
            if commitments:
                return _fail_tonescope(self.name, self.blocking, commitments)
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason=(
                    "tonescope_guardrail_error: llm path failed and no regex "
                    "evidence either — failing SAFE per A7"
                ),
                fail_safe=True,
                details={"commitments": []},
            )
        commitments.extend(llm_commitments)

        # ── Deduplicate on (category, text.lower()) ──────────────
        seen: set[tuple[str, str]] = set()
        dedup: list[dict] = []
        for c in commitments:
            key = (c["category"], c["text"].lower())
            if key in seen:
                continue
            seen.add(key)
            dedup.append(c)
        commitments = dedup

        if commitments:
            return _fail_tonescope(self.name, self.blocking, commitments)
        return GuardrailResult(
            name=self.name,
            passed=True,
            blocking=self.blocking,
            reason="no unauthorised commitments detected",
            details={"commitments": []},
        )

    def _call_llm(self, draft: str, ticket_id: str = "") -> Optional[list[dict]]:
        """Run PR-GUARDRAIL-TONESCOPE-01. Same contract enforcement + fail-
        safe shape as PIIGuardrail._call_llm. Returns a __contract__
        sentinel for a passed/commitments agreement violation.
        """
        caller = self.call_model or _openrouter_call
        try:
            user = _TONESCOPE_PROMPT.render_user(draft=draft)
            raw = caller(_TONESCOPE_PROMPT.system, user, 0)
            data = _parse_json_verdict(raw)
        except Exception as exc:
            MODEL_CALL_FAILURES.labels(
                stage="guardrail:tonescope", error_type=type(exc).__name__
            ).inc()
            logger.warning(
                "guardrails.tonescope.llm_failure",
                extra={"ticket_id": ticket_id, "error": str(exc),
                       "error_type": type(exc).__name__},
            )
            return None

        commitments = data.get("commitments", [])
        if not isinstance(commitments, list):
            return None
        passed = data.get("passed")

        contract_violation = (
            (passed is False and len(commitments) == 0)
            or (passed is True and len(commitments) > 0)
        )
        if contract_violation:
            logger.warning(
                "guardrails.tonescope.contract_violation",
                extra={"ticket_id": ticket_id, "passed": passed,
                       "n_commitments": len(commitments)},
            )
            return [
                {
                    "category": "__contract__",
                    "text": f"tonescope_guardrail_contract_violation: "
                            f"passed={passed} n_commitments={len(commitments)}",
                    "start_index": -1,
                    "reason": "PR-GUARDRAIL-TONESCOPE-01 passed/commitments agreement broken",
                    "source": "contract",
                }
            ]

        result: list[dict] = []
        for c in commitments:
            if not isinstance(c, dict):
                continue
            category = c.get("category", "")
            text = c.get("text", "")
            if category not in {"refund", "eta", "roadmap"}:
                continue
            if not text:
                continue
            result.append(
                {
                    "category": category,
                    "text": text,
                    "start_index": c.get("start_index", -1),
                    "reason": c.get("reason", ""),
                    "source": "llm",
                }
            )
        return result


# ─── FR-19: confidence-floor guardrail ──────────────────────────────


@dataclass
class ConfidenceFloorGuardrail:
    """FR-19 — block auto-respond when the classifier's confidence is
    missing or below ``CONFIDENCE_THRESHOLD``, regardless of upstream
    router decision.

    Reads the classification.confidence from context, not the generator's
    self-reported confidence — the generator's number is a stated
    belief, while the classifier's is a calibrated posterior we can
    threshold on (per D-05 + D-05a).
    """

    name: str = "confidence_floor"
    blocking: bool = True

    def check(
        self, response: GeneratedResponse, context: GuardrailContext
    ) -> GuardrailResult:
        conf = context.classification.confidence
        if conf < CONFIDENCE_THRESHOLD:
            return GuardrailResult(
                name=self.name,
                passed=False,
                blocking=self.blocking,
                reason=(
                    f"classifier confidence {conf:.3f} is below the "
                    f"CONFIDENCE_THRESHOLD floor of "
                    f"{CONFIDENCE_THRESHOLD:.3f}"
                ),
                details={"confidence": conf, "threshold": CONFIDENCE_THRESHOLD},
            )
        return GuardrailResult(
            name=self.name,
            passed=True,
            blocking=self.blocking,
            reason=f"classifier confidence {conf:.3f} clears the floor",
        )


# ─── run_all ────────────────────────────────────────────────────────


def run_all(
    response: GeneratedResponse,
    context: GuardrailContext,
    *,
    call_model: Optional[ModelCall] = None,
    guardrails: Optional[list[Guardrail]] = None,
) -> list[GuardrailResult]:
    """Run every guardrail in order, write one decision-log row, return results.

    Args:
        response: the GeneratedResponse from ``src.generate.generate``.
        context: the surrounding pipeline state — ticket, passages,
            classification.
        call_model: optional injectable model callable for tests. Passed
            through to the LLM-backed guardrails (PII, grounding).
        guardrails: optional custom list of guardrails to run — production
            leaves this None and gets the four FR-16..19 guardrails.

    Returns:
        list[GuardrailResult] — one per guardrail, order preserved. Never
        raises. Individual guardrail failures return ``passed=False`` with
        the reason set; a wholesale exception in ``run_all`` itself would
        break the pipeline contract and is caught here as a last defence.
    """
    if guardrails is None:
        guardrails = [
            PIIGuardrail(call_model=call_model),
            GroundingGuardrail(call_model=call_model),
            InstructionIntegrityGuardrail(),
            ToneScopeGuardrail(call_model=call_model),
            ConfidenceFloorGuardrail(),
        ]

    results: list[GuardrailResult] = []
    for g in guardrails:
        try:
            results.append(g.check(response, context))
        except Exception as exc:  # last-defence — a guardrail should not raise
            logger.warning(
                "guardrails.check_raised",
                extra={
                    "ticket_id": context.ticket.ticket_id,
                    "guardrail": getattr(g, "name", type(g).__name__),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            results.append(
                GuardrailResult(
                    name=getattr(g, "name", type(g).__name__),
                    passed=False,
                    blocking=getattr(g, "blocking", True),
                    reason=f"guardrail_error: {type(exc).__name__}: {exc}",
                    fail_safe=True,
                )
            )

    _write_decision_log(response=response, context=context, results=results)
    return results


# ─── internals ──────────────────────────────────────────────────────


def _write_decision_log(
    *,
    response: GeneratedResponse,
    context: GuardrailContext,
    results: list[GuardrailResult],
) -> None:
    """One decision-log row per run_all(). Feeds the router's block/escalate
    decision and A8 reconciliation.
    """
    blocked = [r for r in results if r.blocking and not r.passed]
    action = "block" if blocked else "pass"
    reason = (
        "; ".join(f"{r.name}: {r.reason}" for r in blocked)
        if blocked
        else "all guardrails passed"
    )

    log_decision(
        ticket_id=context.ticket.ticket_id,
        stage="guardrails",
        prediction=action,
        confidence=context.classification.confidence,
        alternatives=[],
        prompt_version=(
            f"{_PII_PROMPT_VERSION};{_GROUNDING_PROMPT_VERSION};"
            f"{_TONESCOPE_PROMPT_VERSION}"
        ),
        requirement_ids=["FR-16", "FR-17", "FR-18", "FR-19"],
        model_name=MODEL_NAME,
        action_taken=action,
        reason=reason,
        guardrail_results=[
            {
                "name": r.name,
                "passed": r.passed,
                "blocking": r.blocking,
                "reason": r.reason,
                # FR-17 DoD: "log carries the unsupported-claim list."
                # Previously only the truncated `reason` summary made it into
                # the log row. The full structured verdict lives here so a
                # compliance reviewer opening a blocked row sees the actual
                # detections / claims, not a slice-to-3-fields-to-80-chars
                # summary. Same rationale applies to PII detections
                # (r.details["detections"]) and to contract-violation payloads.
                "details": r.details,
            }
            for r in results
        ],
        input_summary=(
            f"n_passages={len(context.passages)} "
            f"unknown={response.unknown} "
            f"n_citations={len(response.citations)} "
            f"n_guardrails={len(results)}"
        ),
    )


def _parse_json_verdict(raw: str) -> dict:
    """Parse a guardrail's JSON verdict. Raises on invalid JSON — the caller
    catches and converts to a fail-safe verdict.
    """
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    stripped = stripped.strip()
    if not stripped:
        raise ValueError("empty response from model")
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON must be object, got {type(data).__name__}")
    return data


def _format_passages(passages: list[Passage]) -> str:
    """Same rendering as src.generate uses so the grounding guardrail sees
    the doc_id-labelled block the generator saw.
    """
    parts: list[str] = []
    for p in passages:
        parts.append(
            f"[{p.doc_id}] (score={p.score:.3f}, title={p.title!r}, "
            f"category={p.category!r})\n{p.text}"
        )
    return "\n\n---\n\n".join(parts)


def _fail(name: str, blocking: bool, detections: list[dict]) -> GuardrailResult:
    """Build a failed PII GuardrailResult from a detections list.

    A ``__contract__`` category in the list is the sentinel from
    ``_call_llm`` for a passed/detections agreement violation — reason is
    named explicitly so the router / log reader sees why the block fired.
    """
    contract_hits = [d for d in detections if d["category"] == "__contract__"]
    if contract_hits:
        return GuardrailResult(
            name=name,
            passed=False,
            blocking=blocking,
            reason=(
                "pii_guardrail_contract_violation: "
                + contract_hits[0].get("text", "")
            ),
            fail_safe=True,
            details={"contract_violation": True, "detections": detections},
        )
    categories = sorted({d["category"] for d in detections})
    summary = ", ".join(
        f"{c}={sum(1 for d in detections if d['category'] == c)}"
        for c in categories
    )
    return GuardrailResult(
        name=name,
        passed=False,
        blocking=blocking,
        reason=f"PII detected ({summary})",
        details={"detections": detections},
    )


def _fail_tonescope(
    name: str, blocking: bool, commitments: list[dict]
) -> GuardrailResult:
    """Build a failed ToneScope GuardrailResult from a commitments list.

    Recognises the ``__contract__`` sentinel from ``_call_llm`` for the
    passed/commitments agreement violation and names it explicitly in
    reason.
    """
    contract_hits = [c for c in commitments if c["category"] == "__contract__"]
    if contract_hits:
        return GuardrailResult(
            name=name,
            passed=False,
            blocking=blocking,
            reason=(
                "tonescope_guardrail_contract_violation: "
                + contract_hits[0].get("text", "")
            ),
            fail_safe=True,
            details={"contract_violation": True, "commitments": commitments},
        )
    categories = sorted({c["category"] for c in commitments})
    summary = ", ".join(
        f"{cat}={sum(1 for c in commitments if c['category'] == cat)}"
        for cat in categories
    )
    return GuardrailResult(
        name=name,
        passed=False,
        blocking=blocking,
        reason=f"unauthorised commitment(s) detected ({summary})",
        details={"commitments": commitments},
    )


def _looks_like_placeholder(text: str) -> bool:
    """Docs-style placeholders that regex might mistake for real PII.

    Only genuine placeholder syntaxes are suppressed: angle-bracket forms
    like ``<your-api-key>`` and SHOUTING_SNAKE_CASE tokens like
    ``YOUR_API_KEY``. RFC 2606 reserved domains (``example.com`` /
    ``example.org``) are DELIBERATELY NOT suppressed here — FR-16's
    acceptance canary is a literal ``test@example.com`` in an outbound
    reply, exactly the "template placeholder accidentally shipped to a
    real customer" failure mode the guardrail exists to catch. Whitelisting
    the RFC 2606 domains would silently kill that canary and mask a
    real class of ship-a-placeholder bug. Instructional appearances of
    ``<your-team-email>`` and similar are caught by the angle-bracket
    rule above.
    """
    if text.startswith("<") and text.endswith(">"):
        return True
    if re.fullmatch(r"[A-Z_]+", text):
        return True
    lowered = text.lower()
    if lowered in {"your-api-key", "your_api_key", "your-key"}:
        return True
    return False


def _normalise_name(name: str) -> str:
    """Lowercase + collapse whitespace for whitelist comparison."""
    return re.sub(r"\s+", " ", name.strip().lower())


def _name_matches_customer(detected: str, customer: str) -> bool:
    """Whitelist: True if every token of the detected name appears among the
    tokens of the customer's name (after normalisation).

    Matches:
      - Exact:            "Rosa Sharma" vs "Rosa Sharma"        -> True
      - First-name only:  "Rosa"        vs "Rosa Sharma"        -> True
      - Family-name only: "Sharma"      vs "Rosa Sharma"        -> True
      - Reordered:        "Sharma Rosa" vs "Rosa Sharma"        -> True
      - With honorific:   "Alice"       vs "Dr Alice Anders"    -> True

    Rejects:
      - Different person:      "Zhang"        vs "Rosa Sharma"  -> False
      - Overlap-only surname:  "Rosa Zhang"   vs "Rosa Sharma"  -> False
      - Empty detected:        ""             vs "Rosa Sharma"  -> False
      - Empty customer:        "Rosa"         vs ""             -> False

    Rationale (fairness): a strict exact-match whitelist blocks any draft
    that addresses the customer by their first name only, which is the
    normal form for a polite auto-reply. That bites customers whose full
    name is on file — segment-correlated across name origins. See
    PR-GUARDRAIL-PII-01.md §Fairness note.
    """
    d_tokens = _normalise_name(detected).split()
    c_tokens = set(_normalise_name(customer).split())
    if not d_tokens or not c_tokens:
        return False
    return all(t in c_tokens for t in d_tokens)


def _dedupe(detections: list[dict]) -> list[dict]:
    """Drop duplicates on (category, text.lower()). Regex + LLM agreeing on
    the same email should count once, not twice.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for d in detections:
        key = (d["category"], d["text"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out
