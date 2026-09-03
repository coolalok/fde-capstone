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
| PR-CLASSIFY-01  | Ticket intent + urgency + calibrated confidence | classify  | 1.2     | 2026-08-31   | FR-04, FR-05. Three test cases (T-01/T-02/T-03). Input scope documented (fairness-blind to tier/region/name). |
| PR-GENERATE-01  | Grounded answer with citations                  | generate  | 2.0     | 2026-09-03   | FR-13, FR-14, FR-15. Five test cases; four built on real dev tickets (DEV-0008/0091/0004/0005), injection case synthetic and labelled. v1.0.0 was unloadable and cited the wrong FRs — see its changelog. |

## Deferred to Week 2 (per Sprint Plan Table 3)

- `PR-RETRIEVE-01` — B-05, query rewriting for onboarding intent only per B-07 findings.
- `PR-GENERATE-02` — B-10, "I don't know" response for empty retrieval. PR-GENERATE-01
  assumes at least one passage and hands this case over, so B-11 needs both.
- `PR-GUARDRAIL-PII-01` — B-12.
- `PR-GUARDRAIL-GROUNDING-01` — B-13.

## Deferred to Week 3

- `PR-EVAL-JUDGE-01` — B-17, three-dim RAG rubric.
- `PR-EVAL-HALLUCINATION-01` — B-17 dependency, claim extraction and verification.
