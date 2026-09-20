# Evaluation results

Run `harness-20260919T194841Z-6aeb7291` on 2026-09-19: 80 tickets. Code `501ca9d + uncommitted changes` at table generation. Drafting model `gpt-4o-mini`, guardrail model `gemini-3.8-flash`, confidence threshold 0.85, guardrails on. Model cache off (0 cached calls, 448 live); 0 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 42.5% correctly resolved (55.0% auto-sent) (NOT MET) | 95% CI 32-53% (n=80) | 10 of 44 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 14.1 s (MET) | n=44 auto-sent tickets; median 12.8 s | Harness time from ticket read to reply ready; excludes queueing and delivery. The 36 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 45.0% (NOT MET) | 95% CI 35-56% (n=80) | 7 escalated by routing and 29 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 82.3% mean over 22 classes; 15 of 22 at ≥85% (NOT MET) | Per-class n: median 3; 16 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: account_access 0% (n=4); integration_help 0% (n=3); sso_configuration 25% (n=1). Overall intent accuracy 88.8%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 95.3% of citations over 53 drafts (recall 82.1%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 25.0 s (NOT MET) | n=80 live tickets; max 48.4 s | End to end per ticket, including retrieval and every model call, run in sequence. Models: gpt-4o-mini drafting, gemini-3.8-flash guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 44 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 30 pts (customer_tier: business vs standard) (NOT MET) | breach not significant at n=30; segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 44 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 30 pts (customer_tier: business vs standard) (breach not significant at n=30; segments under n=10 excluded) | NOT MET |
| Decision logging | Complete coverage. | 80 of 80 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -19.4 pts in band 0.7-0.8 (stated 0.75, observed 0.56, n=9); 0.80-0.90 band observed 0.90 (n=52, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 44 of 80 tickets (55.0%) were answered without a human; 36 (45.0%) went to the human queue (baseline escalation 58%).
- 10 of those answers went to tickets that should have reached a person, so correct automated resolution is 42.5% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 44 of 80 |
| Send precision (sent replies that should have been sent) | 77.3% (34 of 44) |
| Send coverage (tickets that should be answered, answered) | 70.8% (34 of 48) |
| Wrong sends | 10 (12.5% of tickets) |
| Wrong holds | 14 (17.5% of tickets) |

Where the 24 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| guardrail:confidence_floor:verdict | 10 |
| answerability:sent_unanswerable | 9 |
| guardrail:grounding:verdict | 4 |
| other:sent_against_label | 1 |

## Where the time goes

Live tickets only (n=80); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 5.6, max 6.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 1.473 | 1.812 | 1.513 |
| retrieval | 0.258 | 0.5 | 0.463 |
| generation | 1.851 | 2.448 | 1.825 |
| guardrails | 9.184 | 20.435 | 10.515 |

## Facts for "the figures above should be treated with caution because"

- A single run of 80 tickets: one ticket moves a rate by 1.2 points, and 95% intervals are wide.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 21 of 80 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket; 2 such pairs sit inside this run, where no system can be right on both.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
