# Prompt library

Prompts are design artefacts, versioned like code.

## Naming convention

`PR-<component>-<seq>` — e.g. `PR-CLASSIFY-01`, `PR-GENERATE-03`.

## Rules

Every prompt in this directory MUST:

1. Have a `requirement:` frontmatter field naming at least one FR.
2. Wrap user-provided data in delimiters (`<<TICKET_START>>` / `<<TICKET_END>>`) so ticket text is treated as data, not instruction (FR-18).
3. Return strict JSON matching a documented schema — never free-form.
4. Have at least three test cases: happy path, adversarial (injection / empty / malformed), and edge (non-fluent / long / ambiguous).
5. Bump `version` and append to `## Changelog` on any change that could plausibly alter output. Whitespace-only edits do not require a bump.

Prompts under `evaluation/` follow the additional discipline in
`capstone-prompt-writer` skill (position-bias randomisation, verbosity
penalty, generator-family exclusion, chain-of-thought before score,
decomposed rubrics — never a single overall score).

## Register

| ID              | Purpose                                         | Component | Version | Last changed | Notes                                    |
|-----------------|-------------------------------------------------|-----------|---------|--------------|------------------------------------------|
| PR-CLASSIFY-01  | Ticket intent + urgency + calibrated confidence | classify  | 1.3     | 2026-09-26   | FR-04, FR-05, NFR-05, R-04. Five test cases (T-01..T-05); T-04/T-05 are the same integration complaint in a fluent and a compressed register, asserted as a pair. Input scope documented (fairness-blind to tier/region/name/fluency). v1.3 makes `integration_help` reachable — its v1.2 cues occur in none of the 24 tickets carrying the label, and it was predicted 0 times in `dev_local_410_20260924` — and adds six adjacent-code boundary rules written as concept tests, not phrase matches, so a compressed restatement is not left behind. |
| PR-GENERATE-01  | Grounded answer with citations                  | generate  | 2.1     | 2026-09-23   | FR-13, FR-14, FR-15. Five test cases; four built on real dev tickets (DEV-0008/0091/0004/0005), injection case synthetic and labelled. v1.0.0 was unloadable and cited the wrong FRs — see its changelog. v2.1 adds the do-not-compute-a-figure scope rule (2 of 80 local drafts derived a number; both wrong). |
| PR-GUARDRAIL-PII-01 | Detects PII in the drafted response (emails, keys, phones, account numbers, third-party names) | guardrails | 1.0     | 2026-09-03   | FR-16, R-02. Six test cases (T-01..T-06) covering clean draft, email leak, API-key leak, injection-in-draft, third-party name, and placeholder text. Customer-blind — customer-name whitelist applied by src/guardrails.py, not by the prompt. Injection-safe via `<<DRAFT_START>>` markers. |
| PR-GUARDRAIL-GROUNDING-01 | Verifies every factual claim in the drafted answer is supported by a cited passage | guardrails | 1.0     | 2026-09-03   | FR-17. Five test cases (T-01..T-05) covering grounded happy path, extrapolation beyond passage, contradiction behind real citation, claim supported by NON-cited passage, and courtesy sentences not treated as claims. Fails SAFE — LLM error blocks send. Cross-checks the citation-matches-content requirement of FR-17 the generator's structural Self-RAG critic cannot check on its own. |
| PR-GUARDRAIL-TONESCOPE-01 | Blocks replies that make commitments about refunds, delivery timings, or product roadmap items | guardrails | 1.0     | 2026-09-03   | Implicit — no PRD FR yet; architecture.md §6 lists tone/scope as the fifth safety check. Traceability via R-04 (commitment/liability risk) + EV-D4 (Daniel: billing disputes become contractual). Six test cases covering clean draft, refund commitment, ETA commitment, roadmap commitment, adversarial injection, policy-description (not commitment). Injection-safe via `<<DRAFT_START>>` markers. FR-25 for tone/scope is intentional debt — logged in Stage 5. |
| PR-GUARDRAIL-RELEVANCE-01 | Checks the drafted reply addresses the question the customer actually asked | guardrails | 1.1     | 2026-09-20   | FR-14, R-01. Third check of the RAG triad (TruLens/TruEra: context relevance, groundedness, answer relevance) — only groundedness was implemented. Compares the answer to the QUESTION, and is deliberately NOT given the passages: a reply can be perfectly grounded and still answer a question nobody asked, which grounding passes every time. Three test cases (T-01..T-03): normal answered ticket, injection inside the drafted reply, vague non-fluent ticket answered off-topic. Abstention is never flagged as irrelevant. Fails SAFE. Built after the 13 Sep gate run showed 6 of 10 unanswerable tickets auto-answered with all five existing guardrails passing. |
| PR-GUARDRAIL-DRAFT-01 | One call returning the three draft-only guardrail verdicts: PII, tone/scope commitments, and answer relevance | guardrails | 1.0     | 2026-09-20   | FR-16, R-04 + EV-D4, FR-14 + R-01. A transport merge, not a judgement merge: one section per check, each mapped back to the guardrail that owns it, with the same categories and the same contract rules as PR-GUARDRAIL-PII-01, PR-GUARDRAIL-TONESCOPE-01 and PR-GUARDRAIL-RELEVANCE-01, which remain the specification of each check and the fallback when this call fails. Grounding is deliberately NOT merged — it needs the passages, and a groundedness judgement must not leak into a relevance one. pii and tone_scope are instructed to judge the reply alone although the ticket is now in context. Built after the 20 Sep measurement: the guardrail stage was 60% of prompt tokens and 56% of wall time, re-sending 4,865 tokens of instructions per ticket. Four test cases (T-01..T-04) including injection inside the reply. |
| PR-EVAL-JUDGE-01 | Scores one drafted reply on context relevance, groundedness and answer relevance (1-5 each) | evaluation | 1.1     | 2026-09-14   | NFR-01a/b/c, NFR-05. B-17. Reasoning-first JSON, decomposed rubric, verbosity rule, judge on a different model family from the generator; position bias n/a (single-response scoring). Three verbatim worked examples (VAL-0013 strong, VAL-0036 weak, VAL-0006 borderline) excluded from the B-18 calibration set. Cannot detect a ticket that should not have been answered. Not trusted until B-18 human agreement reaches Spearman >= 0.70. |

## Deferred to Week 2 (per Sprint Plan Table 3)

- `PR-RETRIEVE-01` — B-05, query rewriting for onboarding intent only per B-07 findings.

## Deferred to Week 3

- `PR-EVAL-HALLUCINATION-01` — B-17 dependency, claim extraction and verification.
