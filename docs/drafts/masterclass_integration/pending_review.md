# Pending review — Masterclass concept coverage in the Week 2 build

**Created:** 2026-09-03 (Thu, Week 2 Day 4)
**Context:** After the Masterclass 3 / Masterclass 4 / RAG_demo audit and the B-12 review, `src/guardrails.py` (720 lines, FR-16..19) implements the intended concepts and in several places exceeds the reference (richer PII regexes, LLM+regex belt-and-braces, fail-safe on error, pluggable model call, decision-log trace shape). What remains below is the honest concept-coverage residue — the pieces that are either genuinely absent, deferred by decision, or need one verification step before we can call them done.

Nothing here is on the Stage 4 sprint plan today. Review these before opening any decision that would add or move them.

---

## 1 · Adversarial regression fixture — GAP, cheap fix

**Concept:** Masterclass 4 slide 6, Adversarial suite tier. *"Every jailbreak or injection that worked once becomes a permanent regression test."*

**Current state:** No `tests/fixtures/guardrail_attacks.json` or equivalent accumulating file. Test cases live inline in individual test files (`test_guardrails.py`, `test_classify.py`), so attacks discovered during dev / evaluation have no central home and will not automatically accrue as regression cases.

**Why it matters:** The whole point of the discipline is that a bypass, once found, cannot silently return. Inline test cases don't carry that property — they get added ad-hoc and lost when files are refactored.

**Concrete fix (≈15 min):**
- Create `tests/fixtures/guardrail_attacks.json` with a documented schema.
- Move the injection case currently in `PR-GUARDRAIL-PII-01.md` T-02 (and any others) into it as seed entries.
- Add a parametrised test in `tests/test_guardrails.py` that iterates the fixture and asserts every entry blocks.
- Convention: whenever a bypass is found during evaluation or manual testing, a new entry lands here before the fix is merged.

**Owner:** Alok. **When to do:** before Fri 4 Sep Week 2 gate — the gate reviews A7 (guardrail blocks), and having the fixture in place is cheap A7 evidence.

---

## 2 · Cost / rate-limit / circuit-breaker layer around LLM calls — VERIFY THEN DECIDE

**Concept:** Masterclass 3 §Cost & Latency Tradeoffs, Masterclass 4 §Cost pillar. Token budgets and kill-switches on outbound LLM calls; retry-with-backoff for transient failures; circuit breaker when the endpoint is degrading.

**Current state:** `_openrouter_call` in `src/guardrails.py` (and presumably a twin in `src/generate.py`, `src/classify.py`) is a bare synchronous call with `temperature=0.0` and `seed=0` — no per-call token cap, no exponential backoff, no circuit breaker on repeated failures. The guardrail-level fail-safe (return `passed=False` on any exception) is a good backstop but is not a cost control.

**Verification needed:** check whether these live somewhere other than the LLM callers:
- `src/metrics.py` — token counters and cost estimation
- `src/config.py` — token/cost caps as configuration
- Some wrapper module — retry/backoff/circuit-breaker
- `.github/workflows/ci.yml` — timeout enforcement

**Only after verification, decide:** if these controls are already present elsewhere, this is not a gap — close the review item. If they are not present, this is a real A11 gap (graceful degradation on rate-limit / outage). A11 is one of the two acceptance criteria most likely to bite in the hidden 120-ticket run.

**Owner:** Alok. **When to do:** verification 10 min, before deciding whether to add a backlog row. Do the verification before Fri 4 Sep so the gate has a definitive answer either way.

---

## 3 · LLM-as-judge for evaluating the guardrails — DEFERRED, revisit at B-17

**Concept:** Masterclass 4 slide 6, "LLM-as-judge" tier of layered evaluation. A separate judge model scoring the guardrails' precision/recall against a labelled set — the way we learn if PII detection actually catches PII, if grounding actually catches ungrounded claims.

**Current state:** Consciously deferred to Week 3 as `PR-EVAL-JUDGE-01` under backlog row B-17. Prompts/README register carries it in the deferred list.

**Why it stays deferred:** Week 2's job is to build the guardrails; Week 3's job is to measure them. No sequencing benefit to pulling it forward.

**Watch item:** if B-16 (confidence threshold sweep) produces numbers that need faithfulness signal, this may need to advance. Otherwise leave until B-17.

---

## 4 · Retrieval-relevance hard floor (my proposed FR-GUARD-04) — DEFERRED at PRD Q7

**Concept:** RAG_demo `min_relevance_score` gate, echoed by Masterclass 4 slide 8 output-validation layer. Below a top-hit similarity floor, block generation regardless of any other signal.

**Current state:** Consciously deferred by PRD Table 9 Q7 (2026-09-03) to Week 3 candidate. `src/guardrails.py` implements the CONCEPT of a floor-based hard block via `ConfidenceFloorGuardrail` (FR-19), but against classifier confidence — a calibrated posterior — rather than retrieval similarity. D-05a carries the amendment note.

**Watch item:** if the B-16 sweep shows classifier confidence is not enough on its own to catch retrieval-empty-but-classified-high edge cases, revisit Q7 and add the retrieval floor as a second signal. Until then this is closed by design.

---

## Sequencing note

Per capstone-conventions Rule 1: none of the above extends the Stage 4 backlog with new B-XX rows today. Items 1 and 2 may earn a row after review; items 3 and 4 stay deferred by prior decision.

The one item that arguably deserves action before the Fri 4 Sep Week 2 gate is item 1 (adversarial fixture), because it directly evidences A7. Item 2 needs the 10-min verification step before we can even decide whether it's a gap.

---

# B-13 review — issues found 2026-09-03 (Thu)

Independent reviewer flagged four issues in `PR-GUARDRAIL-GROUNDING-01.md` and its wiring. I verified all four against the actual files and the corpus. All confirmed. Logged here for later fix; none applied yet per user's "Stop".

## 5 · Fabricated doc titles + no `Source:` labels — Data fidelity Rule 1 & Rule 2 violation

**File:** `prompts/build/PR-GUARDRAIL-GROUNDING-01.md` (test cases T-01 through T-05).

**What's wrong:** Three real corpus doc_ids are cited with invented titles and invented passage bodies, none labelled as synthetic.

| doc_id | Prompt asserts | Corpus (`data/documentation.json`) actually says |
|---|---|---|
| `DOC-AUTH-001` | title `'MFA reset guide'` | `'Resolving invalid credential errors on login'` |
| `DOC-AUTH-002` | title `'Password reset guide'` | `'Multi-factor authentication setup and recovery'` |
| `DOC-BILL-002` | title `'Refund policy'` | `'Changing plans, and how proration is calculated'` |

T-03 goes further: it invents a "5-7 business days refund" policy attributed to `DOC-BILL-002`, which is actually about proration on plan changes. That is the exact failure pattern the file exists to detect — fabricated content behind a real citation — and the prompt is committing it inside its own test suite. `grep -c "Source:"` on the file returns 0, so Rule 2 (mark paraphrase as paraphrase) is also broken.

**Why it matters more here than anywhere else:** PR-GENERATE-01's scope rules explicitly forbid promising refunds, and the whole subject of this guardrail is grounding integrity. This is the last file in the repo that should carry fabricated grounding claims.

**Concrete fix (≈30 min):** Rewrite T-01 through T-05 using verbatim passage text pulled from `data/documentation.json` for the three doc_ids (corpus content already has real MFA / login / proration guidance to build cases on top of). Titles must match the corpus. Every case gets a `**Source:** DOC-<id> (verbatim from data/documentation.json)` line for passage text and `**Source:** synthetic` for invented answers. Keep the same five failure archetypes (happy path / extrapolation / contradiction / wrong-citation / courtesy) but ground them in real corpus text.

**Owner:** Alok. **When:** before B-14 (guardrails wiring) closes — the test cases feed harness assertions.

---

## 6 · Contract enforcement not implemented — real FAIL-OPEN path

**Files:** `prompts/build/PR-GUARDRAIL-GROUNDING-01.md` (Notes section), `src/guardrails.py` (`GroundingGuardrail.check`).

**What's wrong:** The prompt's Notes section says:
> "if the LLM returns `passed=true` with non-empty `unsupported_claims`, or vice versa, force the response into a block with reason `\"grounding_guardrail_contract_violation\"`."

`grep 'data\["passed"\]\|contract_violation\|grounding_guardrail_contract' src/guardrails.py` returns zero matches. The code (line ~292 of `guardrails.py`) reads only `unsupported_claims`, never `data["passed"]`. Two directions:

| LLM output | Guardrail behaviour today | Correct behaviour |
|---|---|---|
| `passed=false`, `unsupported_claims=[]` | Returns `passed=True` (empty claims → clean pass) — **FAILS OPEN** | Block with `grounding_guardrail_contract_violation` |
| `passed=true`, `unsupported_claims=[…]` | Returns `passed=False` (non-empty → block) — safe by accident | Block with `grounding_guardrail_contract_violation` |

The first row is a real safety hole in a guardrail explicitly designed to fail SAFE. A model that says "this failed" but forgets to fill the claims array gets silently trusted.

**Concrete fix (≈10 lines):** In `GroundingGuardrail.check`, after `_parse_json_verdict`:
```python
llm_passed = data.get("passed")
if isinstance(llm_passed, bool) and llm_passed != (len(unsupported) == 0):
    return GuardrailResult(
        name=self.name, passed=False, blocking=self.blocking,
        reason="grounding_guardrail_contract_violation: LLM's `passed` field "
               f"({llm_passed}) disagrees with `unsupported_claims` "
               f"(len={len(unsupported)})",
        details={"llm_passed": llm_passed, "unsupported_claims": unsupported},
    )
```
Plus one unit test per direction in `tests/test_guardrails.py`.

**Owner:** Alok. **When:** highest-priority of the four B-13 items — a fail-open in a safety guardrail. Do before Fri 4 Sep gate.

---

## 7 · R-01 missing from B-13 frontmatter and prose

**File:** `prompts/build/PR-GUARDRAIL-GROUNDING-01.md`.

**What's wrong:** B-13's sprint-plan DoD says "Cites FR-17, R-01." The frontmatter shows only `requirement: FR-17`. `grep 'R-01'` on the file returns zero. R-01 in the Stage 1 risk register is "confidently incorrect answers" — the reason FR-17 exists — and B-12 handled its equivalent by naming R-02 in prose. B-13 didn't.

**Concrete fix (≈2 min):**
- Frontmatter: `requirement: FR-17, R-01`
- Add one sentence to "What this prompt is for": *"This guardrail is the code-level mitigation for R-01 (confidently incorrect answers) — the risk that a plausible-sounding answer gets past every other check and reaches the customer."*

**Owner:** Alok. **When:** trivial edit, ship with the fix for #6.

---

## 8 · Critic seam wired in generate.py's docstring but not in code

**Files:** `src/generate.py` (docstring), `src/guardrails.py` (`GroundingGuardrail`).

**What's wrong:** `generate.py`'s module docstring says:
> "`critic` is a `(response, passages) -> CritiqueResult` callable — the default is the structural check below; B-13 (PR-GUARDRAIL-GROUNDING-01) will slot a semantic critic in via the same seam."

But `GroundingGuardrail.check` returns `GuardrailResult`, not `CritiqueResult` — different type. And nothing in the codebase passes `GroundingGuardrail` (or an adapter) to `generate()`'s `critic` parameter. So the retry loop never sees semantic grounding feedback: a fabricated-fact draft is blocked and escalated, not retried and fixed.

**Consequence for D-06:** D-06 says the retry loop "converts about half of the would-be blocks into a corrected answer." As implemented, that only applies to STRUCTURAL failures (bad citations, schema violations). Semantic failures (unsupported claims) never get a retry — they always escalate.

**Two ways to close this — pick one:**

- **Option A — wire it.** Write a `SemanticCritic` adapter class in `src/guardrails.py` that wraps `GroundingGuardrail.check` and returns `CritiqueResult(passed, unsupported_claims: list[str])`. Pass it as the default `critic=` in `src/api.py` where `generate()` is invoked. Cost: ~30 lines + one test. Payoff: honours D-06's claim; semantic failures get one retry.

- **Option B — amend the docstrings and the ADR.** Edit `generate.py`'s docstring to say "B-13 is a POST-HOC guardrail, not a critic — semantic failures are caught after generation completes and escalate directly." Add an amendment note to D-06 that the "half converted" figure applies only to structural failures. Cost: 5-line docstring edit + one paragraph in D-06. Payoff: honesty; documentation matches code.

**Recommendation:** A is the design-correct fix and it's not expensive. B is the honesty patch if A doesn't fit the Fri 4 Sep window. Do NOT ship with the current mismatch — that's an unforced credibility loss in the video walkthrough.

**Owner:** Alok. **When:** decide before Fri 4 Sep gate. Whichever path, it's a small change.

---

## Priority order for the eight items in this file

1. **Item 6 (fail-open path)** — safety hole, ~10 lines. Do first.
2. **Item 1 (adversarial fixture)** — A7 evidence for the gate, ~15 min.
3. **Item 8 (critic seam)** — either A or B, both cheap. Pre-gate.
4. **Item 5 (fabricated titles)** — ~30 min. Pre-gate for defensibility.
5. **Item 7 (R-01 citation)** — 2 min. Ship with #6.
6. **Item 2 (cost / rate-limit verification)** — 10-min check, decide after.
7. **Items 3, 4** — deferred by prior decision, revisit at gate.
