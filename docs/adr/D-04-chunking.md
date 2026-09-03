# D-04 — How help articles are split into passages for search

**Status:** Accepted
**Date:** 2026-09-02 (Wednesday, Week 2 Day 3 — B-08 backlog item)
**Decider:** Alok Kulkarni
**Requirements this ADR constrains:** FR-06, FR-07, FR-08, NFR-01a
**Files this ADR affects:** `src/index_docs.py`, `src/retrieve.py`

## Context — what problem this ADR is solving

Each of CloudServe's 29 help articles has to be turned into shorter pieces (passages) so that a customer ticket can be matched against the specific paragraph that answers their question, rather than the whole article. Two decisions are wrapped up in this one:

1. **How to split each article** — fixed-length windows, or splits that respect the article's own structure (headings, sections).
2. **What text to embed** — just the passage's own words, or the passage prefixed with the article's title and category.

The choice affects retrieval quality directly. Since the pack's Dataset Guide reminds us that "splitting inside a resolution sequence tends to produce passages that retrieve well but read as incomplete," this is not a purely mechanical decision.

## Options considered

**A. Fixed 800 characters, 120 character overlap; embed passage text only.**
The Setup Guide's default. Every article is chopped into overlapping 800-character windows. Simple to implement, deterministic. Ignores the article's own structure.

**B. Fixed 800/120; embed with title and category prepended.**
Same chunking as A, but each passage's embedded text is `**<title>** (<category>)\n\n<passage>`. The AI model that computes the numerical representation of the passage sees the article's title alongside its content. The raw passage is preserved in metadata so downstream consumers can still access it.

**C. Section-aware chunking (respect the article's headings, cap at 1500 characters); embed passage text only.**
Split on the article's markdown headings, keeping each section as one passage where it fits within 1500 characters. Passages read as complete resolution steps rather than mid-sentence cutoffs.

**D. Section-aware chunking + title prepending.**
Combines the structure-respecting split of C with the title-context signal of B.

## Chosen

**Option B — Fixed 800/120 chunking, with title and category prepended before embedding.**

## Rationale

The evidence chain across three measurement events pointed at this combination.

**Q3 pilot, 2026-08-29** (`workbooks/q3_findings.md`) — no dense retrieval yet, TF-IDF only. Fixed 800/120 hit 93.6% top-3; section-aware hit 92.4%. Fixed narrowly better. Both chunking strategies were still passage-text-only.

**B-07 D-02 revisit, 2026-08-31** (`workbooks/d02_findings.md`) — first dense measurement. `all-MiniLM-L6-v2` embedder, fixed 800/120, passage-text-only. Dense hit@3 = 91.0%, slightly below TF-IDF. The dense method won on fairness for non-fluent English but lost 2.6 percentage points on top-3 aggregate.

**B-30 title-prepending, 2026-09-02** (`workbooks/b30_findings.md`) — same dense embedder, same fixed 800/120 chunking, but embedding text now includes the article title and category. Dense hit@3 = 95.2%, now beating TF-IDF by 1.6 percentage points. Onboarding intent jumped 30 percentage points. Compliance_request improved by more than 36 points and dropped out of the weakest-five list. Non-fluent English parity preserved (0.943 vs 0.956). Business-vs-enterprise tier gap closed from 7.9pp to 1.4pp.

The title-prepending is the biggest single lever on retrieval quality that costs nothing. The pack's own Dataset Guide flags the pattern the improvement addresses (EV-I2, from Ines's interview): customers describe problems in words that don't match article titles. Adding the title into each chunk's embedded text is the cheapest way to bridge that gap on the corpus side, complementary to the ticket-side stripping the docs_comment ingest step will do (FR-25).

**Why not section-aware (Option C or D)?** Q3 pilot showed section-aware slightly under-performing fixed 800/120 on TF-IDF. Section-aware also produces 145 chunks vs 58 for fixed on this corpus — more surface area for the search to consider but not more useful information. And re-measuring section-aware with title-prepending (Option D) would be another experiment; at 95.2% hit@3 aggregate, we're above every target we set. The marginal gain from switching chunking method is unlikely to justify the re-measurement and code rework, especially with Friday's gate approaching.

## Consequences

- **Positive.**
  - Aggregate hit@3 exceeds every declared target and beats the word-matching baseline outright.
  - Onboarding no longer needs query rewriting; B-05 was cut in Sprint Plan Table 6, saving 2 hours.
  - The tier gap that motivated PRD Open Q6 shrank from 8pp to 1.4pp — Q6 remains open but is no longer urgent.
  - The generator (B-11) sees the article title as part of each retrieved passage. That gives the groundedness check (D-06) more surface to match citations against.
- **Neutral to note.**
  - The retrieved passage's text no longer starts with the article's own content — it starts with `**<title>** (<category>)`. Downstream consumers that need only the raw passage should read `metadata.chunk_text` rather than `page_content`.
- **Negative.**
  - `integration_help` intent stays at hit@3 = hit@5 = 0.688. Title-prepending doesn't fix a missing article, and 5 of 16 dev tickets in this intent have no covering article at all. Documented as risk R-08 with the NFR-01a v3 exception.

## Revisit trigger

- If aggregate hit@3 falls below 90% on the validation set at backlog item B-21.
- If any intent (other than the R-08 exception, integration_help) drops below 90% at hit@5.
- If a future dataset refresh adds articles that noticeably change the corpus profile — re-run `d02_retrieval_check.py` first.
- If the generator's groundedness check (D-06) shows a materially lower support rate when the passages contain the title header — unlikely (the model has more context, not less), but worth a look at the first evaluation harness run.

## Supersedes / superseded by

- Supersedes the "provisional fixed 800/120" note in `docs/architecture.md`'s Decision table (that row now points here).
- Q3 pilot findings and B-07/B-30 measurements are the evidence base.

## Changelog

- 2026-09-02 v1.0 — initial ADR. Written after the B-30 title-prepending measurement made the decision defensible from data rather than from Setup Guide defaults. Closes backlog item B-08.
