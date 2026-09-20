# Evaluation results

Run `harness-20260920T173736Z-8eee28c5` on 2026-09-20: 80 tickets. Code `a288388` at table generation. Drafting model `gpt-4o-mini`, guardrail model `gpt-4o`, confidence threshold 0.85, guardrails on. Model cache on (31 cached calls, 273 live); 9 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 43.8% correctly resolved (60.0% auto-sent) (NOT MET) | 95% CI 33-55% (n=80) | 13 of 48 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 5.3 s (MET) | n=48 auto-sent tickets; median 5.8 s; 7 partly replayed from the model cache (faster than live) | Harness time from ticket read to reply ready; excludes queueing and delivery. The 32 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 40.0% (NOT MET) | 95% CI 30-51% (n=80) | 24 escalated by routing and 8 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 82.0% mean over 22 classes; 15 of 22 at ≥85% (NOT MET) | Per-class n: median 3; 16 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: account_access 0% (n=4); integration_help 0% (n=3); sso_configuration 33% (n=1). Overall intent accuracy 88.8%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 95.3% of citations over 53 drafts (recall 82.1%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 6.7 s (NOT MET) | n=71 live tickets; max 7.0 s; 9 cache-replayed tickets excluded | End to end per ticket, including retrieval and every model call, run in sequence. Models: gpt-4o-mini drafting, gpt-4o guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 48 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 20 pts (language_fluency: non_fluent vs fluent) (NOT MET) | breach not significant at n=19; segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 48 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 20 pts (language_fluency: non_fluent vs fluent) (breach not significant at n=19; segments under n=10 excluded) | NOT MET |
| Decision logging | Complete coverage. | 80 of 80 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -35.0 pts in band 0.7-0.8 (stated 0.75, observed 0.40, n=10); 0.80-0.90 band observed 0.94 (n=53, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 48 of 80 tickets (60.0%) were answered without a human; 32 (40.0%) went to the human queue (baseline escalation 58%).
- 13 of those answers went to tickets that should have reached a person, so correct automated resolution is 43.8% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 48 of 80 |
| Send precision (sent replies that should have been sent) | 72.9% (35 of 48) |
| Send coverage (tickets that should be answered, answered) | 72.9% (35 of 48) |
| Wrong sends | 13 (16.2% of tickets) |
| Wrong holds | 13 (16.2% of tickets) |

Where the 26 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| answerability:sent_unanswerable | 12 |
| classification:low_confidence | 9 |
| guardrail:answer_relevance:verdict | 3 |
| guardrail:grounding:verdict | 1 |
| other:sent_against_label | 1 |

## Where the time goes

Live tickets only (n=71); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 3.77, max 4.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 1.451 | 1.786 | 1.475 |
| retrieval | 0.116 | 0.316 | 0.13 |
| generation | 1.799 | 2.534 | 1.787 |
| guardrails | 2.331 | 3.105 | 2.149 |

## Facts for "the figures above should be treated with caution because"

- A single run of 80 tickets: one ticket moves a rate by 1.2 points, and 95% intervals are wide.
- 9 tickets were partly replayed from the model cache (D-08), so they describe the run that filled it.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 21 of 80 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket; 2 such pairs sit inside this run, where no system can be right on both.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
