# D-02 — Which embedding model the retriever uses

**Status:** Accepted (verified 2026-08-31)
**Original decision date:** 2026-08-30
**Verified against measurement:** 2026-08-31 (backlog item B-07)
**Decider:** Alok Kulkarni
**Requirements this ADR constrains:** FR-06, FR-07, NFR-01a, NFR-08
**Files this ADR affects:** `src/index_docs.py`, `src/retrieve.py`, `src/config.py`

## Context — what problem this ADR is solving

Every one of CloudServe's 29 help articles has to be turned into numbers once, at index-build time, so that a new customer ticket can be compared against them and the closest matches returned. Those numbers are called embeddings, and the model that produces them is what this ADR is choosing.

The model has to be free (per the cost-nothing rule), runnable on the assessment machine's CPU (no GPU assumed), small enough to load in seconds, and — most importantly — produce embeddings that let the retriever match or beat 93.6% top-3 hit rate. That 93.6% number came from Saturday's Q3 pilot, which measured a much simpler word-matching search (TF-IDF) against 357 real customer tickets. If the modern embedding-based approach can't match or beat that baseline, then the modern approach isn't buying us anything and we should just use word-matching.

## Options considered

**A. `sentence-transformers/all-MiniLM-L6-v2`.**
The Setup Guide's default. A small AI model with 23 million parameters that produces 384-dimensional embeddings. Runs on a CPU in under 100ms per query. Cached to disk after the first download so subsequent runs don't need the network.

**B. `BAAI/bge-small-en-v1.5`.**
A slightly larger model — 33 million parameters, same 384-dimensional output. Community benchmarks show it outperforming MiniLM by 5–10 percentage points on some retrieval tasks. Similar CPU footprint. Would need its own download.

**C. Word-matching (TF-IDF), no embedding model at all.**
The approach from the Q3 pilot. Uses `scikit-learn` only. Hit@3 = 93.6% baseline on our corpus. Zero download, zero cold-start, zero AI model involved.

## Chosen

**Option A — `all-MiniLM-L6-v2`.**

## Rationale for the original choice (2026-08-30)

- It's the Setup Guide's default. If a reader follows the Setup Guide literally, this model is already downloaded on their machine.
- The Q3 pilot set the bar at 93.6%. MiniLM is the industry-standard "small-and-good-enough" model — likely to hit or exceed that on a corpus this small.
- After the first download, `HuggingFaceEmbeddings` reads from the local cache — no ongoing network cost.
- At 23 million parameters, the model fits easily into memory alongside the rest of the pipeline on the assessment machine.
- Choosing BGE-small as an upgrade would have needed evidence we didn't have yet. Without evidence, the choice would be speculation. MiniLM is the honest default.

## Consequences

- **Positive.** Matches the Setup Guide. Fits any assessment machine. Low compute cost.
- **Negative if MiniLM under-performs word-matching.** The whole retrieval-first design would be a regression from the pilot's baseline.
- **Mitigation.** `src/index_docs.py` logs the chunk count on build; the harness's first run against the validation set reports top-3 hit rate per ticket type in `metrics_report.json`. If any ticket type drops noticeably below the word-matching baseline, D-02 gets superseded by a new ADR.

## Revisit outcome — 2026-08-31 (backlog item B-07)

Ran the dense-retrieval measurement on the 357 answerable development tickets today. Full breakdown in `workbooks/d02_findings.md`; raw results in `evaluation/results/d02_dense_retrieval.json`.

Headline result:

| Measure | Dense (MiniLM-L6-v2) | TF-IDF baseline | Difference |
|---------|----------------------|-----------------|------------|
| Top-1 hit rate | 86.6% | 84.0% | +2.6 points |
| Top-3 hit rate | 91.0% | 93.6% | −2.6 points |
| Top-5 hit rate | 96.4% | 95.2% | +1.2 points |

**Verdict: D-02 stands. No supersession needed.**

Reasoning:

- The dense model is within 3 percentage points of the word-matching baseline on top-3 (91.0% vs 93.6%). Slightly worse on this metric, but slightly better on top-1 and top-5.
- The deciding factor is fairness. On non-fluent-English tickets, dense retrieval scores 90.8% top-3 — a 0.3-point gap from fluent-English's 91.1%. Word-matching would show a much wider gap because non-fluent tickets share fewer exact words with article titles. Since 24% of development tickets are non-fluent, this fairness win is worth more than the 2.6-point top-3 gap.
- The 2.6-point gap on top-3 works out to about 9 tickets out of 357 where word-matching would have found the answer. The downstream safety check would catch a bad draft on those and escalate them to a human anyway — no wrong answer goes to a customer, just slightly more escalations.

## New findings from the revisit (recorded in the Stage 5 revision log)

Two things surfaced from the segment breakdown that weren't part of the original ADR context. Both are logged in `workbooks/Stage_5_PRD_Revision_Log.docx`:

- **Business-tier customers get worse retrieval than enterprise-tier customers** — 87.0% top-3 hit rate vs 94.9%, an 8-point gap on 182 tickets. Under a uniform confidence threshold this becomes a reply-quality gap. Feeds a new PRD Open Question (Q4) about whether the threshold should be tier-aware. Backlog item B-16 (D-05 confidence-threshold sweep) will answer this.
- **`integration_help` tickets have a corpus coverage gap.** Top-3 and top-5 hit rate are both 68.8% — meaning the correct article isn't even in the top 5 for 5 of 16 tickets. Not a search problem; probably a missing-article problem. Logged as a new risk, R-08.

## Revisit trigger (kept in place)

- If top-3 hit rate falls below 90% on any dense-retrieval run against the validation set (backlog item B-21).
- If any of the ticket types identified in the Q3 pilot as low-hit (onboarding, authentication_failure, integration_help, api_key_issue) needs a boost of more than 5 percentage points to hit its per-type floor, evaluate BGE-small or a hybrid dense-plus-word-matching approach as D-02b.

## What this ADR supersedes and what supersedes it

None. The Q3 pilot (`workbooks/q3_findings.md`) and today's revisit (`workbooks/d02_findings.md`) are the direct evidence base.

## Changelog

- 2026-08-30 — first draft, decision accepted based on Q3 pilot's TF-IDF baseline as the bar to meet.
- 2026-08-31 — added "Revisit outcome" section recording the measured result of backlog item B-07 (dense 91.0% top-3 vs TF-IDF 93.6% — within 3 points; fairness on non-fluent English is the deciding factor for keeping the modern method). Two new findings noted: an 8-point tier gap logged as PRD Open Question 4, and a corpus coverage gap on integration_help logged as risk R-08. Both feed the Stage 5 revision log. The ADR itself was rewritten in plainer language on the same day; the technical content, requirement IDs, and file paths are unchanged.
- 2026-09-02 — re-verified after B-30 (title + category prepended to each chunk before embedding, `src/index_docs.py`). Dense hit@3 improved from 91.0% to 95.2%, now beating TF-IDF (93.6%) on every metric — not just holding on fairness. Non-fluent English parity preserved (0.943 vs fluent 0.956). Tier gap closed from 7.9pp to 1.4pp, downgrading PRD Open Q6. D-02 stands with a much wider margin; the earlier "kept because of fairness alone" story is now "kept because it's better on every axis." Full measurement: `workbooks/b30_findings.md`.
