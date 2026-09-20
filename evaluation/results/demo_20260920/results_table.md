# Evaluation results

Run `harness-20260920T164234Z-d453a078` on 2026-09-20: 4 tickets. Code `a288388` at table generation. Drafting model `gpt-4o-mini`, guardrail model `gpt-4o`, confidence threshold 0.85, guardrails on. Model cache on (14 cached calls, 0 live); 4 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 25.0% auto-sent (NOT MET) | 95% CI 5-70% (n=4) | No labels in the input, so a sent reply cannot be checked as a correct resolution; this is the auto-send rate only. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 0.9 s (MET) | n=1 auto-sent tickets; median 0.9 s; 1 partly replayed from the model cache (faster than live) | Harness time from ticket read to reply ready; excludes queueing and delivery. The 3 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 75.0% (NOT MET) | 95% CI 30-95% (n=4) | 2 escalated by routing and 1 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | Not measured (NOT MEASURED) | No labels | Needs labels.intent in the input. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. |
| Latency p95 | — | < 3 s | Not measured (NOT MEASURED) | No live tickets | Every ticket was replayed from the model cache. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 1 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | Not measured (NOT MEASURED) | No labels | Needs labels.* in the input. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 1 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | Not measured (No labels) | NOT MEASURED |
| Decision logging | Complete coverage. | 4 of 4 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | No confidence band with enough tickets | NOT MEASURED |

## What the numbers mean for the queue

- 1 of 4 tickets (25.0%) were answered without a human; 3 (75.0%) went to the human queue (baseline escalation 58%).

## Facts for "the figures above should be treated with caution because"

- A single run of 4 tickets: one ticket moves a rate by 25.0 points, and 95% intervals are wide.
- 4 tickets were partly replayed from the model cache (D-08), so they describe the run that filled it.
- Not measured to the Framework's method: Satisfaction proxy, Classification precision, Hallucination rate, Citation accuracy, Latency p95, Cross-group variation.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
