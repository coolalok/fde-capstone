# D-02 Revisit — Dense Retrieval Check

**Date:** 2026-08-31 (Mon, Week 2 D1)
**Backlog item:** B-07 (Stage 4 Sprint Plan Table 3)
**Script:** `evaluation/d02_retrieval_check.py`
**Raw results:** `evaluation/results/d02_dense_retrieval.json`
**Baseline:** Q3 pilot (TF-IDF over 29 KB articles, `workbooks/q3_findings.md`) — hit@3 = 93.6% on 357 answerable tickets

## Verdict

**D-02 stays as-is with a note.** `all-MiniLM-L6-v2` is a valid choice — dense retrieval is within 3pp of TF-IDF at hit@3 and better at both hit@1 and hit@5. A supersession ADR is not warranted.

The chunking decision (D-04) can now be finalised on the same measurement.

## Headline numbers

| Metric  | Dense (all-MiniLM-L6-v2) | TF-IDF baseline | Delta   |
|---------|--------------------------|-----------------|---------|
| hit@1   | 0.866                    | 0.840           | +0.026  |
| hit@3   | 0.910                    | 0.936           | -0.026  |
| hit@5   | 0.964                    | 0.952           | +0.012  |

n = 357 answerable tickets (development set), same set as Q3 pilot.

Dense wins at the extremes (position 1 and top-5) and loses in the middle (top-3). Interpretation: dense either nails the target doc at rank 1 or produces a broader candidate set that surfaces it by rank 5; the middle band has more semantically-similar-but-wrong neighbours than TF-IDF's lexical overlap does.

## Where dense is unambiguously better than TF-IDF

- **Language fluency parity.** Non-fluent hit@3 = 0.908, fluent hit@3 = 0.911 — a 0.3pp gap. Semantic embeddings absorb the disfluency EV-DATA-06 flagged as a routing-quality concern. TF-IDF's lexical brittleness would show a wider spread here (not measured in Q3 pilot; taken as a known property of BM25/TF-IDF on non-native English).
- **Top-5 recall.** 96.4% vs 95.2%. Because the router escalates when retrieval returns nothing above threshold (D-06), the wider recall envelope means fewer escalation-by-retrieval-miss cases at the same threshold.
- **hit@1 precision.** 86.6% vs 84.0%. This matters for the confidence-threshold sweep (D-05) — when the confidence floor is set tight, the auto-respond bucket runs mostly on hit@1.

## Where TF-IDF is better

- **hit@3 by 2.6pp.** The router's `retrieve → generate` path currently takes the top-K passages (K = 3 provisional) and asks the generator to cite from that set. A hit@3 miss means the generator has to either draft without the right passage (guardrail FR-17 will block, escalating) or make something up (will also fail groundedness). Either way it lands as an escalation — the failure mode is safe, but throughput on those tickets is worse than TF-IDF would give.

The size of the loss (2.6pp × 357 = ~9 tickets) is small enough that pursuing hybrid retrieval (dense + sparse) or a bigger embedder (BGE) is not a Week 2 priority. See "Deferred" section below.

## Weakest intents (hit@3)

| Intent               | n   | hit@1 | hit@3 | hit@5 | B-05 trigger (<75%)? |
|----------------------|-----|-------|-------|-------|----------------------|
| compliance_request   | 17  | 0.529 | 0.529 | 1.000 | no (not in trigger list) |
| onboarding           | 20  | 0.500 | 0.600 | 0.800 | **YES**              |
| integration_help     | 16  | 0.688 | 0.688 | 0.688 | **YES**              |
| deployment_failure   | 19  | 0.737 | 0.737 | 1.000 | no (not in trigger list) |
| authentication_failure | 14 | 0.786 | 0.786 | 0.786 | no (above 75%)       |

Two of the four intents named in the Sprint Plan's B-05 gate trigger the "write query rewriting prompt" branch:

- **onboarding** — hit@3 = 0.600. Setup ceremony tickets read as generic "getting started" queries; semantic retrieval pulls broad-onboarding content, not the specific setup step the ticket describes. Candidate rewrite: extract the named product step ("SSO config", "workspace creation") and re-query. Escalation acceptable in the meantime.
- **integration_help** — hit@3 = 0.688 (and stays 0.688 at hit@5 — the target doc is not in the top-5 at all for 5 of 16 tickets). This is not a top-3 problem; it's a corpus coverage problem. Query rewriting will not fix it. **New finding — needs a coverage gap risk (R-<n>) not a query-rewriting prompt.**

**Interesting non-trigger observations:**

- `compliance_request` (n=17, hit@3=0.529, hit@5=1.000) — top-5 is perfect, top-3 is broken. This is exactly the case D-06's Self-RAG groundedness retry should catch: the generator draft will fail grounding, retry expands consideration, the second attempt sees the right passage. Worth adding as a T-generate test case (T-generate-groundedness-retry).
- `deployment_failure` (n=19, hit@3=0.737, hit@5=1.000) — same pattern.
- `authentication_failure` (n=14, hit@3=0.786, hit@5=0.786) — permanent miss at top-5. Similar coverage-gap flavour to integration_help but smaller. Investigate.

## Segments — where the system serves worst

| Segment            | Best cell           | Worst cell           | Spread |
|--------------------|---------------------|----------------------|--------|
| Channel            | chat 0.924          | docs_comment 0.896   | 2.8pp  |
| Language fluency   | fluent 0.911        | non_fluent 0.908     | 0.3pp  |
| Region             | latin_america 0.930 | asia_pacific 0.895   | 3.5pp  |
| Customer tier      | enterprise 0.949    | business 0.870       | 7.9pp  |

Two flags:

1. **Customer tier spread of ~8pp.** Business (n=123, hit@3=0.870) is the worst-served tier — worse than standard (0.926) and enterprise (0.949). Business tier accounts for 34% of dev-set volume. Q1 discovery (workbooks/discovery_notes_thursday.md) already flagged enterprise-first bias in the ticket-labelling process; this measurement extends the pattern to retrieval. **Action:** add to PRD Open Questions (Open Q3 or new) — should the confidence floor be tier-aware? See D-05 sweep.
2. **Docs_comment channel is worst.** 0.896 vs chat 0.924. Docs_comment tickets often reference the article they're commenting on but not always the article they *need* — a semantic match on "the article they're reading" outranks "the article that has the answer." **Action:** consider whether the ingest layer should extract and strip the referring-article context from `docs_comment` bodies before retrieval. Add as an FR candidate.

## Downstream actions authorised by this result

Reading against the Sprint Plan (Stage 4 Sprint Plan Table 3):

- **B-08 (D-04 chunking final ADR) — GO.** Fixed_800_120 delivered these numbers; either confirm it or measure a section-aware alternative on the same set.
- **B-05 (PR-RETRIEVE-01 query rewriting) — GO for onboarding only.** Integration_help is a coverage gap not a rewriting problem — write PR-RETRIEVE-01 as onboarding-scoped, and log integration_help as an issue in the risk register (candidate R-08 — "corpus coverage gap on integration_help").
- **B-06 (src/retrieve.py implementation) — GO with today's dense config.** No supersession, no config change.
- **B-04 (src/classify.py) — unaffected.** Continues per plan.

## Deferred (not on this week's plan)

- Hybrid dense+sparse retrieval. Would recover the 2.6pp hit@3 gap and probably more, but adds one dependency (BM25 library) and complicates the retrieval config. Cost-nothing rule still holds — BM25 is free — but the change surface is bigger than what the gap justifies. Revisit if evaluation harness shows retrieval as the dominant failure mode.
- BGE-small embedder (`BAAI/bge-small-en-v1.5`). One-line swap. Retained as the D-02 back-pocket option; measure only if evaluation harness surfaces retrieval as blocking.

## Updates to make elsewhere

1. **PRD Open Q1** — mark answered. Recommendation: `all-MiniLM-L6-v2` stays; hit@3 within 3pp of TF-IDF, hit@1 and hit@5 better, language-fluency parity is the key win.
2. **PRD Open Q3** — new candidate: tier-aware confidence floor. Business-tier retrieval hit@3 8pp behind enterprise.
3. **docs/architecture.md D-04 row** — chunking ADR can now be written (B-08).
4. **PRD Table 5 (NFR-01a)** — measurement source cite updated to point to this file.
5. **Risk register (Governance workbook, Stage 6)** — add candidate R-08 (corpus coverage gap on integration_help).

## Attribution

- Script: `evaluation/d02_retrieval_check.py`
- Chroma index: `storage/chroma/` (59 passages from 29 articles, fixed_800_120, `all-MiniLM-L6-v2` — as per D-04 provisional + D-02)
- Baseline: `workbooks/q3_findings.md`
- Data: 357 answerable tickets from `data/development_tickets.json` (labelled `labels.answerable_from_docs = true`)
