# D-10 — No answerability gate built from retrieval signals

**Status:** Accepted. The gate is not built.
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-09, FR-10
**Affects:** nothing in `src/`; evidence in `evaluation/answerability_probe.py`

## Context

D-05b found that answerability, not confidence, is the binding constraint: 17 of 18 false positives at threshold 0.80 were `answerable_from_docs=false`. The 80-ticket local run (b21_local_80_20260919) repeats it: 13 of its 14 wrong sends were unanswerable tickets.

An external review (20 Sep) proposed an answerability gate between retrieval and generation: score the evidence from retrieval features (top score, margin, lexical agreement), calibrate a logistic regression on the 500 dev tickets against `answerable_from_docs`, and escalate below a threshold without calling the generator. It would cost no model call, which is why it was worth measuring first.

## Options considered

**A. Gate on retrieval features.** Dense top score, dense article margin, passages above the floor, BM25 top score, BM25 margin, dense/BM25 agreement on the top article; logistic regression trained on dev.

**B. No pre-generation gate.** Leave answerability to the generator's "I don't know" (PR-GENERATE-01), the guardrails and the D-07 policy.

**C. A model-judged evidence-sufficiency check.** One more model call per ticket, reading the ticket against the passages.

## Chosen

**Option B.** Option A is rejected on measurement. Option C is not measured and not built (see Revisit trigger).

## Rationale

`evaluation/answerability_probe.py`, results in `evaluation/results/answerability_probe_20260920/report.json`, body-only query (the query the run used):

- Best single feature, dense article margin: AUC 0.652 on dev. Dense top score alone: 0.586.
- Logistic regression on all six features: AUC 0.642 (5-fold cross-validation on dev), 0.661 on the 80 validation tickets. The bar set before measuring was 0.75.
- The operating point chosen on dev (hold at most 5% of answerable tickets) replayed over the 48 sends of b21_local_80_20260919 holds **0 of the 14 wrong sends** and loses 1 of the 34 correct ones. On the validation set it holds 9 of 27 unanswerable tickets, but not the ones the pipeline actually sent.

The unanswerable tickets that get sent are the ones retrieval looks confident about: the docs cover the topic but not the specific question. Retrieval scores measure topical similarity, which is exactly what those tickets have. The subject + body query (D-09) does not change this (cross-validated AUC 0.596).

## Consequences

- The answerability gap stays open, and the report must say so rather than present a gate. The wrong-send figure (13 of 80 on the local run) is the measure of it.
- Positive: no gate that looks like a control and holds nothing; no extra artefact to calibrate.

## Revisit trigger

If a model-judged sufficiency check (Option C) can be measured against the 14 wrong sends of b21_local_80_20260919 and holds most of them while losing under 5% of correct sends, build it. Also revisit if the corpus changes so that unanswerable tickets stop sharing topics with the articles.

## Supersedes / superseded by

None. Follows up D-05b.
