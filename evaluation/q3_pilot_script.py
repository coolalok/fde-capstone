"""Q3 retrieval pilot — settles the content-vs-findability question from discovery.

Cannot reach HuggingFace from this container, so uses TF-IDF (approximates
CloudServe's current keyword-based internal search per Ines's interview) and
BM25 (a stronger sparse-retrieval baseline). This is intentional: if TF-IDF
hits reliably, the content is fine and CloudServe just needed a better search
box. If it misses, retrieval needs semantic embeddings (validates the pack's
choice of sentence-transformers). Either result is decisive for the PRD.

Two chunking strategies × two retrievers × 357 answerable tickets.
Segmented by intent, channel, language_fluency, region, customer_tier.

Output: evaluation/results/q3_retrieval_pilot.json + stdout summary
"""
from __future__ import annotations

import json
import re
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA = Path("/tmp/capstone/FDE_Capstone_Complete/Capstone_Pack/05_Datasets")
OUT = Path("/home/claude/q3_results.json")

print("[q3] loading data")
docs = json.loads((DATA / "documentation.json").read_text())
tix = json.loads((DATA / "development_tickets.json").read_text())
print(f"     {len(docs)} articles · {len(tix)} tickets")


# ─── Chunking ────────────────────────────────────────────────────────────
def chunk_fixed(text: str, size: int = 800, overlap: int = 120) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks, step = [], size - overlap
    for i in range(0, len(text), step):
        piece = text[i : i + size]
        if piece.strip():
            chunks.append(piece)
        if i + size >= len(text):
            break
    return chunks


def chunk_section_aware(text: str, cap: int = 1500) -> list[str]:
    parts = re.split(r"\n(?=## )", text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= cap:
            chunks.append(p)
        else:
            for start in range(0, len(p), cap - 100):
                sub = p[start : start + cap]
                if sub.strip():
                    chunks.append(sub)
    return chunks


strategies = {
    "fixed_800_120": chunk_fixed,
    "section_aware": chunk_section_aware,
}


# ─── BM25 (Okapi) ─────────────────────────────────────────────────────────
def _tokenize(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", t.lower())


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [_tokenize(d) for d in docs]
        self.N = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / self.N
        self.freqs = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for d in self.docs:
            for term in set(d):
                df[term] += 1
        self.idf = {
            term: math.log((self.N - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }
        self.k1, self.b = k1, b

    def score_all(self, query: str) -> np.ndarray:
        q = _tokenize(query)
        scores = np.zeros(self.N)
        for term in q:
            if term not in self.idf:
                continue
            idf_t = self.idf[term]
            for i in range(self.N):
                f = self.freqs[i].get(term, 0)
                if f == 0:
                    continue
                dl = len(self.docs[i])
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[i] += idf_t * (f * (self.k1 + 1)) / denom
        return scores


# ─── Pilot ────────────────────────────────────────────────────────────────
answerable = [t for t in tix if t["labels"]["answerable_from_docs"]]
print(f"[q3] {len(answerable)} answerable tickets")
queries = [t["body"] for t in answerable]

results_per_config: dict = {}

for strategy_name, chunker in strategies.items():
    chunks: list[str] = []
    chunk_doc_ids: list[str] = []
    for d in docs:
        # Prepend title as context for retrieval — mirrors what a search box would surface
        title_prefix = f"{d['title']}\n"
        for piece in chunker(d["content"]):
            chunks.append(title_prefix + piece)
            chunk_doc_ids.append(d["doc_id"])
    print(f"\n[q3] === {strategy_name} · {len(chunks)} chunks ===")

    # ── TF-IDF ──
    vec = TfidfVectorizer(
        lowercase=True, ngram_range=(1, 2),
        min_df=1, max_df=0.95, sublinear_tf=True,
    )
    tfidf_docs = vec.fit_transform(chunks)
    tfidf_q = vec.transform(queries)
    sim_tfidf = cosine_similarity(tfidf_q, tfidf_docs)

    # ── BM25 ──
    bm25 = BM25(chunks)
    sim_bm25 = np.zeros((len(queries), len(chunks)))
    for i, q in enumerate(queries):
        sim_bm25[i] = bm25.score_all(q)

    for retriever_name, sim in [("tfidf", sim_tfidf), ("bm25", sim_bm25)]:
        def topk_docs(qi: int, k: int) -> list[str]:
            ranked = np.argsort(-sim[qi])
            seen: list[str] = []
            for ci in ranked:
                did = chunk_doc_ids[int(ci)]
                if did not in seen:
                    seen.append(did)
                if len(seen) >= k:
                    break
            return seen

        per_ticket = []
        h1 = h3 = h5 = 0
        for i, t in enumerate(answerable):
            expected = set(t["labels"]["expected_doc_ids"])
            top5 = topk_docs(i, 5)
            r1 = int(bool(set(top5[:1]) & expected))
            r3 = int(bool(set(top5[:3]) & expected))
            r5 = int(bool(set(top5[:5]) & expected))
            h1 += r1; h3 += r3; h5 += r5
            per_ticket.append({
                "ticket_id": t["ticket_id"],
                "intent": t["labels"]["intent"],
                "channel": t["channel"],
                "language_fluency": t["language_fluency"],
                "customer_region": t["customer_region"],
                "customer_tier": t["customer_tier"],
                "expected": list(expected),
                "top5": top5,
                "h1": r1, "h3": r3, "h5": r5,
            })

        n = len(answerable)
        overall = {
            "n": n,
            "n_chunks": len(chunks),
            "hit_at_1": h1 / n,
            "hit_at_3": h3 / n,
            "hit_at_5": h5 / n,
        }

        def by(field: str) -> dict:
            groups: dict[str, list[dict]] = defaultdict(list)
            for row in per_ticket:
                groups[row[field]].append(row)
            return {
                k: {
                    "n": len(rows),
                    "hit_at_1": sum(r["h1"] for r in rows) / len(rows),
                    "hit_at_3": sum(r["h3"] for r in rows) / len(rows),
                    "hit_at_5": sum(r["h5"] for r in rows) / len(rows),
                }
                for k, rows in groups.items()
            }

        seg = {
            "by_intent": by("intent"),
            "by_channel": by("channel"),
            "by_language_fluency": by("language_fluency"),
            "by_customer_region": by("customer_region"),
            "by_customer_tier": by("customer_tier"),
        }

        cfg_name = f"{strategy_name}_{retriever_name}"
        results_per_config[cfg_name] = {"overall": overall, "segments": seg}
        print(f"     {retriever_name:<6}  hit@1={overall['hit_at_1']:.3f}  hit@3={overall['hit_at_3']:.3f}  hit@5={overall['hit_at_5']:.3f}")

OUT.write_text(json.dumps(results_per_config, indent=2))
print(f"\n[q3] wrote {OUT}")

print("\n" + "=" * 60)
print("SUMMARY — hit rate on expected_doc_ids across 357 answerable tickets")
print("=" * 60)
print(f"{'config':<30} {'hit@1':>7} {'hit@3':>7} {'hit@5':>7}")
for name, r in results_per_config.items():
    o = r["overall"]
    print(f"{name:<30} {o['hit_at_1']:>7.3f} {o['hit_at_3']:>7.3f} {o['hit_at_5']:>7.3f}")

print("\n" + "=" * 60)
print("FAIRNESS SEGMENTS (best config, hit@3)")
print("=" * 60)
best_name = max(results_per_config, key=lambda k: results_per_config[k]["overall"]["hit_at_3"])
best = results_per_config[best_name]
print(f"Best config: {best_name}\n")

for seg_name, buckets in best["segments"].items():
    print(f"--- {seg_name} ---")
    for k in sorted(buckets):
        v = buckets[k]
        print(f"  {k:<22} n={v['n']:>3}  hit@3={v['hit_at_3']:.3f}")
    print()
