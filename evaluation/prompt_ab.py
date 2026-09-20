"""Paired A/B of a candidate PR-GENERATE-01 against the committed baseline.

Answers one question: does the candidate prompt improve replies WITHOUT making
anything worse? Each ticket is classified and retrieved once, then both prompt
versions draft a reply from the same passages, and both drafts go through the
same guardrails and router. Only the generation prompt differs. Prompt order
alternates by ticket so neither version always runs first.

Pools:
  heldout       the frozen held-out half of data/ground_truth_responses.json
                (evaluation/splits/gt_prompt_split.json). Scored ONCE.
  tune          the other half. Smoke tests and any iteration go here.
  unanswerable  the 143 development tickets labelled answerable_from_docs=False
                that are not in the ground truth. Guards the abstention side:
                a prompt can raise answer scores simply by answering tickets it
                should have declined. The validation set is not touched, so the
                B-21 gate stays independent of prompt selection.

PRE-REGISTERED DECISION RULE — written and committed before the candidate
prompt existed. The candidate is adopted only if EVERY check passes; a tie or
an unproven gain keeps the baseline.

  Safety (from the ground truth and the review of the proposed draft)
    S1  held-out replies making a must_not_claim prohibition: no increase
    S2  replies with a first-person promise, a follow-up timeline, a claim of
        internal activity, or a hedge the articles never use — each counted
        over both pools: at most +1 (coarse regexes; one hit is noise)
  Abstention
    A1  unanswerable tickets auto-sent: no increase
    A2  unanswerable abstention rate: falls by at most 0.05
    Q3  held-out (all answerable) abstention rate: rises by at most 0.05
  Quality
    Q1  held-out answer correctness, paired, 95% bootstrap CI lower bound
        >= -0.02 (no meaningful drop)
    I1  held-out mean correctness difference > 0 OR mean must_mention
        coverage difference > 0 (some measured gain)
  Operations
    G1  held-out tickets blocked by a prompt-sensitive guardrail (every
        guardrail except confidence_floor, excluding fail-safe blocks):
        at most +3
    O1  generator errors over both pools: at most +2

AMENDMENT (2026-09-14, after a 5-ticket smoke run on the TUNE pool, before any
held-out run). Amendments may only make the rule stricter.
  1. The candidate is PR-GENERATE-01 v3.1, not v3.0: the smoke run showed v3.0
     using a doc_id as a noun ("the steps in [DOC-DEPLOY-002]"), which reads as
     a broken sentence once markers are stripped for sending.
  2. S2 gains marker_as_reference — replies that use a doc_id inside a
     sentence — measured on the raw draft, at most +1 like the other
     diagnostics.
  3. Scope, not a tolerance: the A/B runs with gpt-4o-mini drafting and
     gpt-4.1-mini judging, both on OpenAI, chosen by the maintainer: no
     OpenRouter credit, and gpt-4.1-mini over gpt-4o on cost (~$2.20 against
     ~$11.80 for the full run). The verdict applies to that pair, not to the
     documented meta-llama/llama-3.1-8b-instruct setup. gpt-4.1-mini is a
     different model from the drafter but the same family, which the
     prompt-writer guidance advises against, and it has not been validated as a
     judge in this project (gpt-4o was, in the 5-ticket tune smoke run: 55/55
     calls, no fail-safe blocks). Both prompt versions face the same pair, so the
     paired comparison is affected less than absolute scores. summary.json
     records both models.
  4. Infrastructure failures (added after the first full attempt was stopped
     part-way). The laptop slept repeatedly during that attempt; connection
     errors hit about 40% of held-out pairs, and a failed classification
     silently escalated both drafts. A ticket whose classification, drafting
     or any guardrail failed with a CONNECTION-LEVEL provider error
     (APIConnectionError, InternalServerError, RateLimitError) is excluded from
     BOTH arms and counted. Timeouts, cut-off output and malformed JSON are not
     infrastructure: they stay as errors against the prompt. New check V1: if
     more than 5% of either pool's tickets hit an infrastructure failure, the
     verdict is inconclusive, never adopt. Disclosure: the stopped attempt
     printed per-arm counts of errors, abstentions, auto-sends and fail-safe
     blocks for its first 25 held-out and 17 unanswerable tickets; no quality
     metric was computed or viewed. The rerun starts from scratch.

Scoring follows evaluation/gt_response_check.py (RAGAS-compatible formulas,
implemented directly). An abstention on an answerable held-out ticket scores 0
correctness and 0 coverage: declining an answerable ticket is not a free pass.

Usage:
    python -m evaluation.prompt_ab run --pool tune --limit 5 --output DIR
    python -m evaluation.prompt_ab run --pool heldout --output DIR
    python -m evaluation.prompt_ab run --pool unanswerable --output DIR
    python -m evaluation.prompt_ab decide --heldout DIR --unanswerable DIR
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from evaluation.gt_response_check import (
    _Similarity,
    answer_correctness,
    check_answer,
    is_boilerplate_reference,
)
from src.generate import strip_citation_markers
from src.prompt_loader import LoadedPrompt, _parse, load_prompt

_ROOT = Path(__file__).parent.parent
PROMPT_ID = "PR-GENERATE-01"
PROMPT_PATH = "prompts/build/PR-GENERATE-01.md"
SPLIT_PATH = _ROOT / "evaluation" / "splits" / "gt_prompt_split.json"
GT_PATH = _ROOT / "data" / "ground_truth_responses.json"
TICKETS_PATH = _ROOT / "data" / "development_tickets.json"

BASELINE_VERSION = "2.0"
CANDIDATE_VERSION = "3.1"
VARIANTS = ("baseline", "candidate")
BOOTSTRAP_SEED = 20260914
BOOTSTRAP_RESAMPLES = 2000

# Pre-registered tolerances — see the module docstring.
DIAG_TOLERANCE = 1
UNKNOWN_RATE_TOLERANCE = 0.05
CORRECTNESS_DROP_TOLERANCE = 0.02
BLOCK_TOLERANCE = 3
ERROR_TOLERANCE = 2
INFRA_FAILURE_LIMIT = 0.05
# Connection-level provider failures. They say nothing about a prompt, so a
# ticket hitting one is excluded from both arms. Deliberately NOT included:
# APITimeoutError (a longer prompt can genuinely cause it), cut-off output, and
# JSON errors — those stay as errors against the prompt.
INFRA_ERROR_TYPES = ("APIConnectionError", "InternalServerError", "RateLimitError")


def is_infrastructure_error(message: Optional[str]) -> bool:
    return bool(message) and any(t in message for t in INFRA_ERROR_TYPES)


# The prompt cannot change the classifier's confidence.
PROMPT_INSENSITIVE_GUARDRAILS = frozenset({"confidence_floor"})

# ── degradation diagnostics ─────────────────────────────────────────────────
# Each targets a failure the review of the proposed draft predicted. They are
# coarse by design and only compared between the two prompt versions.
DIAGNOSTICS: dict[str, re.Pattern] = {
    # A promise of an action the automation cannot take: the reference replies
    # carry "I will take a closer look at your account directly" 79 times.
    "first_person_promise": re.compile(
        r"\b(?:i|we)\s*(?:will|'ll|can)\s+(?:take\s+a\s+(?:closer\s+)?look|"
        r"look\s+(?:further|into)|start\s+(?:that|the|a)\s+request|raise|escalate|"
        r"arrange|process|check\s+your\s+account)\b"
        r"|\bhappy\s+to\s+look\s+(?:further|into)\b"
        r"|\bwill\s+be\s+(?:handled|reviewed|looked\s+at|picked\s+up)\s+by\b",
        re.IGNORECASE),
    # A follow-up timeline — "the relevant team will get back to you within 2
    # business days" passed every existing detector. Documented product timings
    # ("traffic moves within roughly thirty seconds") must not count, so a
    # follow-up verb is required.
    "followup_timeline": re.compile(
        r"\b(?:get\s+back\s+to|follow\s+up|respond|reply|contact|reach\s+out|update)"
        r"\w*\b[^.]{0,40}\b(?:within|by|in)\s+(?:\d+|a|an|one|two|three|few)\b"
        r"[^.]{0,15}\b(?:hours?|days?|weeks?)\b",
        re.IGNORECASE),
    # Activity the automation did not perform: VAL-0002's invented
    # "We're still investigating the issue".
    "internal_action": re.compile(
        r"\b(?:we|our\s+team|i)\s*(?:am|are|'re|'m|have|has|'ve|will|'ll)\s+"
        r"(?:now\s+|still\s+)?(?:investigating|looking\s+into|reviewed|checked|"
        r"escalated|raised|forwarded|flagged)\b",
        re.IGNORECASE),
    # Frequency claims the help articles never make (checked: neither phrase
    # appears in data/documentation.json).
    "unsourced_hedge": re.compile(
        r"\b(?:the\s+usual\s+cause|usually\s+caused|in\s+most\s+cases)\b", re.IGNORECASE),
}


# Diagnostics that need the RAW draft, because citation markers are stripped
# from the customer-facing text the others inspect.
RAW_DIAGNOSTICS: dict[str, re.Pattern] = {
    # "follow the steps in [DOC-DEPLOY-002]" becomes "follow the steps in." for
    # the customer. Observed on v3.0 in the smoke run (DEV-0009).
    "marker_as_reference": re.compile(
        r"\b(?:in|see|per|from|at|following|described\s+in|outlined\s+in|"
        r"refer\s+to|according\s+to)\s+\[DOC-[A-Z]+-\d+\]",
        re.IGNORECASE),
}
ALL_DIAGNOSTICS = (*DIAGNOSTICS, *RAW_DIAGNOSTICS)


def diagnostics(text: str, raw: str = "") -> dict[str, bool]:
    """Customer-text diagnostics on `text`, raw-draft diagnostics on `raw`."""
    out = {name: bool(pattern.search(text)) for name, pattern in DIAGNOSTICS.items()}
    out.update({name: bool(pattern.search(raw)) for name, pattern in RAW_DIAGNOSTICS.items()})
    return out


def paired_bootstrap(diffs: list[float], resamples: int = BOOTSTRAP_RESAMPLES,
                     seed: int = BOOTSTRAP_SEED) -> dict:
    """Mean paired difference with a percentile 95% bootstrap interval."""
    if not diffs:
        return {"n": 0, "mean": None, "ci_low": None, "ci_high": None}
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(resamples))
    return {
        "n": n,
        "mean": round(sum(diffs) / n, 4),
        "ci_low": round(means[int(0.025 * resamples)], 4),
        "ci_high": round(means[int(0.975 * resamples) - 1], 4),
    }


def score_variant(response, guardrail_results, decision, truth: Optional[dict],
                  sim) -> dict:
    """Everything the decision rule needs about one draft.

    Scoring uses the customer-facing text (citation markers stripped), the same
    text the reference replies are compared with.
    """
    text = strip_citation_markers(response.answer)
    answered = bool(text.strip()) and not response.unknown
    blocks = [g for g in guardrail_results if g.blocking and not g.passed]
    row = {
        "unknown": response.unknown,
        "error": response.error,
        "answer": response.answer,
        "decision": decision.decision,
        "trigger": decision.trigger,
        "prompt_sensitive_blocks": sorted(
            g.name for g in blocks
            if g.name not in PROMPT_INSENSITIVE_GUARDRAILS and not g.fail_safe),
        "fail_safe_blocks": sorted(g.name for g in blocks if g.fail_safe),
        "infra_error": (
            is_infrastructure_error(response.error)
            or any(g.fail_safe and is_infrastructure_error(g.reason) for g in blocks)
        ),
        "diagnostics": diagnostics(text, response.answer),
    }
    if truth is None:
        return row
    checked = check_answer(text, truth["must_not_claim"], truth["must_mention"])
    required = checked["must_mention_total"]
    present = required - len(checked["must_mention_missing"]) if answered else 0
    violations = [v["claim"] for v in checked["violations"]] if answered else []
    boilerplate = is_boilerplate_reference(truth["reference_response"])
    similarity = (sim.score(text, truth["reference_response"])
                  if answered and not boilerplate else None)
    if boilerplate:
        correctness = None
    elif answered:
        correctness = answer_correctness(present, required - present, len(violations), similarity)
    else:
        correctness = 0.0
    row.update(
        violations=violations,
        mentions_required=required,
        mentions_present=present,
        coverage=(present / required) if required else None,
        specific_reference=not boilerplate,
        similarity=None if similarity is None else round(similarity, 4),
        correctness=correctness,
    )
    return row


def summarise(rows: list[dict]) -> dict:
    infra = [r for r in rows if r.get("infra_failure")]
    rows = [r for r in rows if not r.get("infra_failure")]
    out: dict = {"n": len(rows), "n_attempted": len(rows) + len(infra),
                 "infra_failure_tickets": len(infra)}
    has_truth = bool(rows) and "coverage" in rows[0]["baseline"]
    for variant in VARIANTS:
        rs = [r[variant] for r in rows]
        s: dict = {
            "generator_errors": sum(1 for x in rs if x["error"]),
            "unknown": sum(1 for x in rs if x["unknown"] and not x["error"]),
            "auto_respond": sum(1 for x in rs if x["decision"] == "auto_respond"),
            "prompt_sensitive_block_tickets": sum(1 for x in rs if x["prompt_sensitive_blocks"]),
            "fail_safe_block_tickets": sum(1 for x in rs if x["fail_safe_blocks"]),
            "diagnostics": {k: sum(1 for x in rs if x["diagnostics"][k])
                            for k in ALL_DIAGNOSTICS},
        }
        if has_truth:
            required = sum(x["mentions_required"] for x in rs)
            present = sum(x["mentions_present"] for x in rs)
            corr = [x["correctness"] for x in rs if x["correctness"] is not None]
            sims = [x["similarity"] for x in rs if x["similarity"] is not None]
            s["prohibited_claim_tickets"] = sum(1 for x in rs if x["violations"])
            s["must_mention_coverage"] = round(present / required, 4) if required else None
            s["mean_correctness"] = round(statistics.mean(corr), 4) if corr else None
            s["mean_similarity"] = round(statistics.mean(sims), 4) if sims else None
        out[variant] = s
    paired = [r for r in rows if not r["baseline"]["error"] and not r["candidate"]["error"]]
    out["paired_n"] = len(paired)
    if has_truth:
        out["correctness_diff"] = paired_bootstrap([
            r["candidate"]["correctness"] - r["baseline"]["correctness"]
            for r in paired if r["baseline"]["correctness"] is not None])
        out["coverage_diff"] = paired_bootstrap([
            r["candidate"]["coverage"] - r["baseline"]["coverage"]
            for r in paired if r["baseline"]["coverage"] is not None])
    return out


def decide(heldout: dict, unanswerable: dict) -> dict:
    """Apply the pre-registered rule. Adopt only if every check passes."""
    hb, hc = heldout["baseline"], heldout["candidate"]
    ub, uc = unanswerable["baseline"], unanswerable["candidate"]
    checks: list[dict] = []

    def add(rule: str, passed: bool, baseline, candidate) -> None:
        checks.append({"rule": rule, "passed": bool(passed),
                       "baseline": baseline, "candidate": candidate})

    def rate(summary: dict, n: int) -> float:
        return round(summary["unknown"] / n, 4) if n else 0.0

    for pool, summary in (("held-out", heldout), ("unanswerable", unanswerable)):
        attempted = summary.get("n_attempted", summary["n"])
        failed = summary.get("infra_failure_tickets", 0)
        share = round(failed / attempted, 4) if attempted else 0.0
        add(f"V1 {pool} infrastructure failures at most {INFRA_FAILURE_LIMIT:.0%} of tickets",
            share <= INFRA_FAILURE_LIMIT, None, {"failed": failed, "attempted": attempted,
                                                 "share": share})

    add("S1 held-out prohibited-claim replies do not increase",
        hc["prohibited_claim_tickets"] <= hb["prohibited_claim_tickets"],
        hb["prohibited_claim_tickets"], hc["prohibited_claim_tickets"])
    for name in ALL_DIAGNOSTICS:
        b = hb["diagnostics"][name] + ub["diagnostics"][name]
        c = hc["diagnostics"][name] + uc["diagnostics"][name]
        add(f"S2 {name} replies rise by at most {DIAG_TOLERANCE}", c <= b + DIAG_TOLERANCE, b, c)
    add("A1 unanswerable tickets auto-sent do not increase",
        uc["auto_respond"] <= ub["auto_respond"], ub["auto_respond"], uc["auto_respond"])
    ur_b, ur_c = rate(ub, unanswerable["n"]), rate(uc, unanswerable["n"])
    add(f"A2 unanswerable abstention rate falls by at most {UNKNOWN_RATE_TOLERANCE}",
        ur_c >= ur_b - UNKNOWN_RATE_TOLERANCE, ur_b, ur_c)
    hr_b, hr_c = rate(hb, heldout["n"]), rate(hc, heldout["n"])
    add(f"Q3 held-out abstention rate rises by at most {UNKNOWN_RATE_TOLERANCE}",
        hr_c <= hr_b + UNKNOWN_RATE_TOLERANCE, hr_b, hr_c)
    cd = heldout["correctness_diff"]
    add(f"Q1 held-out correctness 95% CI lower bound >= -{CORRECTNESS_DROP_TOLERANCE}",
        cd["ci_low"] is not None and cd["ci_low"] >= -CORRECTNESS_DROP_TOLERANCE,
        hb["mean_correctness"], {"diff": cd["mean"], "ci": [cd["ci_low"], cd["ci_high"]]})
    vd = heldout["coverage_diff"]
    add("I1 held-out correctness or must_mention coverage improves",
        (cd["mean"] or 0) > 0 or (vd["mean"] or 0) > 0,
        {"coverage": hb["must_mention_coverage"]},
        {"correctness_diff": cd["mean"], "coverage_diff": vd["mean"]})
    add(f"G1 held-out prompt-sensitive guardrail blocks rise by at most {BLOCK_TOLERANCE}",
        hc["prompt_sensitive_block_tickets"]
        <= hb["prompt_sensitive_block_tickets"] + BLOCK_TOLERANCE,
        hb["prompt_sensitive_block_tickets"], hc["prompt_sensitive_block_tickets"])
    eb = hb["generator_errors"] + ub["generator_errors"]
    ec = hc["generator_errors"] + uc["generator_errors"]
    add(f"O1 generator errors rise by at most {ERROR_TOLERANCE}",
        ec <= eb + ERROR_TOLERANCE, eb, ec)
    adopt = all(c["passed"] for c in checks)
    inconclusive = any(c["rule"].startswith("V1") and not c["passed"] for c in checks)
    return {"adopt_candidate": adopt, "inconclusive": inconclusive, "checks": checks}


@contextmanager
def generation_prompt(prompt: LoadedPrompt) -> Iterator[None]:
    """Temporarily point src.generate at a given PR-GENERATE-01 version.

    Sequential use only: this swaps module globals, so two variants must never
    draft concurrently in one process.
    """
    import src.generate as gen

    saved = (gen._PROMPT_01, gen._PROMPT_01_VERSION)
    gen._PROMPT_01 = prompt
    gen._PROMPT_01_VERSION = f"{PROMPT_ID}@{prompt.version}"
    try:
        yield
    finally:
        gen._PROMPT_01, gen._PROMPT_01_VERSION = saved


def prompt_at_version(version: str) -> LoadedPrompt:
    """The most recent committed PR-GENERATE-01 carrying `version`."""
    log = subprocess.run(["git", "log", "--format=%H", "--", PROMPT_PATH], cwd=_ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    for commit in log:
        text = subprocess.run(["git", "show", f"{commit}:{PROMPT_PATH}"], cwd=_ROOT,
                              capture_output=True, text=True, check=True).stdout
        prompt = _parse(PROMPT_ID, text)
        if prompt.version == version:
            return prompt
    raise SystemExit(f"no committed {PROMPT_ID} with version {version}")


def _pool(name: str) -> list[tuple[dict, Optional[dict]]]:
    tickets = {t["ticket_id"]: t for t in json.loads(TICKETS_PATH.read_text())}
    gt = {g["ticket_id"]: g for g in json.loads(GT_PATH.read_text())}
    if name in ("heldout", "tune"):
        ids = json.loads(SPLIT_PATH.read_text())[name]
        return [(tickets[i], gt[i]) for i in ids]
    if name == "unanswerable":
        return [(t, None) for tid, t in sorted(tickets.items())
                if tid not in gt and t["labels"].get("answerable_from_docs") is False]
    raise SystemExit(f"unknown pool {name!r}")


def run(pool: str, output: Path, limit: int) -> int:
    from src.classify import classify
    from src.generate import generate
    from src.guardrails import run_all
    from src.ingest import normalise_any
    from src.logging_config import configure_logging
    from src.logging_store import new_run_id, set_run_id
    from src.retrieve import retrieve
    from src.route import route
    from src.schema import GuardrailContext

    configure_logging()
    run_id = set_run_id(new_run_id(f"prompt-ab-{pool}"))
    candidate = load_prompt(PROMPT_ID)
    if candidate.version != CANDIDATE_VERSION:
        raise SystemExit(f"working-tree {PROMPT_ID} is v{candidate.version}, "
                         f"expected candidate v{CANDIDATE_VERSION}")
    baseline = prompt_at_version(BASELINE_VERSION)
    prompts = {"baseline": baseline, "candidate": candidate}

    items = _pool(pool)
    if limit:
        items = items[:limit]
    sim = _Similarity() if pool != "unanswerable" else None
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    print(f"[ab] run_id={run_id} pool={pool} tickets={len(items)} "
          f"baseline=v{baseline.version} candidate=v{candidate.version}", flush=True)
    with (output / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for i, (raw, truth) in enumerate(items):
            tid = raw["ticket_id"]
            ticket = normalise_any(raw)
            classification = classify(ticket)
            passages = retrieve(ticket.body, ticket_id=tid)
            order = VARIANTS if i % 2 == 0 else VARIANTS[::-1]
            row: dict = {"ticket_id": tid, "pool": pool,
                         "intent": raw["labels"]["intent"], "order": list(order)}
            for variant in order:
                with generation_prompt(prompts[variant]):
                    response = generate(ticket, passages, ticket_id=tid)
                ctx = GuardrailContext(ticket=ticket, passages=passages,
                                       classification=classification)
                results = run_all(response, ctx)
                decision = route(ticket, classification, passages, response, results)
                row[variant] = score_variant(response, results, decision, truth, sim)
            row["classifier_error"] = classification.error
            row["infra_failure"] = (
                is_infrastructure_error(classification.error)
                or any(row[v]["infra_error"] for v in VARIANTS)
            )
            rows.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if (i + 1) % 10 == 0 or i + 1 == len(items):
                print(f"[ab]   {i + 1}/{len(items)}", flush=True)

    summary = summarise(rows)
    from src.config import GUARDRAIL_MODEL, MODEL_NAME

    summary.update(pool=pool, run_id=run_id, limit=limit,
                   baseline_version=baseline.version, candidate_version=candidate.version,
                   model_name=MODEL_NAME, guardrail_model=GUARDRAIL_MODEL)
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pool", required=True, choices=["heldout", "tune", "unanswerable"])
    r.add_argument("--output", required=True)
    r.add_argument("--limit", type=int, default=0)
    d = sub.add_parser("decide")
    d.add_argument("--heldout", required=True)
    d.add_argument("--unanswerable", required=True)
    d.add_argument("--output", default="")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return run(args.pool, Path(args.output), args.limit)
    held = json.loads((Path(args.heldout) / "summary.json").read_text())
    unans = json.loads((Path(args.unanswerable) / "summary.json").read_text())
    if (held.get("model_name"), held.get("guardrail_model")) != (
            unans.get("model_name"), unans.get("guardrail_model")):
        raise SystemExit("held-out and unanswerable runs used different models; "
                         "their results cannot be combined")
    for summary, pool in ((held, "heldout"), (unans, "unanswerable")):
        if summary.get("pool") != pool or summary.get("limit"):
            raise SystemExit(f"{pool} summary is not a full {pool} run: {summary.get('pool')}, "
                             f"limit={summary.get('limit')}")
    verdict = decide(held, unans)
    for c in verdict["checks"]:
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {c['rule']:62} "
              f"baseline={c['baseline']}  candidate={c['candidate']}")
    print(f"\n  adopt candidate: {verdict['adopt_candidate']}")
    if args.output:
        Path(args.output).write_text(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
