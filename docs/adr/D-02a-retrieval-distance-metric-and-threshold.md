# D-02a — Retrieval distance metric and relevance threshold (extends D-02)

**Status:** Accepted. Extends D-02.
**Date:** 2026-09-03
**Decider:** Alok Kulkarni
**Constrains:** FR-06, FR-07, NFR-01a (context relevance), A4, A6
**Affects:** `src/index_docs.py` (`DISTANCE_SPACE`), `src/retrieve.py`, `src/config.py` (`RETRIEVAL_THRESHOLD`), `evaluation/d02_retrieval_check.py`

## Context

D-02 chose `all-MiniLM-L6-v2` as the embedding model on a measured top-3 hit rate. It said nothing about two settings that turn out to matter as much as the model choice:

1. **Which distance metric the Chroma collection is built with.**
2. **What relevance score a passage must clear to be returned** (`RETRIEVAL_THRESHOLD`).

Both were left at defaults. `RETRIEVAL_THRESHOLD=0.35` came from `.env.example` as an illustrative placeholder and was never calibrated — the same class of placeholder the Project Brief flagged for the confidence threshold ("the number is yours to set and yours to defend", D-05).

The two settings are not independent, and that is what caused the defect. `src/index_docs.py` built the collection without `hnsw:space`, so Chroma defaulted to **l2**. LangChain then selects `_euclidean_relevance_score_fn`, which computes `1.0 - distance / sqrt(2)` — a formula that assumes normalised vectors, applied to un-normalised MiniLM output. The resulting "relevance scores" ran **-0.094 to 0.650** (mean 0.373). LangChain itself warns at runtime: `UserWarning: Relevance scores must be between 0 and 1`.

A 0.35 floor sits just below the *mean* of that distribution. Measured on the 357 answerable dev tickets:

| Configuration | hit@3 | Tickets returning zero passages |
|---|---|---|
| No threshold (what B-30 measured) | 94.1% | 0/357 |
| Shipped config: l2 scores, 0.35 floor | **52.4%** | **151/357** |

NFR-01a v3 requires a 90% aggregate floor. The shipped configuration missed it by roughly 38 points. DEV-0008 — the happy-path case in PR-CLASSIFY-01 — was one of the 151; its correct article scored 0.245.

This went unnoticed because the measurement never covered the shipped path. `evaluation/d02_retrieval_check.py` calls `store.similarity_search(body, k=15)`, which returns documents ranked by raw distance with **no relevance scores and no threshold**. Neither measurement script references `RETRIEVAL_THRESHOLD`. So NFR-01a's floors were established on a code path production does not use.

## Options considered

**A. Keep l2, lower the threshold to fit the observed scale (~0.10).**
Restores the hit rate without re-indexing. But it keeps a score scale that LangChain itself flags as invalid, can go negative, and has no interpretable meaning — "0.10 relevance" would be a number nobody could reason about, and the next person to touch it would face the same trap. Treats the symptom.

**B. Build the collection in cosine space and re-calibrate the threshold.**
One argument to `Chroma.from_texts` plus a re-index (59 chunks, seconds). Scores land in a genuine [0, 1] range, the LangChain warning goes away, and the threshold becomes a number that means what it appears to mean.

**C. Normalise the embeddings instead (`encode_kwargs={"normalize_embeddings": True}`), keeping l2.**
Also produces a sane scale, since l2 on unit vectors is monotonic with cosine. But it changes the vectors themselves, which invalidates the D-02 and B-30 comparisons directly, and it fixes the scale by coincidence of geometry rather than by naming the metric we actually want.

## Chosen

**Option B — cosine space, threshold set by measurement at 0.25.**

- `src/index_docs.py` builds with `collection_metadata={"hnsw:space": "cosine"}`, exposed as the module constant `DISTANCE_SPACE`.
- `RETRIEVAL_THRESHOLD` default moves from 0.35 to **0.25**.
- `DISTANCE_SPACE` is deliberately **not** environment-configurable, unlike the threshold. The threshold's calibration is only valid for a given metric; letting the two drift independently through env vars is exactly how this defect happened.
- `src/retrieve.py._assert_distance_space` logs an ERROR at store-open time if the index on disk was not built in the expected space, so the mismatch is visible immediately rather than as a bad hit rate at B-21.

## Rationale

Measured through `retrieve()` itself — the production path, not the measurement shortcut — on the 357 answerable and 143 non-answerable dev tickets:

| Threshold | hit@3 (answerable) | Intent classes ≥90% | Non-answerable returning zero |
|---|---|---|---|
| 0.00 | 94.1% | 15/20 | 0/143 (0.0%) |
| 0.20 | 94.1% | 15/20 | 8/143 (5.6%) |
| **0.25** | **94.1%** | **15/20** | **14/143 (9.8%)** |
| 0.30 | 92.7% | 15/20 | 21/143 (14.7%) |
| 0.35 | 90.8% | 13/20 | 27/143 (18.9%) |
| 0.40 | 85.2% | — | 30/143 (21.0%) |

0.25 sits exactly at the recall ceiling — identical to applying no threshold at all — while still silencing about one in ten non-answerable tickets. Above it, recall falls faster than precision rises: going from 0.25 to 0.35 buys 13 more correctly-silent tickets and costs 3.3 points of aggregate hit rate plus two whole intent classes.

The deeper reason to keep the threshold low is that **it is a weak precision instrument and was never the right place to decide answerability**. Even at 0.40 it silences only 21% of non-answerable tickets, at a cost of 9 points of recall. Deciding "should we answer this at all?" belongs to the router — classifier confidence (D-05), the `must_not_auto_respond` types (EV-DATA-10), and the guardrails. The retrieval floor's only job is discarding obvious junk before the generator sees it. The 0.35 value was implicitly asking the threshold to do routing work.

## Consequences

- Positive: aggregate hit@3 goes from 52.4% to 94.1%; NFR-01a's aggregate 90% floor passes with 4 points of headroom instead of failing by 38.
- Positive: scores are interpretable, so the number in `.env` means what a reader assumes it means, and the LangChain range warning is gone.
- Positive: `_assert_distance_space` makes a recurrence loud instead of silent.
- Negative: **the index must be rebuilt** (`python -m src.index_docs`) for the threshold to be valid. An old l2 index plus the new 0.25 floor is a different, untested configuration — the guard exists for exactly this.
- Negative: at 0.25 only 14 of 143 non-answerable tickets return nothing, so the "retrieval found nothing" escalation signal is weak on its own. The router must not treat a non-empty passage list as evidence the ticket is answerable. B-15 needs this stated in its routing rules.
- **Open:** NFR-01a v3's *per-class* 90% floor still fails for 5 intent classes at any threshold (onboarding 80%, plus integration_help, deployment_failure, api_key_issue, webhook_issue). That is a ranking-quality gap, not a threshold gap — the ceiling at threshold 0.00 is the same 15/20. It is B-05's territory (PR-RETRIEVE-01 query rewriting), already flagged for onboarding in the Stage 5 log. This ADR does not close it.

## Evidence

- **B-30 / D-02 measurement** (`evaluation/results/`, `workbooks/b30_findings.md`) — the 94.1% no-threshold ceiling this ADR restores.
- **EV-I2** (Ines: customers phrase problems unlike article titles) — the reason retrieval recall is the metric that matters here, and why silently dropping 42% of correct answers is the worst available failure.
- **NFR-01a v3** — the 90% aggregate and 90% per-class floors this configuration is measured against.
- **LangChain `_euclidean_relevance_score_fn`** (`langchain_core/vectorstores.py`) — the `1.0 - distance / sqrt(2)` formula and its in-library range warning.

## Revisit trigger

- If a full validation run shows aggregate hit@3 below 90%, or the zero-passage rate on answerable tickets above 5%, re-run the sweep — the corpus or the embedding model has moved under the calibration.
- If `retrieve.distance_space_mismatch` ever appears in the logs, the index and the threshold have desynchronised; rebuild before trusting any retrieval metric from that run.
- If B-05's query rewriting lands, re-run this sweep: better ranking may move the optimum, since a rewrite that lifts weak intents could also raise their scores past a higher floor.
- If the router turns out to depend on empty retrieval as an escalation signal, revisit — that would argue for a higher floor and a different recall/precision balance than this ADR chose.

## Supersedes / superseded by

None. Extends D-02, which stays in force on the embedding-model choice.
