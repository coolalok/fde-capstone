# D-16 — Input-side injection detection, and escaping the prompt delimiters

**Status:** Accepted
**Date:** 2026-09-20
**Decider:** Alok Kulkarni
**Constrains:** FR-10, FR-12, FR-18; mitigates R-03
**Affects:** `src/injection.py` (new), `src/ingest.py`, `src/schema.py` (`Ticket.injection_flags`), `src/route.py` (rule 2b), `src/prompt_loader.py` (`escape_delimiters`), `src/metrics.py`, `evaluation/harness.py`, `tests/fixtures/injection_probe.json`
**Partially reverses:** PRD Table 9 Q7 (2026-09-03), which deferred FR-GUARD-01..04. Only the injection-heuristic part of FR-GUARD-02 is taken up here.

## Context

The defence against prompt injection was entirely output-side: FR-18 blocks a draft showing persona-shift markers or fabricated citations, and every prompt wraps ticket text in `<<TICKET_START>>` / `<<TICKET_END>>` and instructs the model to treat it as data.

On 2026-09-20 six crafted attacks were run through the live pipeline on the local configuration (`tests/fixtures/injection_probe.json`): instruction override, delimiter spoof, system-prompt probe, persona override, fabricated-citation request, and a DAN-style jailbreak.

**The result was good and the reason was not.** No attack succeeded: no draft carried the payload, no reply was sent, every ticket was blocked. But **FR-18 fired on none of them**. The blocks came from answer relevance (5 of 6), tone/scope (3) and the confidence floor (1). FR-18 catches a model that *complied*; when the model resists, FR-18 sees nothing. So:

1. **An attempt was indistinguishable from an ordinary blocked ticket.** Nothing in the metrics report, the decision log or the results file said "someone tried to take over the system". R-03's mitigation says to record the input for review; nothing did.
2. **The delimiter boundary is forgeable.** INJ-02's body contained our own `<<TICKET_END>>` marker followed by a `SYSTEM:` block. The model ignored it, which is luck rather than architecture.

## Options considered

**A. Leave it; the probe passed.** Defensible on the evidence — nothing got through. It rests on the drafting model continuing to resist, on every future model, and leaves attempts invisible.

**B. Input-side heuristic detection, escalate and record.** A deterministic pattern match on the raw ticket text before any model call, carried on the Ticket, read by the router as rule 2b: escalate with `trigger="injection_suspected"`, name the shapes in the reason, count them in the metrics report and on `/metrics`.

**C. B, plus refusing the customer**, as the RAG_demo reference implementation does ("Your message looks like it's trying to override the assistant's instructions").

**D. A model-based injection classifier.** Another call per ticket on a pipeline already spending six.

## Chosen

**Option B**, plus escaping the delimiters.

**C is wrong for this product.** The demo is a chat assistant answering its own users; a refusal is a reasonable reply. Here the input is a support ticket, and "ignore the previous instructions" may be a quoted error message, a developer describing their own prompt, a frustrated customer, or an attack. Refusing means the automation tells a paying customer their ticket looks malicious. Escalation costs nothing and is right in all four cases.

**D was rejected on cost and evidence.** Latency is already the worst-performing NFR (p95 70s local, 23s hosted against a 4s requirement), and the dev set contains zero injection attempts, so there is nothing to train or validate a classifier against.

**Precedence: rule 2b, after the safety block and before the policy rules.** A draft with a real fault in it is a block whatever the ticket said — the stronger statement wins and the draft is withheld. Everything below it would otherwise report a downstream symptom: on the probe, "low confidence" or "the reply does not address the question", which is exactly the invisibility this ADR exists to fix.

**Delimiter escaping** turns `<<ANY_MARKER>>` in a substituted value into `[[ANY_MARKER]]` at render time, in `prompt_loader.render_user`, so it covers every prompt at once. Escaped rather than stripped: the reviewer must see what the customer actually sent, and the guardrails must still be able to judge it. The template's own markers are untouched.

## Consequences

- **The heuristic will miss things**, and one of the six probe attacks (INJ-05, which asks for a fabricated citation and a guarantee) is not an override shape and is not flagged. That is recorded as a test, not left as a surprise: the grounding and citation-resolution checks own that case.
- **False positives escalate, they never refuse.** `act as` is dropped from the reference pattern list because support tickets legitimately say "act as the account owner". Four benign phrasings are held by tests.
- **Attempts are now countable**: `injection_flags` per ticket in results.jsonl, `injection_suspected` in the metrics report, and an `injection_flags_total` counter labelled by shape on `/metrics`.
- **Detection runs on the RAW text**, before cleaning normalises whitespace, so an attempt is recorded as the customer wrote it.
- **This does not make the system injection-proof**, and the report should not claim it does. It adds a cheap, visible layer in front of a defence that held on one probe of six attacks against one pair of models.

## Revisit trigger

- Any probe attack reaches a customer, or any real ticket is found to have influenced a sent reply: the heuristic becomes insufficient and option D returns with evidence to validate it against.
- False flags appear on real tickets often enough to be a fairness problem (a tier or a fluency group flagged more than others): re-tune the patterns and report the rate in the fairness audit.
- FR-GUARD-01..04 are taken up properly in a later version: this ADR is then superseded by whatever FR-GUARD-02 becomes.

## Supersedes / superseded by
- Partially reverses PRD Table 9 Q7's deferral, for the injection-heuristic half of FR-GUARD-02 only. Input length caps, output PII redaction and the retrieval-confidence gate stay deferred.
