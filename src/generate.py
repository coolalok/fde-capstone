"""generate.py — produce a grounded reply to a support ticket, with citations.

Satisfies: FR-13 (JSON schema answer + citations + confidence + unknown),
           FR-14 (unknown=true rather than fabricate when passages cannot
                  support an answer),
           FR-15 (prompt-injection delimiters + guarded schema).
Uses prompts: PR-GENERATE-01 (has passages) and PR-GENERATE-02 (empty retrieval).
Writes:       one row to the decision log per call.

Design decisions worth reading:

- **Two branches, two prompts, one function.** Empty retrieval routes to
  PR-GENERATE-02 (the honest "I don't know" reply). Non-empty retrieval routes
  to PR-GENERATE-01 (grounded answer + Self-RAG groundedness check). The
  branch is chosen by the caller-supplied ``passages`` list — an empty list
  means "no passages crossed the retrieval threshold" (FR-07), which is a
  first-class answer, not an error.

- **Self-RAG per D-06, retry cap 1.** After the generator's first draft is
  parsed, a groundedness critic checks it. If every citation resolves to a
  supplied passage and the response is structurally consistent, we return.
  Otherwise we retry once with the critic's feedback prepended, capped at 1.
  A second failure escalates as ``unknown=true`` with ``error`` populated —
  the router treats that as a hard-escalate signal (per D-06 / EV-M5).

- **Pluggable model call and pluggable critic.** ``call_model`` is a
  ``(system, user, seed) -> str`` callable so tests never touch OpenRouter.
  ``critic`` is a ``(response, passages) -> CritiqueResult`` callable — the
  default is the structural check below; B-13 (PR-GUARDRAIL-GROUNDING-01)
  will slot a semantic critic in via the same seam.

- **Never raises.** Every failure (network, JSON parse, schema violation,
  citation resolution, critic exception) is caught and converted to
  ``GeneratedResponse.unknown_fallback(...)``. A11 across the pipeline.

- **FR-15 injection posture.** The user template already wraps the ticket in
  ``<<TICKET_START>>`` / ``<<TICKET_END>>`` markers. The prompt loader's
  single-pass substitution (Bug 4 fix) means a customer body containing
  literal ``{{passages}}`` cannot splice into a system region. After
  parsing, any citation NOT in the supplied ``doc_id`` set is dropped and
  the response is retried — an injection attempt to fabricate a citation
  fails closed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

from src import usage
from src.config import (
    accepts_seed,
    GENERATE_MAX_RETRIES,
    GENERATE_TEMPERATURE,
    MODEL_MAX_RETRIES,
    MODEL_NAME,
    MODEL_TIMEOUT_SECONDS,
    MODEL_API_KEY,
    MODEL_BASE_URL,
    require_key,
)
from src.logging_store import log_decision
from src import model_cache
from src import rate_limit
from src.metrics import MODEL_CALL_FAILURES
from src.prompt_loader import load_prompt
from src.schema import GeneratedResponse, Passage, Ticket

logger = logging.getLogger(__name__)

# Load both prompts at import so their versions are fixed for the process
# lifetime. If either file is missing or malformed, we raise at import time —
# this is a build-time programming error, not a runtime A11 case.
_PROMPT_01 = load_prompt("PR-GENERATE-01")
_PROMPT_02 = load_prompt("PR-GENERATE-02")
_PROMPT_01_VERSION = f"PR-GENERATE-01@{_PROMPT_01.version}"
_PROMPT_02_VERSION = f"PR-GENERATE-02@{_PROMPT_02.version}"


# ─── model call and critic seams ─────────────────────────────────────

# (system_prompt, user_prompt, seed) -> raw model response as a string.
ModelCall = Callable[[str, str, int], str]


@dataclass
class CritiqueResult:
    """Return type of the groundedness critic.

    Attributes:
      passed: True if the response is grounded and structurally valid.
      unsupported_claims: human-readable list of what went wrong. Prepended to
        the retry_feedback placeholder on the next attempt when passed=False.
    """

    passed: bool
    unsupported_claims: list[str]


Critic = Callable[[GeneratedResponse, list[Passage]], CritiqueResult]


def _openrouter_call(system: str, user: str, seed: int = 0) -> str:
    """Call OpenRouter via the OpenAI SDK. Raises on any I/O or auth failure.

    The caller (generate()) catches whatever this raises and converts it into
    an unknown_fallback with ``error`` set.
    """
    from openai import OpenAI  # imported lazily so unit tests don't need the pkg

    # Cache first, before the key check and the client: a cached reply costs
    # no quota, and a replay of a previous run works with no provider at all.
    cache_key = model_cache.key(model=MODEL_NAME, system=system, user=user,
                                seed=seed, temperature=GENERATE_TEMPERATURE)
    cached = model_cache.get(cache_key, stage="generation")
    if cached is not None:
        return cached

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
    completion = rate_limit.guarded(lambda: client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=GENERATE_TEMPERATURE,
        # Only where the provider accepts it; see config.accepts_seed.
        **({"seed": seed} if accepts_seed(MODEL_BASE_URL) else {}),
        response_format={"type": "json_object"},
    ))
    usage.record("generation", MODEL_NAME, getattr(completion, "usage", None))
    # OpenRouter can answer 200 with choices=None when the upstream provider
    # errors. Subscripting that raised "TypeError: 'NoneType' object is not
    # subscriptable" from inside the caller's broad except, which recorded the
    # symptom rather than the cause. Raise the cause instead — the fail-safe
    # cascade is unchanged, but the reason string and MODEL_CALL_FAILURES say
    # what actually happened.
    if not getattr(completion, "choices", None):
        raise ValueError(f"provider returned no choices (model={MODEL_NAME})")
    choice = completion.choices[0]
    # A reply cut off by the provider's output limit is not valid JSON, and
    # the parser then reports "Unterminated string", which looks like a
    # formatting fault in the prompt. PR-GENERATE-01 v3.0 failed that way on
    # DEV-0012 in the 14 Sep A/B smoke run, and nothing recorded why the model
    # stopped. Name the cause instead.
    if getattr(choice, "finish_reason", None) == "length":
        raise ValueError(
            f"model output cut off at the provider's length limit "
            f"(finish_reason=length, model={MODEL_NAME})"
        )
    content = choice.message.content or ""
    model_cache.put(cache_key, content, stage="generation", model=MODEL_NAME,
                    usage=getattr(completion, "usage", None))
    return content


def _structural_critic(
    response: GeneratedResponse, passages: list[Passage]
) -> CritiqueResult:
    """Default groundedness check — structural only.

    Semantic groundedness (does the answer text actually reflect what the
    passages say?) is B-13's territory (PR-GUARDRAIL-GROUNDING-01). This
    structural check is what B-11 needs to close the Self-RAG loop: catch
    the failure modes that the model can produce on its own (fabricated
    citations, contradictory unknown flag, missing citations for a
    non-unknown answer). A B-13 semantic critic can be composed on top.

    Checks:
      1. If unknown=true: answer must be empty AND citations must be empty.
      2. If unknown=false: answer must be non-empty AND citations non-empty.
      3. Every citation must be a doc_id present in the supplied passages.
    """
    valid_ids = {p.doc_id for p in passages}
    problems: list[str] = []

    if response.unknown:
        if response.answer.strip():
            problems.append(
                "answer must be empty when unknown=true (FR-14 contract)"
            )
        if response.citations:
            problems.append(
                "citations must be empty when unknown=true (FR-14 contract)"
            )
    else:
        if not response.answer.strip():
            problems.append(
                "answer must be non-empty when unknown=false (FR-13 contract)"
            )
        if not response.citations:
            problems.append(
                "citations must be non-empty when unknown=false (FR-13 contract)"
            )
        # Every citation must resolve to a supplied passage.
        for cite in response.citations:
            if cite not in valid_ids:
                problems.append(
                    f"citation {cite!r} does not resolve to any retrieved "
                    f"passage doc_id (fabricated or hallucinated)"
                )

    return CritiqueResult(passed=not problems, unsupported_claims=problems)


# ─── public API ──────────────────────────────────────────────────────


def generate(
    ticket: Ticket,
    passages: list[Passage],
    *,
    ticket_id: str,
    seed: int = 0,
    call_model: Optional[ModelCall] = None,
    critic: Optional[Critic] = None,
) -> GeneratedResponse:
    """Draft a reply to a ticket. See FR-13, FR-14, FR-15 and D-06.

    Args:
        ticket: the normalised Ticket (channel/subject/body — the customer
            data the model sees).
        passages: retrieved passages ordered by score descending. An empty
            list means retrieval returned nothing above RETRIEVAL_THRESHOLD;
            we route to PR-GENERATE-02 (I-don't-know) rather than PR-GENERATE-01.
        ticket_id: for the decision log. Required (keyword-only, no default)
            so an A8 reconciliation row is never silently written to "".
        seed: deterministic seed for the model call (default 0).
        call_model: optional injectable model callable; production leaves
            this None and uses OpenRouter.
        critic: optional injectable groundedness critic; production leaves
            this None and uses the structural check above. B-13 will pass a
            semantic critic in via this seam.

    Returns:
        A GeneratedResponse. On any failure — network error, JSON parse
        failure, schema violation, retry exhaustion, or critic exception —
        returns ``GeneratedResponse.unknown_fallback(error=...)``. Never
        raises out of the pipeline.
    """
    caller = call_model or _openrouter_call
    check = critic or _structural_critic

    # ── Empty-retrieval branch: PR-GENERATE-02 owns the "I don't know" reply
    if not passages:
        response = _run_empty_branch(ticket, caller, seed)
        _write_decision_log(
            response=response,
            ticket=ticket,
            ticket_id=ticket_id,
            passages=passages,
            prompt_version=_PROMPT_02_VERSION,
        )
        return response

    # ── Grounded-answer branch: PR-GENERATE-01 + Self-RAG loop
    response = _run_grounded_branch(ticket, passages, caller, check, seed)
    _write_decision_log(
        response=response,
        ticket=ticket,
        ticket_id=ticket_id,
        passages=passages,
        prompt_version=_PROMPT_01_VERSION,
    )
    return response


# ─── internals ───────────────────────────────────────────────────────


def _run_empty_branch(
    ticket: Ticket, caller: ModelCall, seed: int
) -> GeneratedResponse:
    """Ask PR-GENERATE-02 for the honest "I don't know" reply.

    PR-GENERATE-02's contract is fixed: it MUST return unknown=true with an
    empty answer and empty citations. If the model deviates, we force the
    unknown_fallback rather than let a fabricated citation through.
    """
    raw: Optional[str] = None
    try:
        user_prompt = _PROMPT_02.render_user(
            channel=ticket.channel,
            subject=ticket.subject,
            body=ticket.body,
        )
        raw = caller(_PROMPT_02.system, user_prompt, seed)
        response = _parse_response(raw)
    except Exception as exc:  # broad on purpose — A11
        MODEL_CALL_FAILURES.labels(
            stage="generation", error_type=type(exc).__name__
        ).inc()
        logger.warning(
            "generate.empty_branch.failure",
            extra={
                "ticket_id": ticket.ticket_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
                # The model's text, when there was any: without it a parse
                # failure cannot be told apart from a provider fault.
                "raw_response_head": raw[:500] if raw is not None else None,
            },
        )
        return GeneratedResponse.unknown_fallback(
            error=f"{type(exc).__name__}: {exc}"
        )

    # Enforce the empty-branch contract structurally — no citations can be
    # invented here because no passages were provided to cite.
    if not response.unknown or response.citations or response.answer.strip():
        logger.warning(
            "generate.empty_branch.contract_violation",
            extra={
                "ticket_id": ticket.ticket_id,
                "unknown": response.unknown,
                "n_citations": len(response.citations),
                "answer_len": len(response.answer),
            },
        )
        return GeneratedResponse.unknown_fallback(
            error="PR-GENERATE-02 contract violation: expected unknown=true "
            "with empty answer and citations",
        )
    return response


def _run_grounded_branch(
    ticket: Ticket,
    passages: list[Passage],
    caller: ModelCall,
    check: Critic,
    seed: int,
) -> GeneratedResponse:
    """Generate a grounded answer with a Self-RAG groundedness retry loop.

    Retry policy: at most ``GENERATE_MAX_RETRIES`` (default 1 per D-06) after
    the first attempt. On the retry, the critic's ``unsupported_claims`` are
    formatted and passed via the ``{{retry_feedback}}`` placeholder so the
    model can see what to fix.
    """
    passages_block = _format_passages(passages)
    retry_feedback = ""

    for attempt in range(GENERATE_MAX_RETRIES + 1):
        raw = None
        try:
            user_prompt = _PROMPT_01.render_user(
                passages=passages_block,
                retry_feedback=retry_feedback,
                channel=ticket.channel,
                subject=ticket.subject,
                body=ticket.body,
            )
            raw = caller(_PROMPT_01.system, user_prompt, seed + attempt)
            response = _parse_response(raw)
        except Exception as exc:  # broad on purpose — A11
            MODEL_CALL_FAILURES.labels(
                stage="generation", error_type=type(exc).__name__
            ).inc()
            logger.warning(
                "generate.grounded_branch.failure",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "attempt": attempt,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "raw_response_head": raw[:500] if raw is not None else None,
                },
            )
            return GeneratedResponse.unknown_fallback(
                error=f"{type(exc).__name__}: {exc}",
                retries=attempt,
            )

        # Groundedness critic — pluggable so B-13 can extend without changing
        # this file. Structural check by default.
        try:
            critique = check(response, passages)
        except Exception as exc:  # critic errors also fall back per A11
            MODEL_CALL_FAILURES.labels(
                stage="generation:critic", error_type=type(exc).__name__
            ).inc()
            logger.warning(
                "generate.critic.failure",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "attempt": attempt,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return GeneratedResponse.unknown_fallback(
                error=f"critic_failure: {type(exc).__name__}: {exc}",
                retries=attempt,
            )

        if critique.passed:
            response.retries = attempt
            return response

        if attempt >= GENERATE_MAX_RETRIES:
            # Retry cap reached with no grounded answer — escalate as unknown
            # (per D-06, EV-M5: rather nothing than wrong).
            logger.info(
                "generate.retry_exhausted",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "unsupported_claims": critique.unsupported_claims,
                    "attempts": attempt + 1,
                },
            )
            return GeneratedResponse.unknown_fallback(
                error=(
                    "self_rag_retry_exhausted: "
                    + "; ".join(critique.unsupported_claims)
                ),
                retries=attempt,
            )

        # Prepare feedback for the next attempt.
        retry_feedback = (
            "UNSUPPORTED CLAIMS FROM YOUR PREVIOUS DRAFT — remove or ground "
            "each of these:\n- " + "\n- ".join(critique.unsupported_claims)
        )

    # Unreachable — the loop returns on every branch.
    return GeneratedResponse.unknown_fallback(error="unreachable_loop_exit")


def _format_passages(passages: list[Passage]) -> str:
    """Render the retrieved passages for the {{passages}} placeholder.

    One block per passage, doc_id-labelled so citations are unambiguous.
    """
    parts: list[str] = []
    for p in passages:
        parts.append(
            f"[{p.doc_id}] (score={p.score:.3f}, title={p.title!r}, "
            f"category={p.category!r})\n{p.text}"
        )
    return "\n\n---\n\n".join(parts)


# One citation marker as the generator writes it inline, e.g. "[DOC-ACCT-001]".
# All 29 corpus doc_ids match this shape (checked against data/documentation.json).
_RE_MARKER = re.compile(r"\[DOC-[A-Z]+-\d+\]")
# A contiguous run of markers, optionally separated by spaces: "[A][A]", "[A] [B]".
_RE_MARKER_RUN = re.compile(r"(?:\[DOC-[A-Z]+-\d+\][ \t]*){2,}")


def _collapse_repeated_markers(answer: str) -> str:
    """Collapse a run of adjacent inline citation markers to its distinct members.

    Observed on DEV-0485: gpt-4o-mini emitted "...seven days.[DOC-ACCT-001]
    [DOC-ACCT-001]" — the same marker twice in a row. llama-3.1-8b does it too,
    so it is not a single-model artefact and is not fixable by swapping models.
    PR-GENERATE-01 says a marker sits after the sentence relying on it; two
    copies of one marker still means one source, so the duplicate carries no
    information and just reads as a defect to the customer.

    Only exact repeats inside one run are dropped. "[DOC-A][DOC-B]" is two
    genuine sources and is left alone, as is the same marker cited again later
    in the answer after intervening prose.
    """
    def _dedupe(match: "re.Match[str]") -> str:
        seen = dict.fromkeys(_RE_MARKER.findall(match.group(0)))
        trailing = " " if match.group(0).endswith((" ", "\t")) else ""
        return "".join(seen) + trailing

    return _RE_MARKER_RUN.sub(_dedupe, answer)


def strip_citation_markers(answer: str) -> str:
    """Remove inline [DOC-ID] markers from text that is about to reach a customer.

    PR-GENERATE-01 asks the model to put a marker after each sentence that
    relies on a passage, and the grounding guardrail uses them to tie a claim
    to the passage it came from. That is an INTERNAL mechanism. None of the
    200 senior-agent reference replies in data/ground_truth_responses.json
    contains one; they record sources in expected_doc_ids, exactly as our
    GeneratedResponse.citations does. Measured on the 13 Sep gate run, 15 of
    20 auto-sent replies carried at least one marker.

    So this is applied at the point of delivery, NOT at generation:

      - the generator still emits markers (the prompt is unchanged, and every
        measurement taken against that prompt stays valid);
      - the guardrails still see them, so grounding keeps its per-claim anchor;
      - the ESCALATION path keeps them too — a human reviewing a withheld
        draft benefits from seeing which article each claim came from;
      - only the customer-facing string has them removed.

    Whitespace is closed up so removal leaves no trace: a marker glued to a
    full stop ("...key.[DOC-A]") and one sitting mid-sentence ("...key [DOC-A]
    rotates...") both read correctly afterwards. citations is untouched and
    remains the machine-readable record of what was used.
    """
    if not answer:
        return answer
    # Consume any whitespace BEFORE the marker, so "key.[DOC-A] Next" and
    # "key. [DOC-A] Next" both become "key. Next" rather than leaving a
    # double space or a space before punctuation.
    stripped = re.sub(r"[ \t]*" + _RE_MARKER.pattern, "", answer)
    # A marker alone on a line can leave a blank line behind.
    stripped = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", stripped)
    return stripped.strip()


def _parse_response(raw: str) -> GeneratedResponse:
    """Parse and validate the model's JSON output. Raises on any invalidity.

    Structural validation only — the four required fields, right types, right
    ranges. Groundedness (citations resolve) is the critic's job, not the
    parser's.
    """
    # Strip ```json ... ``` fences some gateways add even under response_format.
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    stripped = stripped.strip()
    if not stripped:
        raise ValueError("empty response from model")

    data = json.loads(stripped)  # ValueError on malformed JSON

    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON must be an object, got {type(data).__name__}")

    # FR-13: exactly these four fields.
    answer = data.get("answer")
    citations = data.get("citations")
    confidence = data.get("confidence")
    unknown = data.get("unknown")

    if not isinstance(answer, str):
        raise ValueError(f"answer not string: {type(answer).__name__}")
    if not isinstance(citations, list) or not all(
        isinstance(c, str) for c in citations
    ):
        raise ValueError("citations must be a list of strings")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError(f"confidence not numeric: {type(confidence).__name__}")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence out of range: {confidence}")
    if not isinstance(unknown, bool):
        raise ValueError(f"unknown must be bool: {type(unknown).__name__}")

    return GeneratedResponse(
        answer=_collapse_repeated_markers(answer),
        # Dedupe, preserving order. Models emit the same doc_id repeatedly
        # and staple the markers together ('...[DOC-A][DOC-A]'), against
        # PR-GENERATE-01's rule that a marker sits after the sentence that
        # relies on it. Observed on llama-3.1-8b AND gpt-4o-mini, so it is
        # not a single-model artefact. citations is the SET of documents used.
        citations=list(dict.fromkeys(citations)),
        confidence=confidence,
        unknown=unknown,
        retries=0,
        error=None,
    )


def _write_decision_log(
    *,
    response: GeneratedResponse,
    ticket: Ticket,
    ticket_id: str,
    passages: list[Passage],
    prompt_version: str,
) -> None:
    """One decision-log row per call. FR-20."""
    action = "generated" if response.error is None else "fallback"
    if response.error is None and response.unknown:
        action = "unknown"

    decision_id = log_decision(
        ticket_id=ticket_id,
        stage="generation",
        prediction=(
            "unknown=true"
            if response.unknown
            else f"answer_len={len(response.answer)} citations={response.citations}"
        ),
        confidence=response.confidence,
        alternatives=[],
        prompt_version=prompt_version,
        requirement_ids=["FR-13", "FR-14", "FR-15"],
        model_name=MODEL_NAME,
        action_taken=action,
        reason=(
            response.error
            if response.error is not None
            else f"retries={response.retries} n_passages={len(passages)}"
        ),
        sources_used=[{"doc_id": p.doc_id, "score": p.score} for p in passages],
        input_summary=(
            f"channel={ticket.channel} "
            f"subject_len={len(ticket.subject)} body_len={len(ticket.body)} "
            f"n_passages={len(passages)}"
        ),
    )
    if decision_id is None:
        # Generation happened but was not recorded (FR-20 unmet for this
        # ticket). Same Bug 1 shape as classify.py — mark the response so
        # the router escalates rather than auto-responds.
        response.decision_logged = False
