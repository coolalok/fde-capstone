"""retrieve.py — search the indexed help-article corpus for relevant passages.

Satisfies: FR-06 (ranked passages with doc_id + score),
           FR-07 (empty list when nothing crosses RETRIEVAL_THRESHOLD),
           FR-08 (indexed at build time — src/index_docs.py, per D-04).
Writes:    one decision log row per call with sources_used = [{doc_id, score}].

Design decisions worth reading:

- The Chroma store and the embedder are opened lazily and cached at
  module scope. Reopening on every ticket would dominate the harness's
  wall-clock (embedder load is ~1-2 s cold). One process, one open
  handle — reconciles with FR-08 (index built once, read many).

- `search` is a pluggable callable so tests never touch Chroma or the
  network. Production wires `_chroma_search`; tests pass a stub.

- Score semantics: relevance scores from LangChain's
  `similarity_search_with_relevance_scores`, in [0, 1] with higher =
  better. `RETRIEVAL_THRESHOLD` from src/config.py (default 0.35) is
  read as a floor — passages below it are dropped.

  Those scores are only in [0, 1] because the index is built in cosine
  space (D-02a). Chroma's default is l2, and LangChain then scores with
  `1.0 - distance / sqrt(2)`, which on un-normalised MiniLM vectors
  returned -0.094 to 0.650 — so the same 0.35 floor discarded 42% of
  correct answers. `_assert_distance_space` logs an error at open time
  if the index on disk was not built in the expected space.

- Post-B-30, the text embedded for each chunk begins with
  `**<title>** (<category>)`; the raw chunk is preserved in the
  metadata under `chunk_text`. Passage.text is what the retriever
  returned (with header); Passage.chunk_text is the raw body. The
  generator (B-11) can pick either; the guardrail (B-13 grounding
  check) reads Passage.text so its citation-matching sees the header.

- Empty query, threshold-filtered-to-empty, index missing, embedder
  fails — all return `[]` and log the outcome. Never raises. A11.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from src.config import CHROMA_PATH, EMBEDDING_MODEL, RETRIEVAL_THRESHOLD, RETRIEVAL_TOP_K
from src.index_docs import DISTANCE_SPACE
from src.logging_store import log_decision
from src.schema import Passage

logger = logging.getLogger(__name__)


# ─── module-level lazy singletons ─────────────────────────────────────
#
# The embedder and vector store are expensive to construct. Cache them for
# the process lifetime. Tests that repoint CHROMA_PATH via monkeypatch also
# clear these caches (see the `_clear_cache` helper).
_STORE = None
_EMBEDDINGS = None


def _chroma_search(query: str, k: int) -> list[tuple[str, dict, float]]:
    """Query the persisted Chroma store. Raises on any I/O or model failure.

    The caller (retrieve()) catches whatever this raises and returns [] with
    an entry in the decision log — FR-05 style graceful degradation.
    """
    global _STORE, _EMBEDDINGS
    if _STORE is None:
        # Imported lazily so unit tests don't need the langchain packages.
        from langchain_community.vectorstores import Chroma
        from langchain_community.embeddings import HuggingFaceEmbeddings

        _EMBEDDINGS = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        _STORE = Chroma(
            persist_directory=str(CHROMA_PATH),
            embedding_function=_EMBEDDINGS,
        )
        _assert_distance_space(_STORE)

    hits = _STORE.similarity_search_with_relevance_scores(query, k=k)
    return [(doc.page_content, dict(doc.metadata), float(score)) for doc, score in hits]


def _assert_distance_space(store) -> None:
    """Warn loudly if the index was not built in the metric the threshold assumes.

    RETRIEVAL_THRESHOLD is calibrated against cosine relevance scores (D-02a).
    An index built without `hnsw:space` falls back to l2, whose scores sit on a
    different scale — the same 0.35 floor then discards roughly 42% of correct
    answers, silently, with no error anywhere. This check makes the mismatch
    visible at open time instead of showing up as a bad hit rate at B-21.
    """
    try:
        metadata = store._collection.metadata or {}
        space = metadata.get("hnsw:space")
    except Exception:  # pragma: no cover — never let a diagnostic break retrieval
        return
    if space != DISTANCE_SPACE:
        logger.error(
            "retrieve.distance_space_mismatch",
            extra={
                "expected": DISTANCE_SPACE,
                "found": space,
                "remedy": "rebuild the index: python -m src.index_docs",
            },
        )


def _clear_cache() -> None:
    """Test helper — drops the cached store so a new CHROMA_PATH is picked up."""
    global _STORE, _EMBEDDINGS
    _STORE = None
    _EMBEDDINGS = None


# Callable signature: (query, top_k) -> list of (text, metadata, score) tuples.
SearchFn = Callable[[str, int], list[tuple[str, dict, float]]]


def retrieve(
    query: str,
    *,
    ticket_id: str,
    top_k: int = RETRIEVAL_TOP_K,
    threshold: float = RETRIEVAL_THRESHOLD,
    search: Optional[SearchFn] = None,
) -> list[Passage]:
    """Return ranked passages for `query`, filtered by relevance threshold.

    Per FR-06: each Passage carries doc_id + score. Per FR-07: an empty
    list is a valid, deliberate answer when nothing crosses the threshold.
    Per FR-08: the index is built by src/index_docs.py, never here.

    Args:
        query: the customer's ticket text (typically Ticket.body).
        top_k: how many passages to fetch from Chroma before filtering.
        threshold: minimum relevance score in [0, 1] a passage must clear.
        ticket_id: for the decision log. Required — a row logged without one
            reconciles as an extra empty-id ticket and fails A8, so the
            signature enforces what used to be a convention.
        search: pluggable search callable for tests. Production leaves this
            None and uses _chroma_search.

    Returns:
        list[Passage], ordered by score descending. Empty on: empty/blank
        query, threshold filtering all results, or any search failure. Never
        raises.
    """
    caller = search or _chroma_search

    if not query or not query.strip():
        _log_empty(ticket_id, "empty_query", threshold, top_k)
        return []

    # The search call AND the passage building both sit inside the try. Building
    # is not obviously fallible, but it reads attacker-adjacent data (whatever
    # is in the index metadata), and a single malformed value — a chunk_index
    # of "two", say — used to raise straight out of a function whose docstring
    # promises it never does. A11 is a promise about the whole function.
    try:
        raw_hits = caller(query, top_k)

        # Sort defensively rather than trusting the backend's ordering. Chroma
        # does return best-first, but the docstring promises score-descending
        # output and a stub or a future backend need not honour it. Sorting
        # here also removes the old `break`, which silently dropped every
        # passage after the first below-threshold one — on unsorted input that
        # discarded good hits.
        ranked = sorted(raw_hits, key=lambda h: h[2], reverse=True)

        passages: list[Passage] = []
        for text, metadata, score in ranked:
            if score < threshold:
                continue
            doc_id = str(metadata.get("doc_id", ""))
            if not doc_id:
                # A passage with no doc_id cannot be cited, and A6 requires
                # every citation to resolve to a retrieved passage. Dropping it
                # is safer than emitting an uncitable source.
                logger.warning(
                    "retrieve.passage_missing_doc_id",
                    extra={"ticket_id": ticket_id, "score": score},
                )
                continue
            passages.append(
                Passage(
                    doc_id=doc_id,
                    score=max(0.0, min(1.0, score)),
                    text=text,
                    title=str(metadata.get("title", "")),
                    category=str(metadata.get("category", "")),
                    chunk_index=_safe_int(metadata.get("chunk_index")),
                    chunk_text=str(metadata.get("chunk_text", "")),
                )
            )
    except Exception as exc:  # broad on purpose — FR-05/A11 pattern
        logger.warning(
            "retrieve.search_failure",
            extra={
                "ticket_id": ticket_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        _log_empty(
            ticket_id,
            f"search_error:{type(exc).__name__}",
            threshold,
            top_k,
        )
        return []

    action = "retrieved" if passages else "empty"
    reason = (
        f"n_hits={len(raw_hits)} n_above_threshold={len(passages)} threshold={threshold}"
    )
    log_decision(
        ticket_id=ticket_id,
        stage="retrieval",
        action_taken=action,
        reason=reason,
        prediction=f"top_doc_id={passages[0].doc_id if passages else 'none'}",
        confidence=passages[0].score if passages else 0.0,
        sources_used=[{"doc_id": p.doc_id, "score": p.score} for p in passages],
        threshold_applied=float(threshold),
        model_name=EMBEDDING_MODEL,
        requirement_ids=["FR-06", "FR-07", "FR-08"],
        input_summary=f"query_len={len(query)} top_k={top_k}",
    )
    return passages


def _safe_int(value: object, default: int = 0) -> int:
    """int() that never raises. A malformed chunk_index is cosmetic — it must
    not cost the ticket its passages."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _log_empty(ticket_id: str, reason: str, threshold: float, top_k: int) -> None:
    """Log an empty-list return so the router still sees a row."""
    log_decision(
        ticket_id=ticket_id,
        stage="retrieval",
        action_taken="empty",
        reason=reason,
        prediction="none",
        confidence=0.0,
        sources_used=[],
        threshold_applied=float(threshold),
        model_name=EMBEDDING_MODEL,
        requirement_ids=["FR-06", "FR-07", "FR-08"],
        input_summary=f"top_k={top_k}",
    )
