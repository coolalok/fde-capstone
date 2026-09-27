# Evaluation results

Run `harness-20260927T060043Z-a162ea50` on 2026-09-27: 30 tickets. Code `a288388 + uncommitted changes` at table generation. Drafting model `llama3.1-8b-ctx8k`, guardrail model `qwen2.5-7b-ctx8k`, confidence threshold 0.85, guardrails on. Model cache off (0 cached calls, 121 live); 0 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 70.0% correctly resolved (93.3% auto-sent) (MET) | 95% CI 52-83% (n=30) | 7 of 28 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 50.6 s (MET) | n=28 auto-sent tickets; median 49.8 s | Harness time from ticket read to reply ready; excludes queueing and delivery. The 2 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 6.7% (MET) | 95% CI 2-21% (n=30) | 2 escalated by routing and 0 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 91.0% mean over the 12 classes with a precision denominator; 9 of 12 at ≥85% (NOT MET) | Precision n (predictions made per class): median 2; 12 classes were predicted fewer than 5 times and 2 never, so per-class figures are indicative only | Weakest: api_usage_question 50% (n=2); account_access 67% (n=3); deployment_failure 75% (n=4). 2 class(es) never predicted, so their precision is undefined rather than 0% and is excluded from the mean: authentication_failure, database_issue. Overall intent accuracy 90.0%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 86.2% of citations over 23 drafts (recall 82.6%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 59.8 s (NOT MET) | n=30 live tickets; max 62.9 s | End to end per ticket, including retrieval and every model call, run in sequence. Models: llama3.1-8b-ctx8k drafting, qwen2.5-7b-ctx8k guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 28 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 6 pts (customer_region: north_america vs europe) (NOT MEASURED) | breach not significant: north_america n=11 against europe n=10; 3 segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. The status is the audit's own per-segment verdict: a gap wider than the target whose interval overlaps the best segment's is a gap this sample cannot resolve, so it is reported as not measured rather than as a failure. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |
| Repeat contacts | 23.3% (history, n=30) | Halved | Not measured (NOT MEASURED) | An offline run cannot observe a customer returning | Baseline from history.repeat_contact: 7 of 30 of these tickets (23.3%) came back under human handling, so halved is 11.7% or lower. Leading indicator: 7 of 28 sent replies went to tickets the labels say must be held, the kind of reply that comes back as a repeat contact. |
| Availability | — | 99.5% | 100.0% (MET) | 95% CI 89-100% (n=30) | 30 of 30 tickets had every stage work. 0 hit a model-call or pipeline failure (degraded ticket, classifier or generator error, or a guardrail that could not run); 30 of 30 still received a decision, a failure escalating rather than erroring. One run's tickets are not uptime over time. At this n the interval cannot confirm 99.5%. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 28 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 6 pts (customer_region: north_america vs europe) (breach not significant: north_america n=11 against europe n=10; 3 segments under n=10 excluded) | NOT MEASURED |
| Decision logging | Complete coverage. | 30 of 30 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -5.0 pts in band 0.9-1.0 (stated 0.95, observed 0.90, n=30) | MET |

## What the numbers mean for the queue

- 28 of 30 tickets (93.3%) were answered without a human; 2 (6.7%) went to the human queue (baseline escalation 58%).
- 7 of those answers went to tickets that should have reached a person, so correct automated resolution is 70.0% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 28 of 30 |
| Send precision (sent replies that should have been sent) | 75.0% (21 of 28) |
| Send coverage (tickets that should be answered, answered) | 100.0% (21 of 21) |
| Wrong sends | 7 (23.3% of tickets) |
| Wrong holds | 0 (0.0% of tickets) |

Where the 7 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 7 |

## Intent classification by class

Precision is over the tickets predicted as the class (n predicted); recall is over the tickets labelled as it (n labelled). A class never predicted has no precision and one never labelled has no recall: n/a, not 0%.

| Intent | n labelled | n predicted | Precision | Recall |
|---|---|---|---|---|
| account_access | 2 | 3 | 66.7% | 100.0% |
| api_key_issue | 2 | 2 | 100.0% | 100.0% |
| api_usage_question | 1 | 2 | 50.0% | 100.0% |
| authentication_failure | 1 | 0 | n/a | 0.0% |
| billing_query | 5 | 4 | 100.0% | 80.0% |
| configuration_help | 2 | 2 | 100.0% | 100.0% |
| data_residency | 4 | 4 | 100.0% | 100.0% |
| database_issue | 1 | 0 | n/a | 0.0% |
| deployment_failure | 3 | 4 | 75.0% | 100.0% |
| integration_help | 3 | 3 | 100.0% | 100.0% |
| quota_or_overage | 1 | 1 | 100.0% | 100.0% |
| security_incident | 2 | 2 | 100.0% | 100.0% |
| sso_configuration | 1 | 1 | 100.0% | 100.0% |
| webhook_issue | 2 | 2 | 100.0% | 100.0% |

### Intent confusion matrix

Rows are the labelled intent; columns are the predicted intent, numbered as the rows are. The diagonal (bold) is correct classifications; any other count is tickets mistaken for that column's class. Blank cells are zero.

| Labelled / predicted | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. account_access | **2** |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 2. api_key_issue |  | **2** |  |  |  |  |  |  |  |  |  |  |  |  |
| 3. api_usage_question |  |  | **1** |  |  |  |  |  |  |  |  |  |  |  |
| 4. authentication_failure | 1 |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 5. billing_query |  |  | 1 |  | **4** |  |  |  |  |  |  |  |  |  |
| 6. configuration_help |  |  |  |  |  | **2** |  |  |  |  |  |  |  |  |
| 7. data_residency |  |  |  |  |  |  | **4** |  |  |  |  |  |  |  |
| 8. database_issue |  |  |  |  |  |  |  |  | 1 |  |  |  |  |  |
| 9. deployment_failure |  |  |  |  |  |  |  |  | **3** |  |  |  |  |  |
| 10. integration_help |  |  |  |  |  |  |  |  |  | **3** |  |  |  |  |
| 11. quota_or_overage |  |  |  |  |  |  |  |  |  |  | **1** |  |  |  |
| 12. security_incident |  |  |  |  |  |  |  |  |  |  |  | **2** |  |  |
| 13. sso_configuration |  |  |  |  |  |  |  |  |  |  |  |  | **1** |  |
| 14. webhook_issue |  |  |  |  |  |  |  |  |  |  |  |  |  | **2** |

## Where the time goes

Live tickets only (n=30); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 4.03, max 5.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 2.992 | 6.393 | 3.633 |
| retrieval | 0.202 | 0.858 | 0.276 |
| generation | 16.489 | 19.656 | 16.802 |
| guardrails | 29.325 | 34.571 | 29.845 |

## Facts for "the figures above should be treated with caution because"

- A single run of 30 tickets: one ticket moves a rate by 3.3 points, and 95% intervals are wide.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy, Cross-group variation, Repeat contacts.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 10 of 30 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket; 1 such pair sits inside this run, where no system can be right on both.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
