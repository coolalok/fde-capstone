"""B-17 runner for PR-EVAL-JUDGE-01, and the B-18 agreement check.

  run    score every item in a calibration fixture (or any file of the same shape)
         with the judge, streaming one JSON line per item.
  agree  compare those scores with the fixture's human scores: Spearman per dimension
         and pooled across dimensions, plus exact and within-one agreement.

The judge is called through the guardrail judge's own call path
(src.guardrails._openrouter_call), so it uses GUARDRAIL_MODEL / GUARDRAIL_BASE_URL /
GUARDRAIL_API_KEY with the same timeouts, JSON mode and seed handling. On 14 Sep that is
gemini-3.8-flash; the B-21 drafts it scores were written by gpt-4o-mini.

A verdict that fails validation is recorded as an error, never coerced into a score.
Items with an error are excluded from agreement and counted.

Usage:
    python -m evaluation.judge run --fixture tests/fixtures/judge_calibration.json \
        --output evaluation/results/judge_calibration
    python -m evaluation.judge agree --fixture tests/fixtures/judge_calibration.json \
        --judged evaluation/results/judge_calibration/judged.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Callable, Optional

PROMPT_ID = "PR-EVAL-JUDGE-01"
DIMENSIONS = ("context_relevance", "groundedness", "answer_relevance")
AGREEMENT_FLOOR = 0.70
ModelCall = Callable[[str, str, int], str]

_FAMILY_PREFIXES = (
    (("gpt-", "o1", "o3", "o4", "chatgpt"), "openai"),
    (("gemini", "gemma"), "google"),
    (("claude",), "anthropic"),
    (("llama", "meta-llama"), "meta"),
    (("mistral", "mixtral", "codestral"), "mistral"),
    (("nemotron", "nvidia"), "nvidia"),
)


def model_family(model: str) -> str:
    """Provider family of a model id, with or without an OpenRouter 'org/' prefix."""
    name = model.lower()
    org, _, rest = name.partition("/")
    candidates = (org, rest) if rest else (name,)
    for candidate in candidates:
        for prefixes, family in _FAMILY_PREFIXES:
            if candidate.startswith(prefixes):
                return family
    return org if rest else name


def format_passages(passages: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] {p['doc_id']} — {p.get('title', '')} ({p.get('category', '')})\n{p['text']}"
        for i, p in enumerate(passages, 1)
    )


def parse_scores(raw: str) -> dict:
    """Validate a judge verdict. Raises ValueError on any schema violation."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("verdict is not a JSON object")
    if not isinstance(data.get("reasoning"), str) or not data["reasoning"].strip():
        raise ValueError("missing reasoning")
    scores = {}
    for dim in DIMENSIONS:
        block = data.get(dim)
        if not isinstance(block, dict):
            raise ValueError(f"missing {dim}")
        score = block.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError(f"{dim}.score must be an integer 1-5, got {score!r}")
        scores[dim] = score
    claims = data["groundedness"].get("unsupported_claims", [])
    if not isinstance(claims, list):
        raise ValueError("groundedness.unsupported_claims must be a list")
    return {"scores": scores, "reasoning": data["reasoning"], "unsupported_claims": claims}


def score_item(item: dict, call_model: Optional[ModelCall] = None) -> dict:
    """Score one item. Never raises: failures are recorded in `error`."""
    from src.prompt_loader import load_prompt

    prompt = load_prompt(PROMPT_ID)
    out = {"item_id": item["item_id"], "ticket_id": item["ticket_id"],
           "prompt_version": f"{PROMPT_ID}@{prompt.version}", "scores": None, "error": None}
    if not (item.get("reply") or "").strip():
        out["error"] = "empty reply: abstentions are not scored"
        return out
    if call_model is None:
        from src.guardrails import _openrouter_call as call_model
    started = time.perf_counter()
    raw = None
    try:
        user = prompt.render_user(channel=item["ticket"]["channel"],
                                  subject=item["ticket"]["subject"],
                                  body=item["ticket"]["body"],
                                  passages=format_passages(item["passages"]),
                                  reply=item["reply"])
        raw = call_model(prompt.system, user, 0)
        parsed = parse_scores(raw)
        out.update(scores=parsed["scores"], reasoning=parsed["reasoning"],
                   unsupported_claims=parsed["unsupported_claims"])
    except Exception as exc:  # recorded, not raised
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["raw_head"] = raw[:500] if raw else None
    out["latency_seconds"] = round(time.perf_counter() - started, 2)
    return out


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> Optional[float]:
    """Spearman's rho with average ranks for ties. None when undefined."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy)


def agreement(items: list[dict], judged: dict[str, dict]) -> dict:
    """Judge versus human, per dimension and pooled. Only complete pairs count."""
    report: dict = {"dimensions": {}, "excluded": {"judge_error": 0, "human_unscored": 0}}
    pooled_h: list[int] = []
    pooled_j: list[int] = []
    for dim in DIMENSIONS:
        h_scores, j_scores = [], []
        for item in items:
            j = judged.get(item["item_id"])
            h = item["human_scores"].get(dim)
            if j is None or j.get("error") or not j.get("scores"):
                continue
            if h is None:
                continue
            h_scores.append(h)
            j_scores.append(j["scores"][dim])
        n = len(h_scores)
        rho = spearman(h_scores, j_scores)
        pairs = list(zip(h_scores, j_scores))
        report["dimensions"][dim] = {
            "n": n,
            "spearman": None if rho is None else round(rho, 4),
            "exact_agreement": round(sum(a == b for a, b in pairs) / n, 4) if n else None,
            "within_one": round(sum(abs(a - b) <= 1 for a, b in pairs) / n, 4) if n else None,
            "mean_judge_minus_human": (
                round(statistics.mean(b - a for a, b in pairs), 3) if n else None),
        }
        pooled_h += h_scores
        pooled_j += j_scores
    for item in items:
        j = judged.get(item["item_id"])
        if j is None or j.get("error"):
            report["excluded"]["judge_error"] += 1
        elif any(v is None for v in item["human_scores"].values()):
            report["excluded"]["human_unscored"] += 1
    rho = spearman(pooled_h, pooled_j)
    report["pooled"] = {"n": len(pooled_h), "spearman": None if rho is None else round(rho, 4)}
    report["floor"] = AGREEMENT_FLOOR
    report["trusted"] = rho is not None and rho >= AGREEMENT_FLOOR
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--fixture", required=True)
    r.add_argument("--output", required=True)
    a = sub.add_parser("agree")
    a.add_argument("--fixture", required=True)
    a.add_argument("--judged", required=True)
    args = ap.parse_args(argv)
    fixture = json.loads(Path(args.fixture).read_text())
    if args.cmd == "run":
        from src.config import GUARDRAIL_MODEL, MODEL_NAME
        from src.logging_config import configure_logging

        configure_logging()
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        print(f"[judge] judge={GUARDRAIL_MODEL} ({model_family(GUARDRAIL_MODEL)}) "
              f"generator-config={MODEL_NAME} items={len(fixture['items'])}", flush=True)
        with (out / "judged.jsonl").open("w", encoding="utf-8") as fh:
            for i, item in enumerate(fixture["items"], 1):
                result = score_item(item)
                result["judge_model"] = GUARDRAIL_MODEL
                fh.write(json.dumps(result) + "\n")
                fh.flush()
                if i % 10 == 0 or i == len(fixture["items"]):
                    print(f"[judge]   {i}/{len(fixture['items'])}", flush=True)
        return 0
    judged = {}
    for line in Path(args.judged).open():
        row = json.loads(line)
        judged[row["item_id"]] = row
    report = agreement(fixture["items"], judged)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
