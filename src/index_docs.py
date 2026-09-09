"""One-time indexer for the 29 knowledge-base articles.

Runs the initial Chroma index. Not part of the request path.

Chunking strategy: fixed 800/120 (per D-04 provisional; final ADR at B-08).
Each chunk is embedded together with its article title and category, so the
retriever sees "**Resolving container health check failures.** [chunk]"
rather than the chunk alone. This is B-30 — the pack's Dataset Guide notes
that customers phrase problems unlike article titles (EV-I2), and folding
the title into the embedded text is the cheapest available lever on top-3
hit rate. Measured under B-30 against the same 357 answerable dev tickets
used in the Q3 pilot and the D-02 revisit.

Two versions of the passage are stored:
  - the text that gets embedded (title + category + chunk)
  - the original chunk (stored in metadata as `chunk_text`) so downstream
    code that only wants the raw passage can still get it.

Usage:
    python -m src.index_docs

Idempotent: re-running rebuilds the index from scratch.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

from src.config import CHROMA_PATH, EMBEDDING_MODEL
from src.logging_config import configure_logging

DATA_PATH = Path(__file__).parent.parent / "data" / "documentation.json"

# Distance metric for the Chroma collection (D-02a). NOT env-configurable on
# purpose: RETRIEVAL_THRESHOLD is calibrated against this metric's score scale,
# so letting the two drift apart independently is precisely the defect D-02a
# exists to prevent. Changing this requires re-running the threshold sweep.
#
# Without it, Chroma defaults to l2 and LangChain scores with
# `1.0 - distance / sqrt(2)` — a formula for normalised vectors applied to
# un-normalised MiniLM output. That produced scores from -0.094 to 0.650
# (LangChain warns "Relevance scores must be between 0 and 1"), against which
# the 0.35 threshold cut 42% of correct answers. See D-02a for the measurement.
DISTANCE_SPACE = "cosine"


def _annotate_chunk(title: str, category: str, chunk: str) -> str:
    """Prepend the article title (bold) and category to the chunk before embedding.

    The formatting choice — Markdown-style bold heading + parenthesised
    category — is deliberate. Both live inside the same passage's embedded
    text, so the meaning-based search sees title + category as an implicit
    heading for the chunk. The Markdown bold marks it as a heading to any
    downstream reader (the generator LLM at B-11, a human debugger, the
    groundedness check at D-06) without adding any structural cost.
    """
    return f"**{title}** ({category})\n\n{chunk}"


def main() -> int:
    configure_logging()
    if not DATA_PATH.exists():
        print(f"[index_docs] documentation.json not found at {DATA_PATH}")
        return 1

    docs = json.loads(DATA_PATH.read_text())
    print(f"[index_docs] loaded {len(docs)} articles")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=120,
        # Prefer to split on headings > paragraphs > sentences
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
    )

    texts: list[str] = []
    metadatas: list[dict] = []
    for doc in docs:
        # Real field name is doc_id (Setup Guide example had a typo — 'id')
        for i, chunk in enumerate(splitter.split_text(doc["content"])):
            annotated = _annotate_chunk(doc["title"], doc["category"], chunk)
            texts.append(annotated)
            metadatas.append({
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "category": doc["category"],
                "chunk_index": i,
                # Preserve the raw chunk so a downstream consumer that wants
                # ONLY the passage body (without the title header prepended by
                # B-30) can retrieve it from metadata.
                "chunk_text": chunk,
            })

    # Wipe existing index so re-runs are clean
    if CHROMA_PATH.exists():
        shutil.rmtree(CHROMA_PATH)
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    Chroma.from_texts(
        texts=texts,
        metadatas=metadatas,
        embedding=embeddings,
        persist_directory=str(CHROMA_PATH),
        collection_metadata={"hnsw:space": DISTANCE_SPACE},  # D-02a
    )
    # NOTE: store.persist() was a no-op deprecation on chromadb 0.4.22 —
    # persistence is automatic when persist_directory is passed to Chroma.
    # Removed to avoid the warning. Re-add if we upgrade to a chromadb
    # release that reintroduces manual persistence.

    print(
        f"[index_docs] stored {len(texts)} passages "
        f"from {len(docs)} articles at {CHROMA_PATH} "
        f"(title + category prepended per B-30)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
