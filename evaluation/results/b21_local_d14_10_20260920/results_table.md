# Evaluation results

Run `harness-20260920T060503Z-fab3a44b` on 2026-09-20: 10 tickets. Code `5ae4a9d + uncommitted changes` at table generation. Drafting model `llama3.1-8b-ctx8k`, guardrail model `qwen2.5-7b-ctx8k`, confidence threshold 0.85, guardrails on. Model cache on (26 cached calls, 23 live); 10 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 40.0% correctly resolved (50.0% auto-sent) (NOT MET) | 95% CI 17-69% (n=10) | 1 of 5 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 31.4 s (MET) | n=5 auto-sent tickets; median 44.3 s; 5 partly replayed from the model cache (faster than live) | Harness time from ticket read to reply ready; excludes queueing and delivery. The 5 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 50.0% (NOT MET) | 95% CI 24-76% (n=10) | 3 escalated by routing and 2 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 71.4% mean over 7 classes; 5 of 7 at ≥85% (NOT MET) | Per-class n: median 1; 7 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: account_access 0% (n=1); api_usage_question 0% (n=1); api_key_issue 100% (n=1). Overall intent accuracy 80.0%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 100.0% of citations over 6 drafts (recall 83.3%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | Not measured (NOT MEASURED) | No live tickets | Every ticket was replayed from the model cache. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 5 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 0 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | Not measured (NOT MEASURED) | Every segment under n=10 | No segment reached the audit's minimum size. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 5 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | Not measured (Every segment under n=10) | NOT MEASURED |
| Decision logging | Complete coverage. | 10 of 10 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -15.8 pts in band 0.9-1.0 (stated 0.96, observed 0.80, n=5); 0.80-0.90 band observed 0.67 (n=3, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 5 of 10 tickets (50.0%) were answered without a human; 5 (50.0%) went to the human queue (baseline escalation 58%).
- 1 of those answers went to tickets that should have reached a person, so correct automated resolution is 40.0% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 5 of 10 |
| Send precision (sent replies that should have been sent) | 80.0% (4 of 5) |
| Send coverage (tickets that should be answered, answered) | 80.0% (4 of 5) |
| Wrong sends | 1 (10.0% of tickets) |
| Wrong holds | 1 (10.0% of tickets) |

Where the 2 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| guardrail:grounding:verdict | 1 |
| answerability:sent_unanswerable | 1 |

## Facts for "the figures above should be treated with caution because"

- A single run of 10 tickets: one ticket moves a rate by 10.0 points, and 95% intervals are wide.
- 10 tickets were partly replayed from the model cache (D-08), so they describe the run that filled it.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy, Latency p95, Cross-group variation.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- 1 of 10 tickets have text that appears elsewhere in the labelled data with a different expected_route or answerable_from_docs, so their correct answer is set by which copy was filed here, not by the ticket.
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
