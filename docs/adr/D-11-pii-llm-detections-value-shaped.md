# D-11 — An LLM PII detection must be shaped like the value it names

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-16
**Affects:** `src/guardrails.py` (`_llm_detection_is_value_shaped`, `PIIGuardrail._call_llm`), PR-GUARDRAIL-PII-01 (unchanged)

## Context

The PII guardrail runs a regex pass and an LLM pass (PR-GUARDRAIL-PII-01) and blocks on any detection from either. On the 80-ticket local run (b21_local_80_20260919, judge `qwen2.5-7b-ctx8k`) it blocked three drafts, and every one was an LLM detection that could not be the value it claimed:

| Ticket | Category | Detected text |
|---|---|---|
| VAL-0019 | api_key | `API keys` |
| VAL-0049 | api_key | `DOC-AUTH-004` |
| VAL-0068 | api_key | `all API keys` |

VAL-0019 and VAL-0049 are labelled `auto_respond`, so these blocks cost two correct replies. The OpenAI and Gemini 80-ticket runs recorded no PII blocks at all. The regex pass already exempts citation markers for the same reason (DEV-0485, `_mask_citation_markers`).

## Options considered

**A. Keep every LLM detection (as before).** Every judge misreading is a block.

**B. Only block on regex hits; the LLM advises.** Removes the false positives, and also removes the LLM's reason to exist: person names and structured values the regex does not know.

**C. Keep LLM detections only when their text is shaped like the category's value.** A help-article id is never PII; an api_key is one unbroken token of 12+ characters; a phone has 7+ digits; an account number has a digit; email and person_name are kept as reported.

**D. Revise PR-GUARDRAIL-PII-01 to tell the judge not to flag words or article ids.** A request to the model, not a control; a 7B judge that misreads "API keys" as a key is the reason it is needed.

## Chosen

**Option C.**

## Rationale

The floors are properties any real value has, so they cannot hide a real leak of that category: a phone number without seven digits is not dialable, and a credential with a space in it is not a credential. Replayed over the stored detections of all three 80-ticket runs, the filter drops exactly the three rows above and nothing else. The regex pass is untouched, and name detection, the LLM's main job, is untouched.

## Consequences

- Positive: on the stored verdicts of the local run, VAL-0019 and VAL-0049 passed the other five guardrails, so both would have been sent, and both are labelled `auto_respond`. VAL-0068 would still be held: its intent, `security_incident`, is on the D-07 never-auto-respond list.
- Negative: an api_key the regex does not recognise and that is shorter than 12 characters is no longer caught by the LLM pass. Every key format the regex knows is 16+ characters.
- The zero-occurrence private-data condition is still checked independently on every sent reply by `evaluation/results_table.py`, using the regex patterns.

## Revisit trigger

A leaked value found in a sent reply whose LLM detection this filter discarded (the discard is logged as `guardrails.pii.llm_detection_discarded`).

## Supersedes / superseded by

None.
