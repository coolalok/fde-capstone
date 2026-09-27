# Evaluation results

Run `harness-20260923T100141Z-9b81b9d4` on 2026-09-23: 80 tickets. Code `a288388 + uncommitted changes` at table generation. Drafting model `llama3.1-8b-ctx8k`, guardrail model `qwen2.5-7b-ctx8k`, confidence threshold 0.85, guardrails on. Model cache on (37 cached calls, 283 live); 16 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 56.2% correctly resolved (78.8% auto-sent) (NOT MET) | 95% CI 45-67% (n=80) | 18 of 63 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 42.2 s (MET) | n=63 auto-sent tickets; median 47.6 s; 13 partly replayed from the model cache (faster than live) | Harness time from ticket read to reply ready; excludes queueing and delivery. The 17 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 21.2% (MET) | 95% CI 14-31% (n=80) | 3 escalated by routing and 14 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 86.0% mean over 20 classes; 14 of 20 at ≥85% (NOT MET) | Per-class n: median 4; 12 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: feature_request 0% (n=1); api_key_issue 50% (n=2); api_usage_question 62% (n=5). Overall intent accuracy 88.8%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 90.3% of citations over 57 drafts (recall 85.1%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 56.6 s (NOT MET) | n=64 live tickets; max 66.2 s; 16 cache-replayed tickets excluded | End to end per ticket, including retrieval and every model call, run in sequence. Models: llama3.1-8b-ctx8k drafting, qwen2.5-7b-ctx8k guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 63 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 29 pts (customer_region: asia_pacific vs latin_america) (NOT MET) | breach not significant at n=19; segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 63 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 29 pts (customer_region: asia_pacific vs latin_america) (breach not significant at n=19; segments under n=10 excluded) | NOT MET |
| Decision logging | Complete coverage. | 80 of 80 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -7.3 pts in band 0.9-1.0 (stated 0.95, observed 0.87, n=47); 0.80-0.90 band observed 0.91 (n=33, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 63 of 80 tickets (78.8%) were answered without a human; 17 (21.2%) went to the human queue (baseline escalation 58%).
- 18 of those answers went to tickets that should have reached a person, so correct automated resolution is 56.2% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 63 of 80 |
| Send precision (sent replies that should have been sent) | 71.4% (45 of 63) |
| Send coverage (tickets that should be answered, answered) | 86.5% (45 of 52) |
| Wrong sends | 18 (22.5% of tickets) |
| Wrong holds | 7 (8.8% of tickets) |

Where the 25 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 18 |
| guardrail:grounding:verdict | 5 |
| guardrail:answer_relevance:verdict | 2 |

## Where the time goes

Live tickets only (n=64); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 4, max 4.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 2.987 | 3.871 | 3.296 |
| retrieval | 0.41 | 0.641 | 0.391 |
| generation | 15.933 | 18.023 | 16.114 |
| guardrails | 29.325 | 35.264 | 29.655 |

## Facts for "the figures above should be treated with caution because"

- A single run of 80 tickets: one ticket moves a rate by 1.2 points, and 95% intervals are wide.
- 16 tickets were partly replayed from the model cache (D-08), so they describe the run that filled it.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 18 of 80 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket; 1 such pair sits inside this run, where no system can be right on both.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
