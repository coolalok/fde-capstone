# D-02 — Embedding model

**Status:** Accepted
**Date:** 2026-08-30
**Decider:** Alok Kulkarni
**Constrains:** FR-06, FR-07; NFR-01a, NFR-08
**Affects:** `src/index_docs.py`, `src/retrieve.py`, `src/config.py`

## Context

The 29-article corpus needs to be embedded once (index-build time) so that ticket bodies at inference can be matched by cosine similarity to the passage chunks. The embedder must be free, runnable locally without a GPU, small enough to load in seconds, and produce embeddings whose retrieval hit rate matches or beats the TF-IDF baseline of 93.6% top-3 established in the Q3 pilot.

## Options considered

**A. `sentence-transformers/all-MiniLM-L6-v2`.**
Setup Guide default. 23M parameters, 384-dim embeddings. Runs on CPU in under 100ms per query. HuggingFace-cached after first download.

**B. `BAAI/bge-small-en-v1.5`.**
33M parameters, 384-dim. Reported to outperform MiniLM by 5-10pp on some retrieval benchmarks. Similar CPU footprint.

**C. TF-IDF sparse retrieval (from the Q3 pilot).**
No embedding required. `scikit-learn` only. Hit@3 = 93.6% baseline on our corpus. Zero download, zero cold-start, zero GPU.

## Chosen

**Option A — `all-MiniLM-L6-v2`.**

## Rationale

- Setup Guide default; the assessment machine will already have it cached if the Setup Guide was followed literally.
- Q3 pilot showed TF-IDF baseline at 93.6%. The embedder needs to match or beat this. MiniLM is the industry-standard "small-and-good-enough" model — likely to hit or exceed 93.6% on this small corpus.
- Model download is one-time; after that, `HuggingFaceEmbeddings` reads from local cache.
- 23M parameters means the model fits easily in memory alongside the rest of the harness on the assessment machine.
- Choosing BGE-small as an upgrade would need measured evidence; without it the choice is speculation. MiniLM is the honest default.

## Consequences

- Positive: matches setup guide, fits any assessment machine, low compute.
- Negative: if MiniLM under-performs TF-IDF, we've regressed on the retrieval-first thesis. Not observed yet — needs measurement after the environment is up.
- Mitigation: index_docs.py logs the chunk count and produces a small sanity file; the harness's first run against validation reports per-intent hit@3 in `metrics_report.json`. If any intent drops materially below the TF-IDF baseline, D-02 gets a supersession ADR.

## Revisit trigger

- If hit@3 falls below the TF-IDF baseline (93.6%) on any dense-retrieval run on the validation set.
- If any of the four low-hit intents identified in the Q3 pilot (onboarding, authentication_failure, integration_help, api_key_issue) needs a boost of more than 5 percentage points, evaluate BGE-small or hybrid dense-sparse retrieval as D-02b.

## Supersedes / superseded by

None. Q3 pilot findings (`workbooks/q3_findings.md`) are the direct evidence base.
