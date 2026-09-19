# Evaluation results

Run `harness-20260919T204301Z-5aae4b55` on 2026-09-19: 80 tickets. Code `be776a6` at table generation. Drafting model `gpt-4o-mini`, guardrail model `gemini-3.8-flash`, confidence threshold 0.85, guardrails on. Model cache off (0 cached calls, 414 live); 0 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 35.0% correctly resolved (50.0% auto-sent) (NOT MET) | 95% CI 25-46% (n=80) | 12 of 40 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 5.9 s (MET) | n=40 auto-sent tickets; median 5.8 s | Harness time from ticket read to reply ready; excludes queueing and delivery. The 40 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 50.0% (NOT MET) | 95% CI 39-61% (n=80) | 7 escalated by routing and 33 blocked by a guardrail; 10 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 77.0% mean over 22 classes; 14 of 22 at ≥85% (NOT MET) | Per-class n: median 3; 16 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: account_access 0% (n=4); integration_help 0% (n=3); rate_limit 0% (n=1). Overall intent accuracy 87.5%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 94.3% of citations over 53 drafts (recall 82.1%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 10.8 s (NOT MET) | n=80 live tickets; max 32.4 s | End to end per ticket, including retrieval and every model call, run in sequence. Models: gpt-4o-mini drafting, gemini-3.8-flash guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 40 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 34 pts (customer_tier: business vs standard) (NOT MET) | breach at n=30; segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 40 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 34 pts (customer_tier: business vs standard) (breach at n=30; segments under n=10 excluded) | NOT MET |
| Decision logging | Complete coverage. | 80 of 80 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -25.0 pts in band 0.7-0.8 (stated 0.75, observed 0.50, n=10); 0.80-0.90 band observed 0.92 (n=52, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 40 of 80 tickets (50.0%) were answered without a human; 40 (50.0%) went to the human queue (baseline escalation 58%).
- 12 of those answers went to tickets that should have reached a person, so correct automated resolution is 35.0% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 40 of 80 |
| Send precision (sent replies that should have been sent) | 70.0% (28 of 40) |
| Send coverage (tickets that should be answered, answered) | 58.3% (28 of 48) |
| Wrong sends | 12 (15.0% of tickets) |
| Wrong holds | 20 (25.0% of tickets) |

Where the 32 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 11 |
| guardrail:confidence_floor:verdict | 8 |
| guardrail:pii:fail_safe | 8 |
| guardrail:grounding:verdict | 4 |
| other:sent_against_label | 1 |

## Where the time goes

Live tickets only (n=80); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 5.17, max 6.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 1.413 | 1.728 | 1.451 |
| retrieval | 0.097 | 0.13 | 0.327 |
| generation | 1.644 | 2.269 | 1.657 |
| guardrails | 2.339 | 7.513 | 2.852 |

## Facts for "the figures above should be treated with caution because"

- A single run of 80 tickets: one ticket moves a rate by 1.2 points, and 95% intervals are wide.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
