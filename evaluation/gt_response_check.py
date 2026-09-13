"""Check generated answers against the pack's ground-truth response assertions.

data/ground_truth_responses.json carries 200 senior-agent-written reference
responses. Every field is honoured here, mapped onto the standard RAG
evaluation metrics (RAGAS) so the numbers mean what a reader expects:

  expected_doc_ids   -> context recall. Of the documents the ground truth says
                        are needed, how many did retrieval actually return.
  must_mention       -> the FALSE NEGATIVE side of factual correctness: facts
                        the reference contains that our answer omitted.
  must_not_claim     -> the FALSE POSITIVE side: assertions our answer made
                        that the ground truth forbids.
  reference_response -> answer similarity. Cosine between our answer and the
                        senior agent's reply, using the SAME local embedding
                        model the retriever uses (all-MiniLM-L6-v2).

  answer_correctness -> RAGAS's combination of the two:
                          F1 = TP / (TP + 0.5 * (FP + FN))
                          score = 0.75 * F1 + 0.25 * similarity
                        TP = must_mention facts present, FN = facts missing,
                        FP = prohibited claims made.

Before this, only must_mention and must_not_claim were read; expected_doc_ids
and reference_response were unused, and reference_response is the only
measurement of answer QUALITY (rather than answer safety) in the dataset.

This is a DETERMINISTIC eval: no LLM judge, so no rate limits, no capability
ceiling, no run-to-run variance. That matters because judge availability is the
current binding constraint (Bug 5), and an eval built on a judge would inherit
the problem it is meant to measure.

What it measures: how often the generator makes a claim the ground truth
forbids. That is NFR-01b territory — the "confidently wrong" failure the whole
project is built around (EV-M3) — and it is currently unmeasured.

Scope and honesty about it:
  - All 200 ground-truth tickets are DEV-set; zero overlap with validation. So
    this cannot score a B-21 validation run; it runs its own pass.
  - `must_not_claim` items are natural-language ("a refund has been issued"),
    not literal strings, so detection is by pattern. Two of the three reuse the
    tone/scope guardrail's already-tested regexes; the third gets one here.
  - Detection is therefore a LOWER BOUND on violations: a phrasing no pattern
    covers is counted as clean.
  - Guardrails are not run. We are measuring what the GENERATOR produces, not
    what the guardrail layer would have blocked.
  - Only 13 DISTINCT reference_response texts exist across the 200 tickets, and
    one content-free holding reply ("the relevant guidance in our documentation
    covers the likely causes") is the reference for 79 of them — all of which
    have an empty must_mention list. Scoring similarity against that would
    reward generic waffle, so those tickets are reported SEPARATELY and are
    excluded from the headline similarity and correctness figures. 121 tickets
    carry a specific reference answer; those are the meaningful denominator.

Usage:
    python -m evaluation.gt_response_check --limit 40 --output evaluation/results/gt
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from src.config import EMBEDDING_MODEL
from src.generate import generate, strip_citation_markers
from src.guardrails import _RE_ETA, _RE_REFUND
from src.ingest import normalise_any
from src.logging_config import configure_logging
from src.logging_store import new_run_id, set_run_id
from src.retrieve import retrieve

_ROOT = Path(__file__).parent.parent
GT_PATH = _ROOT / "data" / "ground_truth_responses.json"
TICKETS_PATH = _ROOT / "data" / "development_tickets.json"

# "the issue has been fixed on our side" — a claim about work WE have done.
# The other two prohibitions already have tested detectors in the tone/scope
# guardrail, so only this one is new.
_RE_FIXED_OUR_SIDE = re.compile(
    r"""
    \b(?:
        (?:we|our\ team|engineering)\ (?:have|has|'ve)\ (?:now\ )?
            (?:fixed|resolved|corrected|repaired|patched|deployed\ a\ fix)
      | (?:this|the\ issue|it)\ (?:has\ been|was|is\ now)\ (?:fixed|resolved|corrected)
      | (?:we|our\ team)\ (?:are|'re)\ (?:working\ on|investigating)\ (?:it|this|the\ issue)
      | (?:we|our\ team)\ (?:have|has|'ve)\ (?:checked|reviewed|looked\ at)
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

# "a refund has been issued" — PAST TENSE. The tone/scope guardrail's
# _RE_REFUND targets future COMMITMENTS ("we will refund", "a refund will be
# issued") because that is the liability risk it exists to stop. The ground
# truth prohibits something different: asserting a refund has ALREADY happened.
# _RE_REFUND does not match that — it does not even match the ground truth's
# own wording, "a refund has been issued" — so reusing it alone left this
# prohibition effectively unchecked and would have reported zero violations
# whatever the generator wrote.
_RE_REFUND_ISSUED = re.compile(
    r"""
    \b(?:
        (?:a|your|the)\s+(?:refund|credit|reimbursement)\s+
            (?:has\s+been|was|is)\s+
            (?:issued|processed|applied|actioned|credited|approved|on\s+its\s+way)
      | (?:we|our\s+team|i)\s+(?:have|has|'ve)\s+(?:now\s+)?
            (?:issued|processed|applied|actioned|approved)\s+
            (?:a|your|the)\s+(?:refund|credit|reimbursement)
      | (?:you\s+have|you've)\s+been\s+(?:refunded|reimbursed|credited)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _either(*patterns: re.Pattern) -> re.Pattern:
    """Combine detectors so a prohibition matches if ANY of them fires.

    Kept as a helper rather than one giant regex so each component stays
    independently readable and independently tested.
    """
    return re.compile("|".join(f"(?:{p.pattern})" for p in patterns),
                      re.VERBOSE | re.IGNORECASE)


# Maps each ground-truth prohibition to its detector.
# The refund prohibition needs BOTH: a reply promising a future refund and one
# asserting a past refund are each a violation of "a refund has been issued"
# as a claim the customer would act on.
CLAIM_DETECTORS = {
    "a refund has been issued": _either(_RE_REFUND_ISSUED, _RE_REFUND),
    "a specific delivery date for a fix": _RE_ETA,
    "the issue has been fixed on our side": _RE_FIXED_OUR_SIDE,
}


def check_answer(answer: str, must_not_claim: list[str],
                 must_mention: list[str]) -> dict:
    """Pure function so it is testable without a model call."""
    violations = [
        {"claim": claim, "matched": m.group(0)}
        for claim in must_not_claim
        if (pattern := CLAIM_DETECTORS.get(claim)) is not None
        and (m := pattern.search(answer)) is not None
    ]
    lowered = answer.lower()
    missing = [p for p in must_mention if p.lower() not in lowered]
    return {
        "violations": violations,
        "must_mention_total": len(must_mention),
        "must_mention_missing": missing,
        "undetectable_claims": [c for c in must_not_claim if c not in CLAIM_DETECTORS],
    }


# ── Reference-answer scoring (RAGAS answer_correctness) ─────────────────────

# RAGAS's default split between factual correctness and semantic similarity.
# Factual dominates on purpose: an answer that reads like the reference but
# omits the facts it was supposed to convey is not a correct answer.
_W_FACTUAL, _W_SIMILARITY = 0.75, 0.25

# The content-free holding reply used as the reference for 79 of 200 tickets.
# Identified by its opening rather than by exact match so a whitespace edit in
# the dataset does not silently reclassify 79 tickets as meaningful.
_BOILERPLATE_OPENING = (
    "Thank you for getting in touch, and apologies for the difficulty"
)


def is_boilerplate_reference(reference: str) -> bool:
    """True for the generic holding reply that carries no specific content.

    Those tickets all have an empty must_mention list, which is consistent:
    the dataset is not asserting any particular fact for them. Scoring
    similarity against such a reference measures politeness, not correctness.
    """
    return reference.strip().startswith(_BOILERPLATE_OPENING)


def context_recall(retrieved_doc_ids: list[str], expected: list[str]) -> float | None:
    """Fraction of the ground truth's expected documents that retrieval returned.

    The standard context-recall metric. Returns None when the ground truth
    names no expected document, so those tickets are excluded from the mean
    rather than counted as a perfect or a zero score.
    """
    if not expected:
        return None
    got = set(retrieved_doc_ids)
    return sum(1 for d in expected if d in got) / len(expected)


def answer_correctness(n_present: int, n_missing: int, n_prohibited: int,
                       similarity: float | None) -> float:
    """RAGAS answer correctness: 0.75 * F1 + 0.25 * semantic similarity.

    F1 = TP / (TP + 0.5 * (FP + FN)) with
      TP = must_mention facts the answer contains,
      FN = must_mention facts it omitted,
      FP = must_not_claim prohibitions it violated.

    When the ticket asserts no facts either way (TP+FP+FN == 0) the factual
    term is undefined rather than zero — F1 falls back to the similarity so a
    ticket is not scored 0.75-down for having nothing to check.
    """
    denom = n_present + 0.5 * (n_prohibited + n_missing)
    if denom == 0:
        return round(similarity, 4) if similarity is not None else 0.0
    f1 = n_present / denom
    if similarity is None:
        return round(f1, 4)
    return round(_W_FACTUAL * f1 + _W_SIMILARITY * similarity, 4)


class _Similarity:
    """Cosine similarity against the reference reply, using the retriever's own
    embedding model.

    Deliberately NOT an LLM judge. The whole point of this eval is that it is
    deterministic and free: judge availability is the project's binding
    constraint (Bug 5), and a quality metric that inherits that constraint is
    not a quality metric. The model is already a dependency and already loaded
    for retrieval, so this costs nothing per ticket beyond one local encode.
    """

    def __init__(self) -> None:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        self._emb = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    def score(self, answer: str, reference: str) -> float | None:
        if not answer.strip() or not reference.strip():
            return None
        a, b = self._emb.embed_documents([answer, reference])
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na == 0 or nb == 0:
            return None
        # Clamp: floating point can put an identical pair marginally above 1.
        return max(0.0, min(1.0, dot / (na * nb)))


def _mean(xs: list) -> float | None:
    """Mean over the values that exist. None entries are EXCLUDED, not treated
    as zero — a ticket with no expected_doc_ids has no context-recall score,
    and scoring it 0 would understate retrieval.
    """
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="check only the first N tickets")
    ap.add_argument("--output", default="evaluation/results/gt",
                    help="directory for the report")
    args = ap.parse_args(argv)

    configure_logging()
    gt = {g["ticket_id"]: g for g in json.loads(GT_PATH.read_text())}
    tickets = [t for t in json.loads(TICKETS_PATH.read_text()) if t["ticket_id"] in gt]
    if args.limit:
        tickets = tickets[: args.limit]

    run_id = set_run_id(new_run_id("gtcheck"))
    print(f"[gt] run_id={run_id} tickets={len(tickets)} (of {len(gt)} with ground truth)")

    sim = _Similarity()
    rows, started = [], time.perf_counter()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / "gt_rows.jsonl"
    # Stream, for the same reason the harness does: a 200-ticket pass against a
    # live provider takes long enough that losing it to an interrupt is a real
    # cost, and a partial run is still evidence.
    with rows_path.open("w", encoding="utf-8") as fh:
        for i, raw in enumerate(tickets, 1):
            tid = raw["ticket_id"]
            truth = gt[tid]
            # No classify() call: neither retrieve nor generate consumes the
            # classification, so it would be a wasted model call per ticket.
            ticket = normalise_any(raw)
            passages = retrieve(ticket.body, ticket_id=tid)
            response = generate(ticket, passages, ticket_id=tid)
            checked = check_answer(response.answer, truth["must_not_claim"],
                                   truth["must_mention"])

            retrieved = [p.doc_id for p in passages]
            reference = truth.get("reference_response", "")
            boiler = is_boilerplate_reference(reference)
            # Compare the CUSTOMER-FACING text: the reference replies contain
            # no [DOC-ID] markers, so leaving ours in would depress similarity
            # for a formatting difference the customer never sees.
            customer_text = strip_citation_markers(response.answer)
            similarity = None if boiler else sim.score(customer_text, reference)
            n_present = checked["must_mention_total"] - len(checked["must_mention_missing"])

            row = {
                "ticket_id": tid,
                "unknown": response.unknown,
                "answer": response.answer,
                "error": response.error,
                "retrieved_doc_ids": retrieved,
                "expected_doc_ids": truth.get("expected_doc_ids", []),
                "context_recall": context_recall(retrieved, truth.get("expected_doc_ids", [])),
                "reference_is_boilerplate": boiler,
                "answer_similarity": None if similarity is None else round(similarity, 4),
                "answer_correctness": answer_correctness(
                    n_present, len(checked["must_mention_missing"]),
                    len(checked["violations"]), similarity),
                **checked,
            }
            rows.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(tickets):
                print(f"[gt]   {i}/{len(tickets)} "
                      f"({time.perf_counter() - started:.0f}s)", flush=True)

    answered = [r for r in rows if not r["unknown"] and r["answer"]]
    specific = [r for r in answered if not r["reference_is_boilerplate"]]
    boilerplate = [r for r in answered if r["reference_is_boilerplate"]]
    violating = [r for r in answered if r["violations"]]
    by_claim: dict[str, int] = {}
    for r in violating:
        for v in r["violations"]:
            by_claim[v["claim"]] = by_claim.get(v["claim"], 0) + 1
    expected_mentions = sum(r["must_mention_total"] for r in answered)
    missing_mentions = sum(len(r["must_mention_missing"]) for r in answered)

    report = {
        "run_id": run_id,
        "tickets_checked": len(rows),
        "answers_produced": len(answered),
        "answers_declined_unknown": sum(1 for r in rows if r["unknown"]),
        "answers_with_a_prohibited_claim": len(violating),
        "prohibited_claim_rate": round(len(violating) / len(answered), 4) if answered else None,
        "violations_by_claim": by_claim,
        "must_mention_expected": expected_mentions,
        "must_mention_missing": missing_mentions,
        "must_mention_coverage": (
            round(1 - missing_mentions / expected_mentions, 4) if expected_mentions else None),
        # ── expected_doc_ids -> context recall ──────────────────────────
        "context_recall_mean": _mean([r["context_recall"] for r in rows]),
        "context_recall_n": sum(1 for r in rows if r["context_recall"] is not None),
        # ── reference_response -> answer similarity / correctness ───────
        # Split on purpose. 79 of 200 references are a content-free holding
        # reply; averaging them in would measure politeness and flatter the
        # headline. The specific-reference figure is the one to quote.
        "specific_reference_n": len(specific),
        "boilerplate_reference_n": len(boilerplate),
        "answer_similarity_mean": _mean([r["answer_similarity"] for r in specific]),
        "answer_correctness_mean": _mean([r["answer_correctness"] for r in specific]),
        "answer_correctness_mean_all_tickets": _mean(
            [r["answer_correctness"] for r in answered]),
        "ragas_weights": {"factual": _W_FACTUAL, "similarity": _W_SIMILARITY},
        "note": ("Detection is a lower bound — a phrasing no pattern covers counts "
                 "as clean. Guardrails were NOT run; this measures the generator."),
        "wall_clock_seconds": round(time.perf_counter() - started, 1),
    }

    # gt_rows.jsonl was already streamed during the run.
    (out / "gt_report.json").write_text(json.dumps(report, indent=2))

    print(f"\n[gt] answers produced: {len(answered)}/{len(rows)} "
          f"(declined unknown: {report['answers_declined_unknown']})")
    print(f"[gt] answers making a PROHIBITED claim: {len(violating)}"
          f" ({report['prohibited_claim_rate']})")
    for claim, n in sorted(by_claim.items(), key=lambda x: -x[1]):
        print(f"[gt]    {n:>3}x  {claim}")
    print(f"[gt] must_mention coverage: {report['must_mention_coverage']}")
    print(f"[gt] context recall (expected_doc_ids): {report['context_recall_mean']} "
          f"over {report['context_recall_n']} tickets")
    print(f"[gt] answer similarity vs reference: {report['answer_similarity_mean']} "
          f"over {len(specific)} tickets with a SPECIFIC reference")
    print(f"[gt] answer correctness (RAGAS 0.75/0.25): "
          f"{report['answer_correctness_mean']}")
    print(f"[gt]   ({len(boilerplate)} tickets excluded — their reference is the "
          f"generic holding reply)")
    print(f"[gt] wrote {out}/gt_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
