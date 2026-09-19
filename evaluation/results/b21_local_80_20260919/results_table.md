# Evaluation results

Run `harness-20260919T131836Z-5fe44f57` on 2026-09-19: 80 tickets. Code `7c8d502` at table generation. Drafting model `llama3.1-8b-ctx8k`, guardrail model `qwen2.5-7b-ctx8k`, confidence threshold 0.85, guardrails on. Model cache not recorded (run predates cache logging); 13 tickets replayed. Runs against the hidden evaluation set: 0.

| Measure | Baseline | Target | Achieved | Confidence in the figure | Notes |
|---|---|---|---|---|---|
| First contact resolution | 42% | 60% | 42.5% correctly resolved (60.0% auto-sent) (NOT MET) | 95% CI 32-53% (n=80) | 14 of 48 sent replies went to tickets the labels say must be held, so they are not counted as resolved: a wrong answer returns as a repeat contact. Correctness is agreement with labels.expected_route, not a check of reply quality. |
| Mean time to first reply | 8 to 12 hrs | < 5 min | 52.5 s (MET) | n=48 auto-sent tickets; median 62.6 s; 8 partly replayed from the model cache (faster than live) | Harness time from ticket read to reply ready; excludes queueing and delivery. The 32 escalated or blocked tickets get no automated reply (holding reply is out of scope, PRD Table 6), so their first reply comes from the human queue. |
| Satisfaction proxy | 3.2 / 5 | 4.0 | Not measured (NOT MEASURED) | No scored sample on this run | The Framework's method is human review of a stated sample of responses against a rubric, reporting sample size, rubric and scorers. Not done for this run. Nearest evidence: B-18, where one person scored 50 drafts from b21_openai_80_20260914 on the judge's RAG rubric (mean answer relevance 4.86/5) — a different rubric, a different run and a single scorer, so not a satisfaction proxy. |
| Escalation rate | 58% | ≤ 30% | 40.0% (NOT MET) | 95% CI 30-51% (n=80) | 6 escalated by routing and 26 blocked by a guardrail; 0 tickets were blocked because a check could not run (fail-safe), not because it found a fault. |
| Classification precision | — | 85% | 80.6% mean over 22 classes; 15 of 22 at ≥85% (NOT MET) | Per-class n: median 3; 16 classes have fewer than 5 tickets, so per-class figures are indicative only | Weakest: integration_help 0% (n=3); rate_limit 0% (n=1); sso_configuration 33% (n=1). Overall intent accuracy 86.2%. The target is per class, so it is met only if every class reaches 85%. |
| Hallucination rate | — | ≤ 5% | Not measured to method (NOT MEASURED) | — | The Framework requires at least fifty responses assessed independently by two people, with their agreement reported. This project had one human assessor. Nearest evidence (B-18, drafts from b21_openai_80_20260914): one human found an unsupported claim in 1 of 50 drafts; the LLM judge in 5 of 50; the judge failed calibration (pooled Spearman 0.3492 against 0.70). |
| Citation accuracy | — | 95% | Not measured to method (NOT MEASURED) | — | The Framework checks each citation against the sentence it is attached to. Sentence-level support was not assessed. Nearest evidence: the cited ARTICLE was one the labels expect in 92.5% of citations over 53 drafts (recall 83.0%) — a check of the right source, not of support. |
| Latency p95 | — | < 3 s | 70.4 s (NOT MET) | n=67 live tickets; max 71.6 s; 13 cache-replayed tickets excluded | End to end per ticket, including retrieval and every model call, run in sequence. Models: llama3.1-8b-ctx8k drafting, qwen2.5-7b-ctx8k guardrails. |
| Private data occurrences | — | 0 | 0 (MET) | Automated scan of all 48 sent replies; manual sample review: not done | The scan uses the PII guardrail's own patterns (email, API key, phone, account number), independently of the judge's verdict. The guardrail blocked 3 drafts for private data before sending. |
| Cross-group variation | — | < 5 pts | 44 pts (language_fluency: non_fluent vs fluent) (NOT MET) | breach at n=19; segments under n=10 excluded | Quality here is decision correctness against labels, not a rubric score, across language fluency, region and tier. NFR-05 allows 15 points; this Framework target is 5. Full per-segment figures: fairness audit. |

## Governance conditions (tier three)

| Condition | Requirement | Result | Status |
|---|---|---|---|
| Private data in outbound text | Zero occurrences. | 0 (Automated scan of all 48 sent replies; manual sample review: not done) | MET |
| Quality across customer groups | Under five percentage points of variation. | 44 pts (language_fluency: non_fluent vs fluent) (breach at n=19; segments under n=10 excluded) | NOT MET |
| Decision logging | Complete coverage. | 80 of 80 tickets logged; reconciles=True | MET |
| Confidence calibration | Stated confidence within five points of observed accuracy. | largest gap +100.0 pts in band 0.0-0.1 (stated 0.00, observed 1.00, n=5); 0.80-0.90 band observed 0.86 (n=29, Framework expects about 0.85) | NOT MET |

## What the numbers mean for the queue

- 48 of 80 tickets (60.0%) were answered without a human; 32 (40.0%) went to the human queue (baseline escalation 58%).
- 14 of those answers went to tickets that should have reached a person, so correct automated resolution is 42.5% against the 42% human baseline: the system moves work off the queue, but not yet more correctly resolved work.

## Facts for "the figures above should be treated with caution because"

- A single run of 80 tickets: one ticket moves a rate by 1.2 points, and 95% intervals are wide.
- 13 tickets were partly replayed from the model cache (D-08), so they describe the run that filled it.
- Not measured to the Framework's method: Satisfaction proxy, Hallucination rate, Citation accuracy.
- Correctness is agreement with the dataset's labels, some of which are debatable (e.g. VAL-0004 is labelled unanswerable although DOC-AUTH-002 covers it).
- Hidden evaluation set runs: 0. These figures are from a labelled validation set, not the held-out test set.
