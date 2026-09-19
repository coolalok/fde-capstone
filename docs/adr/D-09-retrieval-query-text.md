# D-09 — What text retrieval searches with

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-06, FR-07
**Affects:** `src/retrieve.py` (`retrieval_query`), `evaluation/harness.py`, `evaluation/retrieval_eval.py`

## Context

Until this decision the harness searched with `ticket.body` alone and discarded the subject. 345 of the 500 dev tickets carry a subject; chat tickets never do (EV-DATA-11). An external review of the repository (20 Sep) proposed two changes to retrieval: add the subject to the query, and replace dense search with a hybrid of dense and BM25 fused by reciprocal rank (RRF). Both are cheap to measure without a model call, so they were measured before either was adopted.

## Options considered

**A. Body alone (as before).** No change; the D-02a threshold was calibrated on it.

**B. Subject, a blank line, then body.** Plain text, no field labels. A ticket with no subject queries with the body alone, exactly as before.

**C. Hybrid: dense plus BM25, fused with RRF (k=60).** Adds a lexical index and a fusion step; the review's reasoning was that exact product terms ("SAML", "401", "webhook") are better matched lexically.

## Chosen

**Option B.** Option C is rejected on measurement.

## Rationale

`evaluation/answerability_probe.py`, article-level hit@k on the 357 answerable dev tickets, full ranking, no threshold (`evaluation/results/answerability_probe_20260920/report.json`):

| Query | Method | hit@1 | hit@3 | hit@5 |
|---|---|---|---|---|
| Body | Dense | 87.7% | 95.2% | 98.0% |
| Body | BM25 | 81.5% | 90.5% | 93.0% |
| Body | RRF | 88.0% | 93.8% | 95.8% |
| Subject + body | Dense | 89.9% | 96.6% | 98.6% |
| Subject + body | BM25 | 86.3% | 94.1% | 96.1% |
| Subject + body | RRF | 90.2% | 96.4% | 98.6% |

Adding the subject improves dense retrieval at every depth (+2.2 points at hit@1). Hybrid RRF does not beat dense: on the body it is worse at hit@3 and hit@5, because BM25 is the weaker ranker on this corpus and fusion pulls its misses up. With the subject it ties dense within one ticket. A lexical index would be a new artefact to build and keep in step with Chroma for no measured gain.

With the production threshold applied (0.25, top 5), hit@5 on the same tickets moves from 95.8% to 96.9%, and the floor cuts one expected article in both modes, so D-02a's calibration still holds.

## Consequences

- Positive: more tickets reach the generator with the right article at rank 1.
- Negative: on the 143 unanswerable dev tickets, 11 now return no passage above the floor instead of 14. Three more unanswerable tickets reach the generator, where the generator's "I don't know" and the guardrails must catch them. D-02a already found that empty retrieval is a weak answerability signal (about 1 in 10); this makes it slightly weaker.
- Figures from runs before this change (b21_* up to 20 Sep, retrieval_eval, d05 sweep, prompt A/B, judge calibration) used the body alone. Those scripts keep the body so their committed results stay reproducible; only the harness and retrieval_eval, which claim to measure production, use `retrieval_query`.

## Revisit trigger

If a validation run shows retrieval hit@3 on answerable tickets below the body-only 95.2%, or if the corpus grows past the 29 articles where dense retrieval is near its ceiling (at which point the hybrid comparison above is worth repeating).

## Supersedes / superseded by

None.
