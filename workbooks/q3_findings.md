# Q3 Retrieval Pilot — Findings

**Date:** 2026-08-29 (Sat, W1D4)
**Purpose:** Settle Q3 from the Wednesday discovery notes — is the underlying failure documentation content or documentation findability?
**Method:** Two chunking strategies (fixed_800_120 vs section_aware) × two sparse retrievers (TF-IDF, BM25) run against the 357 tickets flagged `answerable_from_docs=true`. Hit rate measured against `labels.expected_doc_ids` at top-1, top-3, top-5.
**Constraint:** The container blocked the HuggingFace download, so the pilot used TF-IDF and BM25 rather than `all-MiniLM-L6-v2`. This turned out to be the right pilot — see below.

---

## The headline number

TF-IDF over the 29 articles + `fixed_800_120` chunking hits `expected_doc_ids` in top-3 for **93.6% of the 357 answerable tickets**.

| Config | hit@1 | hit@3 | hit@5 |
|---|---|---|---|
| fixed_800_120 · TF-IDF | 84.0% | 93.6% | 95.2% |
| fixed_800_120 · BM25 | 82.9% | 90.2% | 92.7% |
| section_aware · TF-IDF | 81.0% | 92.4% | 93.6% |
| section_aware · BM25 | 80.4% | 89.6% | 92.7% |

Even bare BM25 with no tuning gets to 90% top-3. Fixed chunking narrowly beat section-aware at every K.

## What this settles

**Q3 answer: the failure is findability, not content — and the corpus is more retrievable than anyone thought.**

Sofia was right that the internal search is the problem. But she may be underselling how solvable it is: a plain TF-IDF search box over the same 29 articles would solve the retrieval problem for 90%+ of the answerable tickets. The failure is not in the corpus and not in the retrieval algorithms available for free — it's in the fact that CloudServe's internal search was configured to match titles and exact terms, per Ines's account. No neural network was needed.

Ines's example — "my deployment keeps dying" vs "resolving container health check failures" — sounds like it should defeat TF-IDF (no shared exact terms). It doesn't defeat it in aggregate because the article bodies (which our TF-IDF indexes, unlike the presumed title-only internal search) contain enough shared vocabulary with ticket bodies to bridge the gap. The lesson: what defeats the internal search isn't semantic distance, it's title-only indexing.

## What this changes for the PRD

The retrieval-first thesis holds. What shifts is the engineering value proposition. The system's win over "just give CloudServe a search box" is:

1. **It packages retrieval + drafting + escalation-context in one workflow.**
2. **It carries an auditable decision log** (compliance review).
3. **It routes with a calibrated confidence threshold** rather than dumping a search results page on the customer.
4. **It has guardrails** for the four must-not-auto-respond intents and for the 6.4% of answerable-but-mis-retrieved tickets.

Retrieval quality is no longer the differentiator — it's a solved sub-problem. The differentiator is the routing + generation + governance stack sitting on top of it.

## Numeric targets for the retrieval NFR (feeds NFR-Xa "context relevance")

Given TF-IDF baseline of 93.6% hit@3 on answerable tickets:

- **Baseline threshold (must beat):** ≥ 90% top-3 hit rate. This is the minimum bar; below this we're worse than a keyword search box.
- **Target:** ≥ 93% top-3 hit rate.
- **Stretch:** ≥ 95%, with per-segment fairness (no segment below 85%).

Semantic embeddings (`all-MiniLM-L6-v2` per the pack) should match or beat TF-IDF. If they don't match on this corpus size, the pack's default is not the right choice and we should note that in D-02.

## Where retrieval actually struggles

Four intents where TF-IDF hit@3 is under 80% and semantic embedding might help:

| Intent | n | hit@3 (TF-IDF) | Interpretation |
|---|---|---|---|
| onboarding | 20 | 60.0% | Wide vocabulary; customer language doesn't share terms with article titles |
| authentication_failure | 14 | 64.3% | Symptoms in customer voice ("can't log in") differ from article title language |
| integration_help | 16 | 68.8% | Product-specific jargon customers don't know yet |
| api_key_issue | 12 | 75.0% | Named credentials may not appear in the title |

Note: none of these are top-volume intents. The high-volume intents (data_export, data_residency, deployment_failure, etc.) all sit at 90%+ hit@3 with plain TF-IDF.

**Implication for the PRD:** the retrieval NFR should carry a per-intent floor (no intent below 75% hit@3), not just an aggregate target. Otherwise the aggregate hides these four failure modes.

## Fairness segment results

| Dimension | Best segment | Worst segment | Gap |
|---|---|---|---|
| language_fluency | fluent 94.4% | non_fluent 90.8% | 3.6pp |
| customer_tier | enterprise 98.3% | business 91.1% | 7.2pp |
| customer_region | latin_america 100% (n=43) | europe 89.6% | 10.4pp |
| channel | chat 95.0% | forum 91.9% | 3.1pp |

Sofia's language-fluency concern shows up here at the retrieval level (3.6pp gap) even though it didn't show at the outcome level in the historical baseline. Small but real.

Enterprise retrieves best (98.3%). Combined with the earlier finding that enterprise has the worst outcomes (37% FCR, 369-min median resolution), this confirms enterprise's failure mode is complexity of resolution, not findability. Automation of the auto-respond path will disproportionately help the two segments that don't have this problem (business, standard), which is the tier-gap risk Ravi flagged from the other direction.

Latin America 100% on n=43 is likely small-sample noise; treat with caution.

## Chunking decision (feeds D-04 ADR)

`fixed_800_120` narrowly beats `section_aware` on every K. Both are within 2pp of each other. Given fixed chunking is simpler to implement, cheaper to reason about, and the Setup Guide default, **D-04 keeps `fixed_800_120`** with an ADR revisit trigger of "if hit@3 falls below 90% on the validation set."

Section-aware chunking on this corpus produced 145 chunks vs 58 for fixed. The extra chunk count added retrieval noise without adding retrieval quality. Section boundaries in these 29 articles are short enough that fixed windows already respect them by accident.

## What we still cannot answer without the pack's embedder

- **Whether semantic embedding beats TF-IDF on this corpus** at all, or by how much. Cannot test in this container; user must run once their Chroma is indexed.
- **Whether hybrid retrieval (dense + sparse fusion)** produces a meaningful lift on the four hard intents.
- **Whether query rewriting** (a small LLM call before retrieval to expand customer terms) closes the remaining 6.4% gap.

All three go on the Week 2 backlog as measurement tasks, not design commitments.

## Files

- `evaluation/results/q3_pilot_script.py` — the pilot script
- `evaluation/results/q3_pilot_results.json` — full per-segment JSON
- `workbooks/q3_findings.md` — this file
