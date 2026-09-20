# Evaluation results

Run `harness-20260920T025325Z-d5fdedb1` on 2026-09-20: 12 tickets. Code `501ca9d` at table generation. Drafting model `meta-llama/llama-3.1-8b-instruct`, guardrail model `nvidia/nemotron-3-super-120b-a12b:free`, confidence threshold 0.85, guardrails on. Model cache off (0 cached calls, 56 live); 0 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 8.3% correctly resolved (8.3% auto-sent) (NOT MET) | 95% CI 1-35% (n=12) | 0 of 1 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 38.5 s (MET) | n=1 auto-sent tickets; median 38.5 s | Harness time from ticket read to reply ready; excludes queueing and delivery. The 11 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 91.7% (NOT MET) | 95% CI 65-99% (n=12) | 2 escalated by routing and 9 blocked by a guardrail; 3 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 75.0% mean over 8 classes; 6 of 8 at ≥85% (NOT MET) | Per-class n: median 1; 8 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: account_access 0% (n=1); api_usage_question 0% (n=1); api_key_issue 100% (n=1). Overall intent accuracy 75.0%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 87.5% of citations over 8 drafts (recall 87.5%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 75.1 s (NOT MET) | n=12 live tickets; max 75.1 s | End to end per ticket, including retrieval and every model call, run in sequence. Models: meta-llama/llama-3.1-8b-instruct drafting, nvidia/nemotron-3-super-120b-a12b:free guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 1 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 1 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | Not measured (NOT MEASURED) | Every segment under n=10 | No segment reached the audit's minimum size. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 1 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | Not measured (Every segment under n=10) | NOT MEASURED |
| Decision logging | Complete coverage. | 12 of 12 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap -3.9 pts in band 0.9-1.0 (stated 0.93, observed 0.89, n=9); 0.80-0.90 band observed 0.33 (n=3, Framework expects about 0.85) | MET |

## What the numbers mean for the queue

- 1 of 12 tickets (8.3%) were answered without a human; 11 (91.7%) went to the human queue (baseline escalation 58%).
- 0 of those answers went to tickets that should have reached a person, so correct automated resolution is 8.3% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Routing against the labels

The FCR figure divides correct sends by every ticket. It hides two failures with opposite fixes: sending what should be held, and holding what could be sent.

| Measure | Value |
|---|---|
| Replies sent | 1 of 12 |
| Send precision (sent replies that should have been sent) | 100.0% (1 of 1) |
| Send coverage (tickets that should be answered, answered) | 14.3% (1 of 7) |
| Wrong sends | 0 (0.0% of tickets) |
| Wrong holds | 6 (50.0% of tickets) |

Where the 6 wrong decisions come from. Each is attributed to one stage by `evaluation.harness.failure_stage`: a wrong send to what the labels say is wrong with sending, a wrong hold to the earliest stage that explains it.

| Stage: reason | Tickets |
|---|---|
| guardrail:pii:fail_safe | 2 |
| guardrail:grounding:verdict | 1 |
| guardrail:tone_scope:verdict | 1 |
| guardrail:pii:verdict | 1 |
| guardrail:answer_relevance:fail_safe | 1 |

## Where the time goes

Live tickets only (n=12); tickets with any call replayed from the model cache are excluded. Model calls per ticket: mean 4.67, max 6.

| Stage | p50 s | p95 s | mean s |
|---|---|---|---|
| classification | 2.071 | 5.276 | 2.414 |
| retrieval | 0.134 | 15.033 | 1.388 |
| generation | 1.796 | 8.002 | 2.703 |
| guardrails | 18.22 | 68.997 | 21.574 |

## Facts for "the figures above should be treated with caution because"

- A single run of 12 tickets: one ticket moves a rate by 8.3 points, and 95% intervals are wide.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy, Cross-group variation.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
