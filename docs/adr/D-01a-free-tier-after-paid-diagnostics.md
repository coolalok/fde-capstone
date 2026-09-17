# D-01a — Graded configuration stays on the free tier (extends D-01)

**Status:** Accepted on the tier. The model within the free tier is OPEN: no free configuration has yet completed a validation run.
**Date:** 2026-09-17
**Decider:** Alok Kulkarni
**Constrains:** FR-04, FR-05, FR-13, FR-14, FR-15, FR-22, FR-23; NFR-01b, NFR-01c, NFR-08
**Affects:** `.env.example`, `src/config.py` (`MODEL_*`, `GUARDRAIL_*`), `evaluation/harness.py` (`--judge`), every B-21 result directory, the report's evaluation section

## Context

D-01 chose OpenRouter's free tier with `meta-llama/llama-3.1-8b-instruct`. Three things have happened since.

1. **That model is no longer free.** The id has no `:free` suffix and is billed; the OpenRouter account has no credit (commits 3f2e667, 38a6e9a).
2. **Free-tier calls failed far past D-01's 15% trigger.** The 13 Sep gate run on that model (`evaluation/results/b21_gate_20260913`) lost 46 of 80 classifications and 47 of 80 drafts to `APIConnectionError`. The same day's re-run log (`b21_rerun_20260913/run.log`) shows upstream 429s from four OpenRouter routes (Novita, Groq, DeepInfra, CoreWeave), then a 400 from Cloudflare rejecting `seed`. D-01's trigger names rate limits; the connection errors are a different cause with the same effect on routing.
3. **The clean runs were paid.** To get past the outage, the 14 and 15 Sep B-21 runs used OpenAI `gpt-4o-mini` for drafting, with `gpt-4o` (14 Sep) and `gemini-3.8-flash` (15 Sep) as the guardrail judge. Both completed 80/80 with zero failed calls. The fairness audit (B-24), the B-18 calibration drafts and the 17 Sep recomputed metrics all come from those runs.

A free retry on 17 Sep (`evaluation/results/b21_free_8_20260917`: `google/gemma-4-31b-it:free` drafting, `nvidia/nemotron-3-super-120b-a12b:free` judging) returned 429 on 7 of 8 classifications and 8 of 8 drafts. It measured availability, not quality.

The Build Specification is explicit about which way this should go: "A well-built system on a small free model out-scores a thin one on an expensive model."

## Options considered

**A. Stay on the free tier for the graded configuration; paid runs are diagnostics.**
Keeps the cost-nothing rule and NFR-08. Every figure measured so far describes a model the graded configuration does not use, and a free configuration still has to complete the gate run.

**B. Make paid OpenAI + Gemini the graded configuration.**
The only configuration with a clean 80-ticket run. Breaks the cost-nothing rule and NFR-08, and an assessor re-running the harness would need two paid keys.

Within A, the free provider is not chosen yet:

- **A1. OpenRouter `:free` models.** No code change. 8 of 8 drafts rate-limited on 17 Sep.
- **A2. Groq free tier.** The fallback D-01 itself named. Untested here: needs a Groq key, and its handling of `seed` and JSON mode through `src/config.py` has not been checked.
- **A3. Local Ollama.** No rate limits. Adds an install and hardware requirement on the assessment machine, which D-01 rejected for that reason.

## Chosen

**Option A.** The graded configuration runs on a free tier. The 14 and 15 Sep paid runs stay in the repository as diagnostic evidence and are labelled as such wherever they are cited.

The free model and provider are not chosen here. That choice needs a completed run, and none exists.

## Rationale

- The maintainer's decision, and the one the Build Specification rewards.
- The paid runs answered a narrower question: with provider failures removed, does the pipeline work end to end (A8, A9, A10)? They showed it does, and that answer does not depend on which model drafted.

## Consequences

- **Every quality figure measured so far describes `gpt-4o-mini`, not the graded model.** That covers intent accuracy 88.8%, unanswerable tickets auto-sent 13/27, the fairness table, recall@k, unknown-correctness and the Brier score. The report must say this beside each number.
- D-05b's 0.85 threshold was swept on `llama-3.1-8b-instruct`, a third model. It is not re-validated for whichever free model is chosen.
- **`--judge` stays off by default in the harness.** The pack does not require an LLM judge: its hallucination rate is "Human review of at least fifty responses, two assessors" (Evaluation Framework). NFR-01b and NFR-01c do specify judge-scored samples, but only from a judge calibrated to Spearman >= 0.70, and B-18 measured 0.35. Default-on would also add one call per draft against a rate-limited free provider. NFR-01b/c go to the Stage 5 revision log (B-22).
- Before submission, a free configuration still has to complete the 80-ticket gate run. If none does, the report says so and presents the paid runs as the only complete ones.

## Revisit trigger

- A free configuration completes the 80-ticket validation run with failed calls on at most 15% of tickets: record the model and its figures in a D-01b that closes the open part of this decision.
- Every free option (A1-A3) fails that bar: reopen Option B with the maintainer, stating the cost-nothing breach in the report.

## Supersedes / superseded by

None. Extends D-01, which stays in force on the provider-tier choice; its model choice (`llama-3.1-8b-instruct`) no longer holds, because that model is billed.
