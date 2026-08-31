"""D-02 revisit check — measure all-MiniLM-L6-v2 hit rate on the same 357
answerable tickets used in the Q3 TF-IDF pilot.

Baseline to beat: TF-IDF hit@3 = 93.6% (workbooks/q3_findings.md).

Usage:
    python -m evaluation.d02_retrieval_check
    # writes evaluation/results/d02_dense_retrieval.json + prints summary
"""
from __future__ import annotations

import json
import warnings
from collections import defaultdict
from pathlib import Path

# Silence LangChain deprecation noise. Must happen before the langchain
# imports below or the warnings still fire during import — hence the E402
# noqa on those imports.
warnings.filterwarnings("ignore", category=DeprecationWarning)

from langchain_community.vectorstores import Chroma  # noqa: E402
from langchain_community.embeddings import HuggingFaceEmbeddings  # noqa: E402

from src.config import CHROMA_PATH, EMBEDDING_MODEL  # noqa: E402

ROOT = Path(__file__).parent.parent
DEV = ROOT / "data" / "development_tickets.json"
OUT = ROOT / "evaluation" / "results" / "d02_dense_retrieval.json"

TF_IDF_BASELINE = {"hit@1": 0.840, "hit@3": 0.936, "hit@5": 0.952}


def main() -> int:
    print("[d02] loading tickets")
    tix = json.loads(DEV.read_text())
    answerable = [t for t in tix if t["labels"]["answerable_from_docs"]]
    print(f"     {len(answerable)} answerable tickets")

    print("[d02] loading persisted Chroma index")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    store = Chroma(persist_directory=str(CHROMA_PATH), embedding_function=embeddings)

    print("[d02] retrieving top-5 for each ticket")
    per_ticket = []
    h1 = h3 = h5 = 0
    for i, t in enumerate(answerable):
        if i % 50 == 0:
            print(f"     {i}/{len(answerable)}")
        expected = set(t["labels"]["expected_doc_ids"])
        # top-K by unique doc_id (walk hits until we accumulate K distinct docs)
        hits = store.similarity_search(t["body"], k=15)
        seen: list[str] = []
        for h in hits:
            did = h.metadata.get("doc_id")
            if did and did not in seen:
                seen.append(did)
            if len(seen) >= 5:
                break
        r1 = int(bool(set(seen[:1]) & expected))
        r3 = int(bool(set(seen[:3]) & expected))
        r5 = int(bool(set(seen[:5]) & expected))
        h1 += r1
        h3 += r3
        h5 += r5
        per_ticket.append({
            "ticket_id": t["ticket_id"],
            "intent": t["labels"]["intent"],
            "channel": t["channel"],
            "language_fluency": t["language_fluency"],
            "customer_region": t["customer_region"],
            "customer_tier": t["customer_tier"],
            "expected": list(expected),
            "top5": seen,
            "h1": r1, "h3": r3, "h5": r5,
        })

    n = len(answerable)
    overall = {
        "n": n,
        "hit@1": h1 / n,
        "hit@3": h3 / n,
        "hit@5": h5 / n,
    }

    def segment_by(field: str) -> dict:
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in per_ticket:
            groups[row[field]].append(row)
        return {
            k: {
                "n": len(rows),
                "hit@1": sum(r["h1"] for r in rows) / len(rows),
                "hit@3": sum(r["h3"] for r in rows) / len(rows),
                "hit@5": sum(r["h5"] for r in rows) / len(rows),
            }
            for k, rows in groups.items()
        }

    result = {
        "overall": overall,
        "baseline_tfidf": TF_IDF_BASELINE,
        "delta_vs_tfidf": {
            k: overall[k] - TF_IDF_BASELINE[k]
            for k in ("hit@1", "hit@3", "hit@5")
        },
        "by_intent": segment_by("intent"),
        "by_channel": segment_by("channel"),
        "by_language_fluency": segment_by("language_fluency"),
        "by_customer_region": segment_by("customer_region"),
        "by_customer_tier": segment_by("customer_tier"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    print(f"[d02] wrote {OUT}")

    print("\n" + "=" * 60)
    print("DENSE (all-MiniLM-L6-v2)  vs  TF-IDF baseline")
    print("=" * 60)
    for k in ("hit@1", "hit@3", "hit@5"):
        d = overall[k]
        b = TF_IDF_BASELINE[k]
        delta = d - b
        sign = "+" if delta >= 0 else ""
        print(f"  {k}: dense {d:.3f}   tfidf {b:.3f}   delta {sign}{delta:+.3f}")

    print("\n" + "=" * 60)
    print("D-02 REVISIT VERDICT")
    print("=" * 60)
    dense_h3 = overall["hit@3"]
    tfidf_h3 = TF_IDF_BASELINE["hit@3"]
    if dense_h3 >= tfidf_h3:
        print(f"  Dense hit@3 ({dense_h3:.3f}) matches or beats TF-IDF ({tfidf_h3:.3f}).")
        print("  D-02 stays as-is: all-MiniLM-L6-v2 is a valid choice.")
    elif dense_h3 >= tfidf_h3 - 0.03:
        print(f"  Dense hit@3 ({dense_h3:.3f}) within 3pp of TF-IDF ({tfidf_h3:.3f}).")
        print("  D-02 stays as-is with a note.")
        print("  Semantic search buys us nothing on this corpus but doesn't hurt.")
    else:
        print(f"  Dense hit@3 ({dense_h3:.3f}) UNDER-performs TF-IDF ({tfidf_h3:.3f}) by >3pp.")
        print("  D-02 needs a supersession ADR.")
        print("  Options: BGE embedder, hybrid dense+sparse, TF-IDF fallback.")

    print("\n" + "=" * 60)
    print("PER-INTENT hit@3 (weakest 5)")
    print("=" * 60)
    weakest = sorted(result["by_intent"].items(), key=lambda x: x[1]["hit@3"])[:5]
    for intent, stats in weakest:
        print(f"  {intent:<28} n={stats['n']:>3}  hit@3={stats['hit@3']:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
