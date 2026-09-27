# Evaluation results

Run `harness-20260927T101501Z-10995e3f` on 2026-09-27: 80 tickets. Code `47e0bc1` at table generation. Drafting model `gpt-4o-mini`, guardrail model `gpt-4o`, confidence threshold 0.85, guardrails on. Model cache off (0 cached calls, 304 live); 0 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 56.2% correctly resolved (76.2% auto-sent) (NOT MET) | 95% CI 45-67% (n=80) | 16 of 61 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 5.6 s (MET) | n=61 auto-sent tickets; median 5.5 s | Harness time from ticket read to reply ready; excludes queueing and delivery. The 19 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 23.8% (MET) | 95% CI 16-34% (n=80) | 14 escalated by routing and 5 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 95.7% mean over the 21 classes with a precision denominator; 18 of 21 at ≥85% (NOT MET) | Precision n (predictions made per class): median 3; 13 classes were predicted fewer than 5 times and 1 never, so per-class figures are indicative only | Weakest: compliance_request 50% (n=2); account_access 80% (n=5); api_usage_question 80% (n=5). 1 class(es) never predicted, so their precision is undefined rather than 0% and is excluded from the mean: rate_limit. Overall intent accuracy 96.2%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 94.3% of citations over 53 drafts (recall 82.1%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 6.7 s (NOT MET) | n=80 live tickets; max 7.2 s | End to end per ticket, including retrieval and every model call, run in sequence. Models: gpt-4o-mini drafting, gpt-4o guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 61 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 17 pts (language_fluency: non_fluent vs fluent) (NOT MEASURED) | breach not significant: non_fluent n=19 against fluent n=61; 2 segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. The status is the audit's own per-segment verdict: a gap wider than the target whose interval overlaps the best segment's is a gap this sample cannot resolve, so it is reported as not measured rather than as a failure. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |
| Repeat contacts | 21.2% (history, n=80) | Halved | Not measured (NOT MEASURED) | An offline run cannot observe a customer returning | Baseline from history.repeat_contact: 17 of 80 of these tickets (21.2%) came back under human handling, so halved is 10.6% or lower. Leading indicator: 16 of 61 sent replies went to tickets the labels say must be held, the kind of reply that comes back as a repeat contact. |
| Availability | — | 99.5% | 100.0% (MET) | 95% CI 95-100% (n=80) | 80 of 80 tickets had every stage work. 0 hit a model-call or pipeline failure (degraded ticket, classifier or generator error, or a guardrail that could not run); 80 of 80 still received a decision, a failure escalating rather than erroring. One run's tickets are not uptime over time. At this n the interval cannot confirm 99.5%. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 61 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 17 pts (language_fluency: non_fluent vs fluent) (breach not significant: non_fluent n=19 against fluent n=61; 2 segments under n=10 excluded) | NOT MEASURED |
| Decision logging | Complete coverage. | 80 of 80 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap +9.9 pts in band 0.8-0.9 (stated 0.85, observed 0.95, n=59); 0.80-0.90 band observed 0.95 (n=59, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 61 of 80 tickets (76.2%) were answered without a human; 19 (23.8%) went to the human queue (baseline escalation 58%).
- 16 of those answers went to tickets that should have reached a person, so correct automated resolution is 56.2% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 61 of 80 |
| Send precision (sent replies that should have been sent) | 73.8% (45 of 61) |
| Send coverage (tickets that should be answered, answered) | 93.8% (45 of 48) |
| Wrong sends | 16 (20.0% of tickets) |
| Wrong holds | 3 (3.8% of tickets) |

Where the 19 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 15 |
| guardrail:grounding:verdict | 3 |
| other:sent_against_label | 1 |

## Intent classification by class

Precision is over the tickets predicted as the class (n predicted); recall is over the tickets labelled as it (n labelled). A class never predicted has no precision and one never labelled has no recall: n/a, not 0%.

| Intent | n labelled | n predicted | Precision | Recall |
|---|---|---|---|---|
| account_access | 4 | 5 | 80.0% | 100.0% |
| api_key_issue | 6 | 6 | 100.0% | 100.0% |
| api_usage_question | 4 | 5 | 80.0% | 100.0% |
| authentication_failure | 3 | 2 | 100.0% | 66.7% |
| billing_query | 10 | 10 | 100.0% | 100.0% |
| compliance_request | 1 | 2 | 50.0% | 100.0% |
| configuration_help | 3 | 3 | 100.0% | 100.0% |
| data_export | 1 | 1 | 100.0% | 100.0% |
| data_residency | 6 | 5 | 100.0% | 83.3% |
| database_issue | 1 | 1 | 100.0% | 100.0% |
| deployment_failure | 5 | 5 | 100.0% | 100.0% |
| feature_request | 3 | 3 | 100.0% | 100.0% |
| integration_help | 3 | 3 | 100.0% | 100.0% |
| onboarding | 4 | 4 | 100.0% | 100.0% |
| performance_degradation | 3 | 3 | 100.0% | 100.0% |
| quota_or_overage | 2 | 2 | 100.0% | 100.0% |
| rate_limit | 1 | 0 | n/a | 0.0% |
| rollback_request | 6 | 6 | 100.0% | 100.0% |
| security_incident | 4 | 4 | 100.0% | 100.0% |
| sso_configuration | 1 | 1 | 100.0% | 100.0% |
| unclear_request | 6 | 6 | 100.0% | 100.0% |
| webhook_issue | 3 | 3 | 100.0% | 100.0% |

### Intent confusion matrix

Rows are the labelled intent; columns are the predicted intent, numbered as the rows are. The diagonal (bold) is correct classifications; any other count is tickets mistaken for that column's class. Blank cells are zero.

| Labelled / predicted | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. account_access | **4** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 2. api_key_issue |  | **6** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 3. api_usage_question |  |  | **4** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 4. authentication_failure | 1 |  |  | **2** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 5. billing_query |  |  |  |  | **10** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 6. compliance_request |  |  |  |  |  | **1** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 7. configuration_help |  |  |  |  |  |  | **3** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 8. data_export |  |  |  |  |  |  |  | **1** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 9. data_residency |  |  |  |  |  | 1 |  |  | **5** |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 10. database_issue |  |  |  |  |  |  |  |  |  | **1** |  |  |  |  |  |  |  |  |  |  |  |  |
| 11. deployment_failure |  |  |  |  |  |  |  |  |  |  | **5** |  |  |  |  |  |  |  |  |  |  |  |
| 12. feature_request |  |  |  |  |  |  |  |  |  |  |  | **3** |  |  |  |  |  |  |  |  |  |  |
| 13. integration_help |  |  |  |  |  |  |  |  |  |  |  |  | **3** |  |  |  |  |  |  |  |  |  |
| 14. onboarding |  |  |  |  |  |  |  |  |  |  |  |  |  | **4** |  |  |  |  |  |  |  |  |
| 15. performance_degradation |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **3** |  |  |  |  |  |  |  |
| 16. quota_or_overage |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **2** |  |  |  |  |  |  |
| 17. rate_limit |  |  | 1 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 18. rollback_request |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **6** |  |  |  |  |
| 19. security_incident |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **4** |  |  |  |
| 20. sso_configuration |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **1** |  |  |
| 21. unclear_request |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **6** |  |
| 22. webhook_issue |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **3** |

## Where the time goes

Live tickets only (n=80); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 3.8, max 4.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 1.302 | 1.565 | 1.312 |
| retrieval | 0.102 | 0.252 | 0.127 |
| generation | 1.782 | 2.65 | 1.815 |
| guardrails | 2.085 | 2.652 | 1.965 |

## Facts for "the figures above should be treated with caution because"

- A single run of 80 tickets: one ticket moves a rate by 1.2 points, and 95% intervals are wide.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy, Cross-group variation, Repeat contacts.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 21 of 80 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket; 2 such pairs sit inside this run, where no system can be right on both.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
