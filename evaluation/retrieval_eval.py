"""Retrieval metrics against data/ground_truth_responses.json expected_doc_ids.

Standard ranked-retrieval metrics, computed on the EXACT chunk list the
production retriever returns (src.retrieve.retrieve — same query text, same
top_k, same relevance threshold as the harness), then broken down by intent.

  hit@k    any relevant chunk in the top k
  MRR      mean of 1 / rank of the first relevant chunk (0 when none)
  NDCG@k   binary-relevance NDCG. A chunk is relevant when its doc_id is in
           expected_doc_ids. Each expected DOCUMENT earns gain once, at its
           first chunk — the TREC/BEIR convention. Without that, two chunks of
           one expected article would score DCG above the ideal and NDCG > 1;
           every article here splits into 2-3 chunks, so this is not a corner
           case. IDCG places min(|expected|, k) relevant documents at the top;
           51 of the 200 tickets expect more than one document.

An empty result (nothing cleared the threshold) scores 0 on every metric —
that is what production returned, so it is what gets measured.

The confusion table answers "when the top chunk is wrong, what did it pick
instead?" — e.g. whether data_residency queries land on the data-export
article. Only rank-1 misses are counted: that chunk is the one most likely to
steer the generated answer.

No model calls; runs on the local embedding index. Deterministic.

Usage:
    python -m evaluation.retrieval_eval --output evaluation/results/retrieval_eval
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).parent.parent
GT_PATH = _ROOT / "data" / "ground_truth_responses.json"
TICKETS_PATH = _ROOT / "data" / "development_tickets.json"
DOCS_PATH = _ROOT / "data" / "documentation.json"
K_VALUES = (1, 3, 5)


def first_relevant_rank(ranked: list[str], expected: set[str]) -> int | None:
    """1-based rank of the first chunk whose doc_id is expected, or None."""
    for i, doc_id in enumerate(ranked, start=1):
        if doc_id in expected:
            return i
    return None


def hit_at_k(ranked: list[str], expected: set[str], k: int) -> bool:
    return any(d in expected for d in ranked[:k])


def reciprocal_rank(ranked: list[str], expected: set[str]) -> float:
    rank = first_relevant_rank(ranked, expected)
    return 0.0 if rank is None else 1.0 / rank


def ndcg_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    """Binary NDCG@k, each expected document credited once (see module doc)."""
    credited: set[str] = set()
    dcg = 0.0
    for i, doc_id in enumerate(ranked[:k], start=1):
        if doc_id in expected and doc_id not in credited:
            credited.add(doc_id)
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(expected), k) + 1))
    return dcg / ideal if ideal else 0.0


def score_ticket(ranked: list[str], expected: list[str]) -> dict:
    exp = set(expected)
    row = {f"hit@{k}": hit_at_k(ranked, exp, k) for k in K_VALUES}
    row["rr"] = reciprocal_rank(ranked, exp)
    row["ndcg@5"] = ndcg_at_k(ranked, exp, 5)
    row["first_relevant_rank"] = first_relevant_rank(ranked, exp)
    return row


def aggregate(rows: list[dict]) -> dict:
    """Mean of each metric over rows. Booleans average to a rate."""
    n = len(rows)
    if not n:
        return {"n": 0}
    out: dict = {"n": n}
    for key in [f"hit@{k}" for k in K_VALUES] + ["rr", "ndcg@5"]:
        out["mrr" if key == "rr" else key] = round(sum(float(r[key]) for r in rows) / n, 4)
    return out


def by_intent(rows: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["intent"]].append(r)
    return {intent: aggregate(g) for intent, g in groups.items()}


def top1_confusions(rows: list[dict]) -> Counter:
    """(expected_doc, retrieved_top1_doc) pairs for every rank-1 miss.

    A ticket expecting several documents contributes one pair per expected
    document, since the wrong chunk displaced each of them.
    """
    pairs: Counter = Counter()
    for r in rows:
        ranked, expected = r["retrieved_doc_ids"], set(r["expected_doc_ids"])
        if not ranked or ranked[0] in expected:
            continue
        for exp in sorted(expected):
            pairs[(exp, ranked[0])] += 1
    return pairs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", default="evaluation/results/retrieval_eval")
    args = ap.parse_args(argv)

    from src.ingest import normalise_any
    from src.logging_config import configure_logging
    from src.logging_store import new_run_id, set_run_id
    from src.retrieve import retrieve

    configure_logging()
    run_id = set_run_id(new_run_id("retrieval-eval"))
    gt = {g["ticket_id"]: g for g in json.loads(GT_PATH.read_text())}
    tickets = [t for t in json.loads(TICKETS_PATH.read_text()) if t["ticket_id"] in gt]
    titles = {d["doc_id"]: d["title"] for d in json.loads(DOCS_PATH.read_text())}

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with (out / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for raw in tickets:
            tid = raw["ticket_id"]
            ticket = normalise_any(raw)
            # Same query text the harness sends, so this measures production.
            ranked = [p.doc_id for p in retrieve(ticket.body, ticket_id=tid)]
            row = {"ticket_id": tid, "intent": gt[tid]["intent"],
                   "expected_doc_ids": gt[tid]["expected_doc_ids"],
                   "retrieved_doc_ids": ranked,
                   **score_ticket(ranked, gt[tid]["expected_doc_ids"])}
            rows.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()

    intents = by_intent(rows)
    confusions = top1_confusions(rows)
    report = {
        "run_id": run_id,
        "source": "data/ground_truth_responses.json expected_doc_ids",
        "overall": aggregate(rows),
        "empty_results": sum(1 for r in rows if not r["retrieved_doc_ids"]),
        "by_intent": dict(sorted(intents.items(), key=lambda kv: kv[1]["mrr"])),
        "top1_confusions": [
            {"expected": e, "expected_title": titles.get(e, ""),
             "retrieved": g, "retrieved_title": titles.get(g, ""), "count": n}
            for (e, g), n in confusions.most_common()
        ],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))

    o = report["overall"]
    print(f"[retrieval] {o['n']} tickets  hit@1={o['hit@1']} hit@3={o['hit@3']} "
          f"hit@5={o['hit@5']}  MRR={o['mrr']}  NDCG@5={o['ndcg@5']}  "
          f"empty={report['empty_results']}")
    print("[retrieval] weakest intents by MRR:")
    for intent, s in list(report["by_intent"].items())[:6]:
        print(f"   {intent:26} n={s['n']:>3}  hit@1={s['hit@1']:.3f}  "
              f"MRR={s['mrr']:.3f}  NDCG@5={s['ndcg@5']:.3f}")
    print("[retrieval] top-1 confusions (expected -> retrieved instead):")
    for c in report["top1_confusions"][:8]:
        print(f"   {c['count']:>3}x  {c['expected']} {c['expected_title'][:30]!r} -> "
              f"{c['retrieved']} {c['retrieved_title'][:30]!r}")
    print(f"[retrieval] wrote {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
