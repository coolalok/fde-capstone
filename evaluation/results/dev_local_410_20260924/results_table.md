# Evaluation results

Run `harness-20260923T191730Z-991c8f6a` on 2026-09-23: 410 tickets. Code `a288388 + uncommitted changes` at table generation. Drafting model `llama3.1-8b-ctx8k`, guardrail model `qwen2.5-7b-ctx8k`, confidence threshold 0.85, guardrails on. Model cache on (418 cached calls, 1187 live); 143 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 55.6% correctly resolved (74.1% auto-sent) (NOT MET) | 95% CI 51-60% (n=410) | 76 of 304 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 37.5 s (MET) | n=304 auto-sent tickets; median 47.4 s; 115 partly replayed from the model cache (faster than live) | Harness time from ticket read to reply ready; excludes queueing and delivery. The 106 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 25.9% (MET) | 95% CI 22-30% (n=410) | 71 escalated by routing and 35 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 84.9% mean over 22 classes; 12 of 22 at ≥85% (NOT MET) | Per-class n: median 18; 0 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: integration_help 0% (n=15); api_usage_question 52% (n=19); account_access 72% (n=18). Overall intent accuracy 86.1%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 86.8% of citations over 285 drafts (recall 83.5%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 58.5 s (NOT MET) | n=267 live tickets; max 121.4 s; 143 cache-replayed tickets excluded | End to end per ticket, including retrieval and every model call, run in sequence. Models: llama3.1-8b-ctx8k drafting, qwen2.5-7b-ctx8k guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 304 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 15 pts (customer_region: latin_america vs europe) (NOT MET) | breach not significant at n=45; segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 304 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 15 pts (customer_region: latin_america vs europe) (breach not significant at n=45; segments under n=10 excluded) | NOT MET |
| Decision logging | Complete coverage. | 410 of 410 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap +100.0 pts in band 0.0-0.1 (stated 0.00, observed 1.00, n=11); 0.80-0.90 band observed 0.81 (n=171, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 304 of 410 tickets (74.1%) were answered without a human; 106 (25.9%) went to the human queue (baseline escalation 58%).
- 76 of those answers went to tickets that should have reached a person, so correct automated resolution is 55.6% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 304 of 410 |
| Send precision (sent replies that should have been sent) | 75.0% (228 of 304) |
| Send coverage (tickets that should be answered, answered) | 90.1% (228 of 253) |
| Wrong sends | 76 (18.5% of tickets) |
| Wrong holds | 25 (6.1% of tickets) |

Where the 101 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 63 |
| guardrail:grounding:verdict | 18 |
| other:sent_against_label | 12 |
| generation:generator_unknown | 5 |
| retrieval:no_expected_doc_retrieved | 1 |
| classification:low_confidence | 1 |
| classification:sent_never_auto_intent | 1 |

## Where the time goes

Live tickets only (n=267); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 3.88, max 5.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 2.994 | 4.038 | 3.25 |
| retrieval | 0.363 | 0.592 | 0.344 |
| generation | 16.462 | 20.638 | 16.924 |
| guardrails | 30.017 | 35.897 | 28.63 |

## Facts for "the figures above should be treated with caution because"

- A single run of 410 tickets: one ticket moves a rate by 0.2 points, and 95% intervals are wide.
- 143 tickets were partly replayed from the model cache (D-08), so they describe the run that filled it.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 91 of 410 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket; 28 such pairs sit inside this run, where no system can be right on both.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
