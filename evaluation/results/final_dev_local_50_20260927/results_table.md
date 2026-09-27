# Evaluation results

Run `harness-20260927T101501Z-32ab3564` on 2026-09-27: 50 tickets. Code `a288388 + uncommitted changes` at table generation. Drafting model `llama3.1-8b-ctx8k`, guardrail model `qwen2.5-7b-ctx8k`, confidence threshold 0.85, guardrails on. Model cache off (0 cached calls, 198 live); 0 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 60.0% correctly resolved (80.0% auto-sent) (MET) | 95% CI 46-72% (n=50) | 10 of 40 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 52.2 s (MET) | n=40 auto-sent tickets; median 51.1 s | Harness time from ticket read to reply ready; excludes queueing and delivery. The 10 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 20.0% (MET) | 95% CI 11-33% (n=50) | 6 escalated by routing and 4 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 97.8% mean over the 18 classes with a precision denominator; 17 of 18 at ≥85% (NOT MET) | Precision n (predictions made per class): median 2; 16 classes were predicted fewer than 5 times and 0 never, so per-class figures are indicative only | Weakest: account_access 60% (n=5); api_key_issue 100% (n=2); api_usage_question 100% (n=3). Overall intent accuracy 96.0%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 88.9% of citations over 36 drafts (recall 84.7%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 77.9 s (NOT MET) | n=50 live tickets; max 88.0 s | End to end per ticket, including retrieval and every model call, run in sequence. Models: llama3.1-8b-ctx8k drafting, qwen2.5-7b-ctx8k guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 40 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 30 pts (language_fluency: fluent vs non_fluent) (NOT MEASURED) | breach not significant: fluent n=40 against non_fluent n=10; 1 segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. The status is the audit's own per-segment verdict: a gap wider than the target whose interval overlaps the best segment's is a gap this sample cannot resolve, so it is reported as not measured rather than as a failure. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |
| Repeat contacts | 24.0% (history, n=50) | Halved | Not measured (NOT MEASURED) | An offline run cannot observe a customer returning | Baseline from history.repeat_contact: 12 of 50 of these tickets (24.0%) came back under human handling, so halved is 12.0% or lower. Leading indicator: 10 of 40 sent replies went to tickets the labels say must be held, the kind of reply that comes back as a repeat contact. |
| Availability | — | 99.5% | 98.0% (NOT MET) | 95% CI 90-100% (n=50) | 49 of 50 tickets had every stage work. 1 hit a model-call or pipeline failure (degraded ticket, classifier or generator error, or a guardrail that could not run); 50 of 50 still received a decision, a failure escalating rather than erroring. One run's tickets are not uptime over time. At this n the interval cannot confirm 99.5%. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 40 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 30 pts (language_fluency: fluent vs non_fluent) (breach not significant: fluent n=40 against non_fluent n=10; 1 segments under n=10 excluded) | NOT MEASURED |
| Decision logging | Complete coverage. | 50 of 50 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap +1.0 pts in band 0.9-1.0 (stated 0.95, observed 0.96, n=50) | MET |

## What the numbers mean for the queue

- 40 of 50 tickets (80.0%) were answered without a human; 10 (20.0%) went to the human queue (baseline escalation 58%).
- 10 of those answers went to tickets that should have reached a person, so correct automated resolution is 60.0% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 40 of 50 |
| Send precision (sent replies that should have been sent) | 75.0% (30 of 40) |
| Send coverage (tickets that should be answered, answered) | 93.8% (30 of 32) |
| Wrong sends | 10 (20.0% of tickets) |
| Wrong holds | 2 (4.0% of tickets) |

Where the 12 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 10 |
| generation:generator_unknown | 1 |
| guardrail:grounding:verdict | 1 |

## Intent classification by class

Precision is over the tickets predicted as the class (n predicted); recall is over the tickets labelled as it (n labelled). A class never predicted has no precision and one never labelled has no recall: n/a, not 0%.

| Intent | n labelled | n predicted | Precision | Recall |
|---|---|---|---|---|
| account_access | 3 | 5 | 60.0% | 100.0% |
| api_key_issue | 2 | 2 | 100.0% | 100.0% |
| api_usage_question | 3 | 3 | 100.0% | 100.0% |
| authentication_failure | 4 | 2 | 100.0% | 50.0% |
| billing_query | 3 | 3 | 100.0% | 100.0% |
| compliance_request | 4 | 4 | 100.0% | 100.0% |
| configuration_help | 3 | 3 | 100.0% | 100.0% |
| data_export | 2 | 2 | 100.0% | 100.0% |
| database_issue | 2 | 2 | 100.0% | 100.0% |
| deployment_failure | 4 | 4 | 100.0% | 100.0% |
| feature_request | 2 | 2 | 100.0% | 100.0% |
| integration_help | 3 | 3 | 100.0% | 100.0% |
| performance_degradation | 1 | 1 | 100.0% | 100.0% |
| quota_or_overage | 2 | 2 | 100.0% | 100.0% |
| rate_limit | 2 | 2 | 100.0% | 100.0% |
| rollback_request | 5 | 5 | 100.0% | 100.0% |
| security_incident | 2 | 2 | 100.0% | 100.0% |
| sso_configuration | 3 | 3 | 100.0% | 100.0% |

### Intent confusion matrix

Rows are the labelled intent; columns are the predicted intent, numbered as the rows are. The diagonal (bold) is correct classifications; any other count is tickets mistaken for that column's class. Blank cells are zero.

| Labelled / predicted | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. account_access | **3** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 2. api_key_issue |  | **2** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 3. api_usage_question |  |  | **3** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 4. authentication_failure | 2 |  |  | **2** |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 5. billing_query |  |  |  |  | **3** |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 6. compliance_request |  |  |  |  |  | **4** |  |  |  |  |  |  |  |  |  |  |  |  |
| 7. configuration_help |  |  |  |  |  |  | **3** |  |  |  |  |  |  |  |  |  |  |  |
| 8. data_export |  |  |  |  |  |  |  | **2** |  |  |  |  |  |  |  |  |  |  |
| 9. database_issue |  |  |  |  |  |  |  |  | **2** |  |  |  |  |  |  |  |  |  |
| 10. deployment_failure |  |  |  |  |  |  |  |  |  | **4** |  |  |  |  |  |  |  |  |
| 11. feature_request |  |  |  |  |  |  |  |  |  |  | **2** |  |  |  |  |  |  |  |
| 12. integration_help |  |  |  |  |  |  |  |  |  |  |  | **3** |  |  |  |  |  |  |
| 13. performance_degradation |  |  |  |  |  |  |  |  |  |  |  |  | **1** |  |  |  |  |  |
| 14. quota_or_overage |  |  |  |  |  |  |  |  |  |  |  |  |  | **2** |  |  |  |  |
| 15. rate_limit |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **2** |  |  |  |
| 16. rollback_request |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **5** |  |  |
| 17. security_incident |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **2** |  |
| 18. sso_configuration |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | **3** |

## Where the time goes

Live tickets only (n=50); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 3.96, max 4.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 2.947 | 3.271 | 3.257 |
| retrieval | 0.281 | 0.485 | 0.307 |
| generation | 16.395 | 29.011 | 17.987 |
| guardrails | 30.358 | 45.665 | 31.785 |

## Facts for "the figures above should be treated with caution because"

- A single run of 50 tickets: one ticket moves a rate by 2.0 points, and 95% intervals are wide.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy, Cross-group variation, Repeat contacts.
- Correctness is agreement with the dataset's labels, some of which are debatable.
- 6 of 50 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket.
- Hidden evaluation set runs: 0. These figures are from a labelled development set, not the held-out test set.
