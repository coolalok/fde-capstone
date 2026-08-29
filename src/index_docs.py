"""One-time indexer for the 29 knowledge-base articles.

Runs the initial Chroma index. Not part of the request path.
Chunking strategy is fixed 800/120 for the initial setup; the D-04 ADR
will revisit this in Week 2 against section-aware chunking on a measured
hit-rate basis. Do not treat 800/120 as the final choice.

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

DATA_PATH = Path(__file__).parent.parent / "data" / "documentation.json"


def main() -> int:
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
            texts.append(chunk)
            metadatas.append({
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "category": doc["category"],
                "chunk_index": i,
            })

    # Wipe existing index so re-runs are clean
    if CHROMA_PATH.exists():
        shutil.rmtree(CHROMA_PATH)
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    store = Chroma.from_texts(
        texts=texts,
        metadatas=metadatas,
        embedding=embeddings,
        persist_directory=str(CHROMA_PATH),
    )
    store.persist()

    print(f"[index_docs] stored {len(texts)} passages from {len(docs)} articles at {CHROMA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
