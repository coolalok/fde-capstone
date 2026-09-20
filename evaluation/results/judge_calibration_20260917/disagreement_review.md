# B-18 disagreement review — PR-EVAL-JUDGE-01 v1.1 vs human scores

Date: 2026-09-17. Judge: `gemini-3.8-flash`, prompt `PR-EVAL-JUDGE-01@1.1`. Items: the 50-item
calibration fixture `tests/fixtures/judge_calibration.json` (fixture_id `8fdd65c70cc7`), drafts
from the 14 Sep B-21 run `evaluation/results/b21_openai_80_20260914`. Human scores were given blind
(`evaluation/calibration/judge_calibration_scores.json`, imported into the fixture).

## Result

**The judge is NOT trusted**: pooled Spearman 0.35 against the 0.70 floor. Its scores are not
reported as measurements. They may be used only to flag items for a human to read.

| File | What it is |
|---|---|
| `judged.jsonl` | Judge scores and reasoning, 50 items, 0 errors. |
| `agreement.json` | Agreement with the blind human scores. |
| `disagreements.json` | Every item where human and judge differ, with judge reasoning and human notes. |

## Agreement

| Dimension | Spearman | Exact | Within one | Mean judge minus human |
|---|---|---|---|---|
| context_relevance | 0.668 | 0.92 | 0.98 | +0.02 |
| groundedness | 0.457 | 0.90 | 0.98 | -0.12 |
| answer_relevance | 0.046 | 0.70 | 0.96 | -0.18 |
| **pooled (n=150)** | **0.349** | | | |

**Ceiling effect.** Human scores were 5 on 43, 49 and 46 of 50 items for the three dimensions; the
judge gave 5 on 43, 45 and 37. Rank correlation on near-constant scores is unstable: with one
non-5 human groundedness score, a single item decides that dimension. High exact agreement
(70-92%) with low Spearman is the signature of this. The calibration sample, drawn from real
drafts, contains too few weak replies to measure rank agreement reliably.

## Disagreements

19 of 50 items differ on at least one dimension: answer_relevance 15, groundedness 5,
context_relevance 4.

### groundedness — judge claims checked against the retrieved passages

Each judge claim below was checked against the passage text in the fixture. Quotes are verbatim.

| Item | Human / judge | Judge's unsupported claim | Check against passages | Verdict |
|---|---|---|---|---|
| CAL-09 (VAL-0024) | 5 / 4 | "you will need to create a new key with the appropriate write permissions to resolve this issue" | DOC-AUTH-004: "Review the scopes attached to the key." and "Read-only keys cannot write, and project-scoped keys cannot reach organisation endpoints." Creating a new key is not stated. | Judge right: unsupported. Minor or material is a judgement call. |
| CAL-16 (VAL-0045) | 5 / 4 | "you may consider canceling and reinitiating the export" | DOC-DATA-001: "Large exports are queued and processed asynchronously" and "Check the exports page for job status." Nothing on cancelling. | Judge right: unsupported, and it answers the customer's direct question ("Should I cancel and try again?"). |
| CAL-23 (VAL-0026) | 5 / 4 | "if you have specific requirements for data residency, consider enabling read replicas in the EU to reduce latency for users located there without moving the primary storage" | DOC-DATA-003: "Enable read replicas in additional regions to reduce latency for distant users without moving primary storage." | **Judge wrong: the claim is supported.** The weakness is relevance: read replicas are offered under data residency, which they do not satisfy. |
| CAL-24 (VAL-0071) | 5 / 3 | "you can choose to enable overage protection instead." | DOC-BILL-003: "Overage protection is disabled, so usage continued beyond the allowance" and "Decide deliberately between a hard spend cap, which stops the service, and overage, which continues at the listed rate." | **Judge right.** Enabling overage protection is what stops usage; the customer wants to keep running. The core advice contradicts the passage, which the rubric scores 2. |
| CAL-33 (VAL-0019) | 4 / 3 | "you may want to consider removing the user and re-inviting them to ensure they have the correct permissions set up" | Not re-checked. Human note agrees it is unsupported ("minor extrapolation"). | Differ only on minor vs material. |

On groundedness the judge found real unsupported claims the human scored as fully supported
(CAL-09, CAL-16, CAL-24), and made one error (CAL-23).

### answer_relevance — the dimension blocking calibration

15 items differ. The judge scored lower on 12 (CAL-03, 07, 10, 11, 14, 15, 23, 24, 29, 32, 45, 48),
mostly at 4 against a human 5. The human scored lower on 3 (CAL-25, 35, 38), where the judge gave 5.
The two raters disagree on which replies fall short, not just on how strict to be.

CAL-38 (VAL-0062): human 3, judge 5. The human note, "Retrieval correctly followed body, not
subject", describes retrieval and does not explain an answer_relevance of 3; the score may have been
entered against the wrong dimension or item.

### context_relevance

4 items differ: CAL-14 (human 3, judge 5), CAL-19 (4, 5), CAL-16 (5, 4), CAL-48 (5, 4).

The rubric says to compare passages with the ticket and ignore the reply. Human notes on CAL-14,
CAL-19, CAL-10 and CAL-15 give reasons about what the REPLY left out (for example CAL-14: "reply
defaults to the standard rotation flow and doesn't flag this priority"). On CAL-10 and CAL-15 the
judge happened to give the same score, so they are not disagreements, but the reasoning applies the
rubric differently from the judge.

## Finding for the report — VAL-0071

The 14 Sep draft for VAL-0071 told a customer who wants to avoid being stopped to "enable overage
protection", the opposite of DOC-BILL-003, and it was sent: the grounding guardrail passed it. The
15 Sep run held VAL-0071, but with a differently worded draft, so that run does not show the error
was caught. Treat this as a confirmed grounding miss in a sent reply.

## Open

- Making the judge trustworthy would need a calibration set with a spread of quality (including
  deliberately weak replies), scored blind. Not scheduled.
