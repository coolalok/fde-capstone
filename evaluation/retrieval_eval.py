"""Retrieval metrics against data/ground_truth_responses.json expected_doc_ids.

Standard ranked-retrieval metrics, computed on the EXACT chunk list the
production retriever returns (src.retrieve.retrieve — same query text, same
top_k, same relevance threshold as the harness), then broken down by intent.

  hit@k    any relevant chunk in the top k
  recall@k share of the expected DOCUMENTS found in the top k, each counted
           once. Differs from hit@k only for tickets expecting several documents.
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

Rank metrics alone cannot show whether the embedding model STRUGGLES to tell
two topics apart. An intent scoring hit@1 = 1.000 may be winning every ticket
by a hair. Two diagnostics measure that directly:

  margin   per ticket: best score of any expected article minus best score of
           any other article, over the FULL ranking (every chunk, no threshold,
           no top_k — this is a model diagnostic, not a production metric).
           Negative means a wrong article outscored every right one. Reported
           per intent as median, minimum, and how many tickets fall under
           THIN_MARGIN, with the rival article that comes closest most often.
           Measured 13 Sep: sso_configuration scored 1.000 on every rank
           metric while 9 of its 15 tickets won by under 0.05.

  article overlap
           corpus level: for each pair of articles, the cosine similarity of
           their closest pair of chunks, using the index's stored embeddings.
           High overlap names the topics a query can fall between before any
           query is run.

The confusion table answers "when the top chunk is wrong, what did it pick
instead?". Only rank-1 misses are counted: that chunk is the one most likely to
steer the generated answer.

No model calls; runs on the local embedding index. Deterministic.

Usage:
    python -m evaluation.retrieval_eval --output evaluation/results/retrieval_eval
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import warnings
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

_ROOT = Path(__file__).parent.parent
GT_PATH = _ROOT / "data" / "ground_truth_responses.json"
TICKETS_PATH = _ROOT / "data" / "development_tickets.json"
DOCS_PATH = _ROOT / "data" / "documentation.json"
K_VALUES = (1, 3, 5)

# A correct article winning by less than this is a near miss. Correct-article
# top scores had a median of 0.558 on the 13 Sep gate run, so 0.05 is under a
# tenth of the signal separating right from wrong.
THIN_MARGIN = 0.05


def first_relevant_rank(ranked: list[str], expected: set[str]) -> int | None:
    """1-based rank of the first chunk whose doc_id is expected, or None."""
    for i, doc_id in enumerate(ranked, start=1):
        if doc_id in expected:
            return i
    return None


def hit_at_k(ranked: list[str], expected: set[str], k: int) -> bool:
    return any(d in expected for d in ranked[:k])


def recall_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    """Share of expected documents among the top k chunks, each counted once."""
    if not expected:
        return 0.0
    return len(expected & set(ranked[:k])) / len(expected)


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
    row.update({f"recall@{k}": recall_at_k(ranked, exp, k) for k in K_VALUES})
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
    keys = [f"hit@{k}" for k in K_VALUES] + [f"recall@{k}" for k in K_VALUES]
    for key in keys + ["rr", "ndcg@5"]:
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


# ─── separation diagnostics ─────────────────────────────────────────


def best_score_per_doc(hits: list[tuple[str, float]]) -> dict[str, float]:
    """Collapse chunk-level (doc_id, score) hits to each article's best score."""
    best: dict[str, float] = {}
    for doc_id, score in hits:
        if score > best.get(doc_id, float("-inf")):
            best[doc_id] = score
    return best


def score_margin(best: dict[str, float],
                 expected: set[str]) -> tuple[float | None, str | None]:
    """(best expected score - best other score, the closest other article).

    None when there is nothing to compare: no expected article was scored, or
    every scored article is expected.
    """
    right = [s for d, s in best.items() if d in expected]
    wrong = [(s, d) for d, s in best.items() if d not in expected]
    if not right or not wrong:
        return None, None
    wrong_score, wrong_doc = max(wrong)
    return max(right) - wrong_score, wrong_doc


def margin_by_intent(rows: list[dict]) -> dict[str, dict]:
    """Per-intent separation, narrowest median first."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("margin") is not None:
            groups[r["intent"]].append(r)
    out: dict[str, dict] = {}
    for intent, g in groups.items():
        margins = [r["margin"] for r in g]
        rival, rival_n = Counter(r["nearest_wrong_doc"] for r in g).most_common(1)[0]
        out[intent] = {
            "n": len(g),
            "median_margin": round(statistics.median(margins), 4),
            "min_margin": round(min(margins), 4),
            "thin_margin_n": sum(1 for m in margins if m < THIN_MARGIN),
            "wrong_ranked_first_n": sum(1 for m in margins if m < 0),
            "nearest_wrong_doc": rival,
            "nearest_wrong_doc_n": rival_n,
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["median_margin"]))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def article_overlap(chunks_by_doc: dict[str, list[list[float]]]) -> list[tuple[float, str, str]]:
    """Every article pair scored by its closest chunk pair, most similar first."""
    pairs = [
        (round(max(_cosine(x, y) for x in chunks_by_doc[a] for y in chunks_by_doc[b]), 4), a, b)
        for a, b in combinations(sorted(chunks_by_doc), 2)
    ]
    return sorted(pairs, reverse=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", default="evaluation/results/retrieval_eval")
    args = ap.parse_args(argv)

    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import Chroma

    from src.config import CHROMA_PATH, EMBEDDING_MODEL
    from src.ingest import normalise_any
    from src.logging_config import configure_logging
    from src.logging_store import new_run_id, set_run_id
    from src.retrieve import retrieve

    configure_logging()
    run_id = set_run_id(new_run_id("retrieval-eval"))
    gt = {g["ticket_id"]: g for g in json.loads(GT_PATH.read_text())}
    tickets = [t for t in json.loads(TICKETS_PATH.read_text()) if t["ticket_id"] in gt]
    titles = {d["doc_id"]: d["title"] for d in json.loads(DOCS_PATH.read_text())}

    # A second handle on the same persisted index, for the full ranking and the
    # stored embeddings. Production retrieval still goes through retrieve().
    store = Chroma(persist_directory=str(CHROMA_PATH),
                   embedding_function=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL))
    stored = store.get(include=["embeddings", "metadatas"])
    n_chunks = len(stored["ids"])

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with (out / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for raw in tickets:
            tid = raw["ticket_id"]
            ticket = normalise_any(raw)
            expected = gt[tid]["expected_doc_ids"]
            # Same query text the harness sends, so this measures production.
            ranked = [p.doc_id for p in retrieve(ticket.body, ticket_id=tid)]
            # Full ranking for the margin. The least similar chunks score just
            # below 0, and LangChain then warns with the ENTIRE result list —
            # megabytes per ticket. Comparing gaps is unaffected, so silence it.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                full = store.similarity_search_with_relevance_scores(ticket.body, k=n_chunks)
            margin, rival = score_margin(
                best_score_per_doc([(d.metadata["doc_id"], s) for d, s in full]), set(expected))
            row = {"ticket_id": tid, "intent": gt[tid]["intent"],
                   "expected_doc_ids": expected, "retrieved_doc_ids": ranked,
                   "margin": None if margin is None else round(margin, 4),
                   "nearest_wrong_doc": rival,
                   **score_ticket(ranked, expected)}
            rows.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()

    chunks_by_doc: dict[str, list[list[float]]] = defaultdict(list)
    for emb, meta in zip(stored["embeddings"], stored["metadatas"]):
        chunks_by_doc[meta["doc_id"]].append(list(emb))
    overlap = article_overlap(chunks_by_doc)

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
        "thin_margin_threshold": THIN_MARGIN,
        "by_intent_margin": margin_by_intent(rows),
        "article_overlap_median": overlap[len(overlap) // 2][0] if overlap else None,
        "article_overlap_top": [
            {"similarity": s, "a": a, "a_title": titles.get(a, ""),
             "b": b, "b_title": titles.get(b, "")}
            for s, a, b in overlap[:15]
        ],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))

    o = report["overall"]
    print(f"[retrieval] {o['n']} tickets  hit@1={o['hit@1']} hit@3={o['hit@3']} "
          f"hit@5={o['hit@5']}  recall@3={o['recall@3']} recall@5={o['recall@5']}  "
          f"MRR={o['mrr']}  NDCG@5={o['ndcg@5']}  "
          f"empty={report['empty_results']}")
    print("[retrieval] weakest intents by MRR:")
    for intent, s in list(report["by_intent"].items())[:6]:
        print(f"   {intent:26} n={s['n']:>3}  hit@1={s['hit@1']:.3f}  "
              f"MRR={s['mrr']:.3f}  NDCG@5={s['ndcg@5']:.3f}")
    print(f"[retrieval] narrowest separation (margin over the closest wrong article, "
          f"thin < {THIN_MARGIN}):")
    for intent, s in list(report["by_intent_margin"].items())[:6]:
        print(f"   {intent:26} n={s['n']:>3}  median={s['median_margin']:+.3f}  "
              f"thin={s['thin_margin_n']:>2}  wrong-first={s['wrong_ranked_first_n']}  "
              f"rival={s['nearest_wrong_doc']}")
    print("[retrieval] top-1 confusions (expected -> retrieved instead):")
    for c in report["top1_confusions"][:8]:
        print(f"   {c['count']:>3}x  {c['expected']} {c['expected_title'][:30]!r} -> "
              f"{c['retrieved']} {c['retrieved_title'][:30]!r}")
    print(f"[retrieval] most overlapping articles (median pair "
          f"{report['article_overlap_median']}):")
    for p in report["article_overlap_top"][:5]:
        print(f"   {p['similarity']:.3f}  {p['a']} <-> {p['b']}")
    print(f"[retrieval] wrote {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
