"""Can retrieval signals alone tell an answerable ticket from an unanswerable one?

Satisfies: nothing in production. Evidence for the answerability question D-05b
           left open ("answerability, not confidence, is the binding constraint")
           and for D-09, which records what was decided from it.
Cites:     D-02a (a non-empty passage list is not evidence of answerability),
           D-05b (17 of 18 false positives were answerable_from_docs=false).

The 80-ticket local run (b21_local_80_20260919) sent 13 replies to tickets the
labels say the documentation cannot answer. A gate that holds those tickets
BEFORE generation would need a signal the pipeline already has, costs no model
call and separates the two groups. This measures whether such a signal exists.

Features, all available at inference (no labels):
  dense_top      best chunk relevance score (the retriever's own score)
  dense_margin   best article score minus the second-best article's
  dense_n_above  chunks in the top 5 clearing RETRIEVAL_THRESHOLD
  bm25_top       best BM25 chunk score (lexical match)
  bm25_margin    best BM25 article score minus the second-best article's
  agree          1 when dense and BM25 rank the same article first

Each is scored by ROC AUC against labels.answerable_from_docs on the 500 dev
tickets, then a logistic regression on all six is scored by 5-fold cross-
validation on dev, then trained on dev and tested once on the 80 validation
tickets. The operating point is chosen on dev: the score that keeps 95% of
answerable tickets (a gate that holds more than 1 in 20 good tickets costs more
coverage than it buys). With --run, that dev-chosen gate is replayed over a
harness run's sends to count the wrong sends it would hold and the correct sends
it would lose.

Also measured, because the same full ranking gives it for free: retrieval hit@k
on answerable dev tickets for the body alone vs subject + body, and for dense,
BM25 and reciprocal-rank fusion of the two.

No model calls. Reads the Chroma index directly, not through retrieve(), so no
decision-log rows are written. Deterministic.

Usage:
    python -m evaluation.answerability_probe \\
        --run evaluation/results/b21_local_80_20260919 \\
        --output evaluation/results/answerability_probe_20260920
"""
from __future__ import annotations

import argparse
import json
import math
import re
import warnings
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np

_ROOT = Path(__file__).parent.parent
DEV_PATH = _ROOT / "data" / "development_tickets.json"
VAL_PATH = _ROOT / "data" / "validation_tickets.json"

FEATURES = ("dense_top", "dense_margin", "dense_n_above", "bm25_top", "bm25_margin", "agree")
KEEP_ANSWERABLE = 0.95  # the gate may hold at most 5% of answerable tickets
RRF_K = 60              # the constant from Cormack et al. (2009); not tuned here
HIT_K = (1, 3, 5)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 over the index's chunks. k1=1.5, b=0.75, the usual defaults."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.tokens = [tokenize(d) for d in docs]
        self.k1, self.b = k1, b
        self.avgdl = sum(len(t) for t in self.tokens) / len(self.tokens)
        df: Counter = Counter(term for t in self.tokens for term in set(t))
        n = len(self.tokens)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self.tf = [Counter(t) for t in self.tokens]

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, toks in zip(self.tf, self.tokens):
            norm = self.k1 * (1 - self.b + self.b * len(toks) / self.avgdl)
            out.append(sum(self.idf.get(t, 0.0) * tf[t] * (self.k1 + 1) / (tf[t] + norm)
                           for t in q if t in tf))
        return out


def best_per_doc(pairs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Collapse chunk scores to one score per article (its best chunk), best first."""
    best: dict[str, float] = {}
    for doc, score in pairs:
        best[doc] = max(score, best.get(doc, -math.inf))
    return sorted(best.items(), key=lambda x: x[1], reverse=True)


def margin(ranked_docs: list[tuple[str, float]]) -> float:
    return ranked_docs[0][1] - ranked_docs[1][1] if len(ranked_docs) > 1 else 0.0


def rrf(*rankings: list[str]) -> list[str]:
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, 1):
            score[doc] = score.get(doc, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(score, key=score.get, reverse=True)


def query_text(ticket: dict, with_subject: bool) -> str:
    subject = (ticket.get("subject") or "").strip()
    return f"{subject}\n\n{ticket['body']}" if with_subject and subject else ticket["body"]


def auc(y: np.ndarray, s: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return round(float(roc_auc_score(y, s)), 4)


def gate_threshold(y: np.ndarray, s: np.ndarray) -> float:
    """The highest score threshold that still keeps KEEP_ANSWERABLE of answerable tickets."""
    answerable = np.sort(s[y == 1])
    return float(answerable[int(math.floor((1 - KEEP_ANSWERABLE) * len(answerable)))])


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", default="evaluation/results/answerability_probe")
    ap.add_argument("--run", help="harness output dir whose sends the gate is replayed over")
    args = ap.parse_args(argv)

    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import Chroma
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from src.config import CHROMA_PATH, EMBEDDING_MODEL, RETRIEVAL_THRESHOLD

    store = Chroma(persist_directory=str(CHROMA_PATH),
                   embedding_function=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL))
    stored = store.get(include=["documents", "metadatas"])
    chunk_docs = [m["doc_id"] for m in stored["metadatas"]]
    bm25 = BM25(stored["documents"])
    n_chunks = len(chunk_docs)

    def probe(ticket: dict, with_subject: bool) -> dict:
        q = query_text(ticket, with_subject)
        # The least similar chunks score just below 0 and LangChain then warns
        # with the entire result list; ranks and gaps are unaffected.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            dense = [(d.metadata["doc_id"], s)
                     for d, s in store.similarity_search_with_relevance_scores(q, k=n_chunks)]
        lexical = sorted(zip(chunk_docs, bm25.scores(q)), key=lambda x: x[1], reverse=True)
        dense_docs, lex_docs = best_per_doc(dense), best_per_doc(lexical)
        return {
            "features": {
                "dense_top": dense[0][1],
                "dense_margin": margin(dense_docs),
                "dense_n_above": sum(1 for _, s in dense[:5] if s >= RETRIEVAL_THRESHOLD),
                "bm25_top": lexical[0][1],
                "bm25_margin": margin(lex_docs),
                "agree": float(dense_docs[0][0] == lex_docs[0][0]),
            },
            "rankings": {
                "dense": [d for d, _ in dense_docs],
                "bm25": [d for d, _ in lex_docs],
                "rrf": rrf([d for d, _ in dense_docs], [d for d, _ in lex_docs]),
            },
        }

    dev = json.loads(DEV_PATH.read_text())
    val = json.loads(VAL_PATH.read_text())
    report: dict = {"n_chunks": n_chunks, "retrieval_threshold": RETRIEVAL_THRESHOLD,
                    "keep_answerable": KEEP_ANSWERABLE, "query_modes": {}}

    for mode, with_subject in (("body", False), ("subject_body", True)):
        dev_p = [probe(t, with_subject) for t in dev]
        val_p = [probe(t, with_subject) for t in val]
        X = np.array([[p["features"][f] for f in FEATURES] for p in dev_p])
        y = np.array([int(t["labels"]["answerable_from_docs"]) for t in dev])
        Xv = np.array([[p["features"][f] for f in FEATURES] for p in val_p])
        yv = np.array([int(t["labels"]["answerable_from_docs"]) for t in val])

        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
        cv_scores = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
        model.fit(X, y)
        dev_scores = model.predict_proba(X)[:, 1]
        val_scores = model.predict_proba(Xv)[:, 1]
        cut = gate_threshold(y, cv_scores)

        # Retrieval quality: answerable dev tickets, article-level hit@k.
        hits: dict[str, dict[str, float]] = {}
        answerable = [(t, p) for t, p in zip(dev, dev_p) if t["labels"]["answerable_from_docs"]]
        for method in ("dense", "bm25", "rrf"):
            hits[method] = {
                f"hit@{k}": round(sum(bool(set(p["rankings"][method][:k])
                                           & set(t["labels"]["expected_doc_ids"]))
                                      for t, p in answerable) / len(answerable), 4)
                for k in HIT_K}

        held_val = val_scores < cut
        entry = {
            "dev_n": len(dev), "dev_answerable": int(y.sum()),
            "single_feature_auc_dev": {f: auc(y, X[:, i]) for i, f in enumerate(FEATURES)},
            "logistic_auc_dev_cv": auc(y, cv_scores),
            "logistic_auc_val": auc(yv, val_scores),
            "gate": {
                "threshold": round(cut, 4),
                "dev_cv_unanswerable_held": round(float((cv_scores[y == 0] < cut).mean()), 4),
                "val_answerable_held": int((held_val & (yv == 1)).sum()),
                "val_unanswerable_held": int((held_val & (yv == 0)).sum()),
                "val_answerable": int(yv.sum()), "val_unanswerable": int((yv == 0).sum()),
            },
            "retrieval_hit_answerable_dev": {"n": len(answerable), **hits},
            "coefficients": dict(zip(FEATURES, np.round(
                model.named_steps["logisticregression"].coef_[0], 4).tolist())),
        }
        if args.run:
            rows = {json.loads(line)["ticket_id"]: json.loads(line)
                    for line in (Path(args.run) / "results.jsonl").open()}
            held = {t["ticket_id"] for t, h in zip(val, held_val) if h}
            sent = [tid for tid, r in rows.items() if r.get("decision") == "auto_respond"]
            labels = {t["ticket_id"]: t["labels"] for t in val}
            entry["replay_over_run"] = {
                "run": str(args.run),
                "sent": len(sent),
                "wrong_sends_held": sum(1 for tid in sent if tid in held
                                        and labels[tid]["expected_route"] != "auto_respond"),
                "wrong_sends": sum(1 for tid in sent
                                   if labels[tid]["expected_route"] != "auto_respond"),
                "correct_sends_lost": sum(1 for tid in sent if tid in held
                                          and labels[tid]["expected_route"] == "auto_respond"),
                "correct_sends": sum(1 for tid in sent
                                     if labels[tid]["expected_route"] == "auto_respond"),
            }
        report["query_modes"][mode] = entry
        _ = dev_scores  # in-sample scores are not reported; CV scores are the honest ones

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
