# Architecture

*The system architecture for CloudServe Draft. Where the PRD (`workbooks/Stage_2_PRD_Template.docx`) says what the system must do, this document says how the pieces fit together. Every design choice below has an ADR file in `docs/adr/` that explains what else was considered and what would make us change our minds.*

## The high-level shape

Six components, one after the other, with three cross-cutting concerns that touch several of them. The overall pattern is called a **Router** agent: the classifier reads the ticket and hands it off to one of three outcomes — `auto_respond`, `escalate`, or `block`. On the reply-drafting step, the system runs a self-check on the draft's citations: every cited article must be one that search returned, and a real answer must cite something (see ADR D-06, amended by D-06a). If the self-check fails once, one retry. Whether the draft's claims are actually supported by the cited text is checked afterwards by the grounding guardrail, which blocks the reply rather than retrying.

```
INGEST → CLASSIFY → RETRIEVE → ROUTE → GENERATE → VALIDATE
                     |           |         |          |
                     └─ decision log · metrics · guardrails ─┘
```

## Design decisions at a glance

Every non-obvious design choice gets a row here. Read the linked ADR for what else we considered, why we picked what we picked, and what would make us change our minds later.

| ID   | Decision                       | Options we considered                                          | What we picked                                   | Why (one sentence)                                                                                              | Date       |
|------|--------------------------------|----------------------------------------------------------------|--------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|------------|
| [D-01](adr/D-01-model-provider.md)  | AI model provider           | OpenRouter free tier · Groq free tier · Local Ollama          | OpenRouter (Llama 3.1 8B)                        | Setup Guide default; broadest model catalog on a single API key; nothing to install on the assessment machine.  | 2026-08-30 |
| [D-01a](adr/D-01a-free-tier-after-paid-diagnostics.md) | Graded configuration after the free model failed | Free tier, paid runs as diagnostics · Paid OpenAI + Gemini as graded | Free tier; free model still OPEN | `llama-3.1-8b-instruct` is now billed and both recorded free runs (13 and 17 Sep) lost most calls to outages or 429s; the Build Specification rewards a free model, so the clean 14-15 Sep paid runs are diagnostics only. | 2026-09-17 |
| [D-08](adr/D-08-model-response-cache.md) | Handling free-tier rate limits | Treat throttling as environmental · Cache + bigger retry budget · Cache + tenacity + concurrency semaphore · Keep paying | On-disk response cache, retries 2 -> 5, pacing only after a refusal | The Build Spec calls rate limits a design problem and encourages caching; the SDK already backs off with jitter, and the harness is serial, so the cache is the missing piece and a semaphore would be a no-op. | 2026-09-19 |
| [D-02](adr/D-02-embedding-model.md) | Search-embedding model      | `all-MiniLM-L6-v2` · `BAAI/bge-small-en-v1.5` · TF-IDF fallback | `all-MiniLM-L6-v2` (verified 2026-08-31)          | Verified in B-07 against 357 dev tickets — 91.0% top-3 hit rate, within 3 points of the TF-IDF baseline, better on non-fluent English (fairness win). See `workbooks/d02_findings.md`. | 2026-08-30; verified 2026-08-31 |
| [D-03](adr/D-03-decision-log-store.md) | Where the decision log lives | SQLite · PostgreSQL · JSONL                                 | SQLite at `storage/decisions.db`                  | No database service to run; standard library only; reconciliation is a single SELECT; PostgreSQL would be extra setup for no benefit at this scale. | 2026-08-30 |
| D-04 | How articles are split into chunks | Fixed 800 chars, 120 overlap · Section-aware, 1500 cap · Sentence-boundary | *Provisionally fixed 800/120 — final ADR is backlog item B-08* | Q3 pilot: fixed 800/120 gave 93.6% top-3, section-aware gave 92.4%. Final ADR can now be written now that B-07 has cleared the dense-retrieval measurement. | (B-08, this week) |
| [D-05](adr/D-05-confidence-threshold.md) | Confidence threshold above which the system auto-replies | 0.80 fixed · 0.85 · 0.70 · Set by measurement | Set by measurement (data-driven sweep); provisional value 0.80 until B-16 | Project Brief mandates that this be set from data; the precision-first constraint (≥0.95) comes from EV-M3 (Marcus: "I would rather it said nothing than said something wrong"). | 2026-08-30 |
| [D-05b](adr/D-05b-confidence-threshold-measured.md) | The measured confidence threshold | 0.80 · 0.85 · 0.90 · 0.95 | 0.85, provisional — precision floor UNMET | B-16 swept 0.50-0.95 on 80 validation tickets: no threshold reaches the 0.95 precision floor (ceiling 0.760). 17 of 18 false positives are tickets the docs cannot answer, so answerability — not confidence — is the binding constraint. | 2026-09-04 |
| [D-06](adr/D-06-agent-architecture-pattern.md) | Overall agent pattern | Router · ReAct · Plan-and-Execute · Self-RAG · Hybrid | Router with an inline Self-RAG self-check on the draft; retry cap 1 | Q3 pilot showed search is essentially a solved problem on this corpus; the engineering value shifts to the draft-and-safety-check layer sitting on top. | 2026-08-30 |
| [D-06a](adr/D-06a-self-rag-critic-as-built.md) | What the Self-RAG critic checks | Semantic critic in the loop · Structural critic + blocking grounding guardrail · Grounding verdict fed back into the retry | Structural critic in the loop; semantic grounding as a blocking guardrail (as built) | The grounding guardrail blocked 3 of 80 drafts on the local run, so a semantic in-loop critic would recover at most 3 tickets for one more model call per ticket; recorded because D-06 described a semantic critic that was never built. | 2026-09-20 |

| [D-02a](adr/D-02a-retrieval-distance-metric-and-threshold.md) | Retrieval distance metric + relevance threshold | Keep l2 and lower the floor · Cosine space, re-calibrate · Normalise the embeddings | Cosine space; threshold 0.25 set by measurement | The l2 default scored passages from -0.094 to 0.650, so the uncalibrated 0.35 floor discarded 42% of correct answers (hit@3 52.4% vs 94.1%); cosine puts scores in a real [0,1] range and 0.25 sits at the recall ceiling. | 2026-09-03 |
| [D-07](adr/D-07-never-auto-respond-policy.md) | How the router knows a ticket must never be auto-answered | Read labels.must_not_auto_respond · Fixed intent policy list · A second classifier | Fixed policy list of four intents | The label is evaluation ground truth and FR-01 v2 keeps it off the Ticket; the four intents reproduce it at precision/recall 1.000 on 500 dev + 80 validation tickets. | 2026-09-04 |
| [D-03b](adr/D-03b-decision-log-write-failure-policy.md) | What happens when a decision-log write fails | Raise (kill the ticket) · Swallow silently · Swallow, report, and refuse to auto-respond | Swallow operational failures, flag the decision as unlogged, router escalates it | FR-20 exists so EV-M5's auditor can reconstruct any action; degrading the *action* preserves that where degrading the *record* would not. | 2026-09-03 |
| [D-09](adr/D-09-retrieval-query-text.md) | What text retrieval searches with | Body alone · Subject + body · Dense + BM25 fused by RRF | Subject + body, dense only | On 357 answerable dev tickets the subject lifts hit@1 from 87.7% to 89.9%; RRF hybrid is worse than dense on the body and ties it with the subject, so a lexical index earns nothing. | 2026-09-20 |
| [D-10](adr/D-10-no-answerability-gate-from-retrieval.md) | Whether to gate on answerability before generation | Retrieval-feature gate · No gate · Model-judged sufficiency check | No gate | Six retrieval features reach AUC 0.64 (dev, cross-validated) against answerable_from_docs; the dev-chosen gate would have held 0 of the local run's 14 wrong sends. | 2026-09-20 |
| [D-11](adr/D-11-pii-llm-detections-value-shaped.md) | Which LLM PII detections block | Keep all · Regex only · Keep only value-shaped · Prompt revision | Keep only value-shaped (article ids never; api_key an unbroken 12+ char token; phone 7+ digits; account a digit) | All three PII blocks in the 80-ticket local run were the judge flagging the words "API keys" or an article id; replayed over every stored detection the filter drops those three and nothing else. | 2026-09-20 |
| [D-12](adr/D-12-concurrent-guardrails.md) | Guardrails in turn or concurrently | In turn · Thread pool, results in order · Call LLM guardrails only when a cheap check is inconclusive | Thread pool, at most 4 at once (`GUARDRAIL_MAX_WORKERS`) | Identical verdicts on 20 replayed drafts either way; on hosted models the guardrail stage fell from 10.1 s to 3.1 s (ticket p95 24.2 s to 12.2 s); 1.11x on a local judge, which needs OLLAMA_NUM_PARALLEL > 1. | 2026-09-20 |
| [D-13](adr/D-13-bounded-model-call.md) | What bounds one model call | Lower the httpx timeout · SIGALRM · Daemon thread with a caller-side deadline · Async client | Caller-side deadline, `MODEL_CALL_DEADLINE_SECONDS` (180 s) | MODEL_TIMEOUT_SECONDS is an httpx gap-between-bytes timeout that a provider streaming keep-alives resets forever; a 20 Sep run hung over seven minutes on a healthy endpoint and had to be killed, which breaks A9. | 2026-09-20 |

D-04 gets its own ADR file this week (backlog item B-08). Now that the dense-retrieval measurement is in, the chunking decision can be finalised on the same evidence base.

## The six components — what each one does

### 1. Ingest — FR-01, FR-02, FR-03
- **What it does:** takes the raw ticket from any of the four channels (email, chat, docs_comment, forum) and turns it into one internal shape the rest of the pipeline can work with.
- **Inputs:** the raw ticket record.
- **Outputs:** a normalised `Ticket` object. Keeps `original_body`, `channel`, `received_at`, and all the customer-segment fields.
- **Edge cases it handles:** empty subject (every chat ticket has this by design — 155 of 155 in the dev set, per EV-DATA-11); unusual characters; empty body (unseen in the dev data but possible in the hidden test set). If anything is wrong, the ingest step adds an entry to `Ticket.warnings` rather than throwing an exception.

### 2. Classify — FR-04, FR-05
- **What it does:** reads the ticket and returns three things — the ticket type (one of 22), how urgent it is, and how confident the classifier is in its answer.
- **Outputs:** a `ClassificationResult` object with `intent`, `urgency`, `confidence` (a number between 0 and 1), and `alternatives` (up to two other plausible ticket types).
- **The 22 ticket types:** listed in `docs/intent_classes.md`.
- **What the classifier deliberately doesn't see:** `customer_tier`, `customer_region`, `customer_name`, `language_fluency`. This is a fairness decision — see `prompts/build/PR-CLASSIFY-01.md`, "What the classifier sees, and what it does NOT" section. Tier-aware policy lives in the router, not the classifier.
- **What happens if the AI model fails:** the classifier returns `intent='unknown'`, `confidence=0.0` and an `error` field describing what went wrong. It never lets an exception surface (FR-05).

### 3. Retrieve — FR-06, FR-07, FR-08
- **What it does:** takes the ticket's subject and body (D-09; the body alone when there is no subject), searches the 29 help articles, and returns the top matching passages with their scores.
- **Design settings:** chunks of 800 characters with 120-character overlap (D-04, provisional), embeddings from `all-MiniLM-L6-v2` (D-02, verified 2026-08-31), index built in cosine space with a 0.25 relevance floor (D-02a, measured 2026-09-03). Each chunk is embedded with its article title and category prepended (B-30).
- **When search finds nothing:** if no passage scores above the `RETRIEVAL_THRESHOLD` set in the config, the retriever returns an empty list. Downstream, that means the router will escalate the ticket to a human.
- **The floor is not an answerability test (D-02a):** at 0.25 only 14 of 143 non-answerable dev tickets return nothing, so a non-empty passage list is *not* evidence the ticket can be answered. Deciding that is the router's job — classifier confidence, the must-not-auto-respond types, and the guardrails. Raising the floor to make it a stronger signal costs recall much faster than it buys precision.
- **The metric and the threshold are coupled:** 0.25 is calibrated against cosine scores. An index built in another distance space makes the number mean something else, which is how the 0.35 default came to discard 42% of correct answers. `retrieve._assert_distance_space` logs an error at open time if the index on disk does not match.

### 4. Route — FR-09, FR-10, FR-11, FR-12
- **What it does:** looks at the classifier's confidence, the retrieval result, and the guardrail outcomes, then decides one of three things — `auto_respond`, `escalate`, or `block`.
- **Deterministic (FR-09, A5):** the same input always produces the same decision and the same reason. This holds structurally, not by argument: `route()` is a pure function of values earlier stages already computed — no clock, no randomness, and **no model call of its own**. (An earlier version of this line credited `temperature=0.0`; that is what makes the *generator* reproducible, not the router.)
- **On escalate:** the router passes along the retrieved passages, the classifier's top three alternatives, any draft the system produced, and tier 1's flag of what wasn't clear. That closes the missing-context loop Daniel complained about in the interviews (EV-D1).
- **Some intents never auto-answer (D-07):** `compliance_request`, `security_incident`, `feature_request` and `unclear_request` escalate at any confidence. FR-10 v1 keyed this off `labels.must_not_auto_respond`, which the router cannot see — labels are evaluation ground truth and FR-01 v2 keeps them off the Ticket. The intent policy reproduces that flag exactly on both labelled sets (87/87 dev, 14/14 validation) because EV-DATA-10 shows the flag is driven by ticket type. Caveat: measured against *true* intent, so live coverage is bounded by classifier recall on those four classes — measured at B-21.
- **Rules are ordered, first match wins:** unlogged decision, then guardrail block, then the D-07 policy, then empty retrieval, then generator-unknown, then the confidence floor. FR-12 requires the reason to name the cause, so precedence is part of the contract.
- **Escalations carry an EscalationBundle (FR-11):** the retrieved passages, the classifier's top-3 alternatives, the draft, and the point where the system was unsure — which in an automated pipeline is the rule that fired. A draft blocked by a guardrail still travels, flagged `draft_blocked`, so the reviewer sees what was caught; it is never sendable as-is.
- **Unlogged decisions force escalation (D-03b):** if the decision-log write failed, the upstream result arrives with `decision_logged=False`. The router must escalate on that alone, checked before the confidence threshold. A reply the autumn compliance review couldn't reconstruct (EV-M5) must not be sent automatically, however confident the classifier was.

### 5. Generate — FR-13, FR-14, FR-15
- **What it does:** takes the ticket and the retrieved passages, and writes a reply that cites its sources. Returns JSON with `answer`, `citations[]`, `confidence`, and an `unknown` flag.
- **Safety:** the ticket text is wrapped in markers (`<<TICKET_START>>` / `<<TICKET_END>>`); any instructions inside those markers are ignored, per FR-15.
- **Self-check (D-06, amended by D-06a):** once the draft is written, a structural critic checks its citations: every cited `doc_id` was retrieved, a real answer carries at least one citation, and an "I don't know" carries none. If that fails, one retry with the problems flagged. The critic does not read the answer against the passage text. That semantic check is the grounding guardrail (FR-17), which runs after generation and blocks an unsupported draft; it does not trigger a retry.

### 6. Validate (guardrails) — FR-15 through FR-19
Five safety checks. All of them block, never just warn.

- **PII guardrail (FR-16):** blocks replies containing emails, API keys, phone numbers, account numbers, or other customers' names.
- **Grounding guardrail (FR-17):** every factual claim in the reply must have a supporting passage in the retrieved articles.
- **Instruction integrity (FR-18):** blocks replies where the ticket text managed to redirect the system.
- **Tone and scope (implicit):** blocks commitments about refunds, timelines, or the product roadmap.
- **Confidence floor (FR-19):** overrides auto-respond when the confidence is missing or below the threshold.

A blocked reply routes to escalate. The reason it was blocked gets recorded in the decision log.

## Cross-cutting concerns

### Decision log — FR-20
SQLite database at `storage/decisions.db` (D-03). The schema is the Governance Framework's minimum record plus one added column (`run_id`) and one widened column (`action_taken`); both extensions are recorded in the Stage 5 revision log (`workbooks/Stage_5_PRD_Revision_Log.docx`, Table 3 rows 6 and 7).

- **`run_id`** — stamped on every row by the harness at the start of an invocation (`src/logging_store.py::set_run_id`). Reconciliation scopes by this. Without it, a fresh run against a persistent `decisions.db` (the grading condition) would count every dev and validation row already in the file as `extra_in_log` and fail A8 on arrival. Was the Bug 2 fix.
- **`action_taken` vocabulary** — carries either a routing outcome (`auto_respond | escalate | block` at `stage='routing'`) or a stage outcome (`classified | fallback` at `stage='classification'`; `retrieved | empty` at `stage='retrieval'`; `generated | blocked` at `stage='generation'` / `'validation'`). Distinguished by the `stage` column. Single-column, per-stage vocabulary. FR-20 asks for one row per autonomous decision, so classification rows have to describe what happened at classification — the pack's example values (which are routing verbs) don't cover that. Two alternatives considered and rejected: splitting into `stage_outcome` + `action_taken` (over-engineering), and folding classify into the routing row (loses per-stage auditability).

Every decision writes one row before the reply is sent. At the end of a harness run, a reconciliation query counts logged decisions scoped to the current `run_id` against tickets processed. Any gap fails acceptance criterion A8.

### Metrics — FR-22
Prometheus counters and histograms exposed at `:8001/metrics`. What we track: tickets by outcome, response latency, guardrail activations by type, and the distribution of confidence scores (so we can watch whether the classifier's confidence is calibrated — 90% should mean right 90% of the time).

### Guardrails
See section 6 above. Each guardrail is a `Guardrail` class with one method — `.check(response, context) → GuardrailResult{passed, reason, blocking}`. Every guardrail in this project blocks (per FR-16 through FR-19); none are warn-only.

## Layers

- **Application** — the FastAPI service (`src/api.py`) and the evaluation harness command-line tool (`evaluation/harness.py`).
- **Domain** — the six components (`src/ingest.py`, `classify.py`, `retrieve.py`, `route.py`, `generate.py`, `guardrails.py`).
- **Persistence** — the SQLite decision log, the Chroma vector store, and the Prometheus metrics endpoint.

## Dataset labels — what the scores are measured against

Audited 20 Sep, because the reported figures are agreement with `labels.*` and nothing had checked the labels themselves.

Self-consistent where it matters: across all 580 labelled tickets, none is `auto_respond` while unanswerable, none carries `must_not_auto_respond` and `auto_respond` together, and every answerable ticket lists expected articles. Sixteen answerable tickets are held with no policy flag; all sixteen are high-urgency performance or database incidents, which reads as a deliberate "investigate, do not send an article" call rather than an error.

Two defects are real, and both limit what any score here can mean:

- **The same ticket text is labelled both ways.** 50 groups of identical subject and body disagree on `expected_route` or `answerable_from_docs` (144 tickets). Two pairs sit inside the validation set itself — VAL-0012/VAL-0034 and VAL-0060/VAL-0061 — so no system can be right on both members. 21 of the 80 validation tickets have contested text, and 10 of the 32 wrong decisions on b21_openai_gemini_80_d12_20260920 land on them. `evaluation/results_table.py` computes this per run into the limitations section, so it travels with every table.
- **VAL-0004 looks mislabelled.** Marked unanswerable with no expected articles, while DOC-AUTH-002 lists "The authenticator code is rejected as invalid" under Symptoms — the ticket's exact complaint.

The labels are not corrected. Editing ground truth to suit our output would make every figure unfalsifiable, and the hidden evaluation set carries whatever labels it carries. The defects are reported instead.

**Nothing in `src/` is fitted to an individual ticket.** Every `VAL-`/`DEV-` reference in the pipeline and the prompts is a comment naming the evidence for a rule. The two rules that came closest to the labels were re-checked in this audit: the D-07 policy list matches `must_not_auto_respond` on all 580 tickets with no exceptions, and EV-DATA-10 shows the flag is a function of intent, so the rule restates the label in a field the router may read rather than approximating it; and the answer-relevance guardrail's motivating case (VAL-0002) is labelled identically in all five copies of its text, so it targets a real defect. The one decision shaped by the graded set is the 0.85 confidence threshold, swept on the same 80 validation tickets it is reported against (D-05b). It is also the largest single cause of held-back correct answers (11 on the latest run, 5 of them on contested tickets), so tuning it further on this set would be fitting label noise.

## What's still pending

- **D-04 (chunking):** provisionally fixed 800/120; the final ADR is backlog item B-08 this week, now that dense-retrieval measurement is in.
- **D-05b:** the confidence-threshold sweep result, backlog item B-16 (Friday).
- **PR-EVAL-JUDGE-01:** the three-dimensional RAG rubric prompt for the evaluation harness (backlog item B-17, Week 3).
- **D-03b's router rule has no consumer yet.** `ClassificationResult.decision_logged` is written by `classify.py` but nothing reads it until `route.py` exists. B-15's definition of done must include the forced-escalation check, or D-03b is only half-implemented and unlogged decisions can still be auto-responded to.

## Changelog

- 2026-08-30 — first version, six components + decision table.
- 2026-08-31 — updated the D-02 decision-table row to reflect the measured verdict from backlog item B-07 (91.0% top-3 hit rate, within 3 points of the TF-IDF baseline, better on non-fluent English). Added the "verified" date to the D-02 row. Added a note to the Classify component describing what the classifier deliberately doesn't see (fairness decision, see PR-CLASSIFY-01). Removed `docs/intent_classes.md` from the pending list (it's now written — see the file). Updated D-04's row to note that B-07 has cleared the way for the final ADR (backlog item B-08). Rewrote the document in plainer language throughout; all requirement IDs, ADR IDs, file paths, and numeric claims preserved.
- 2026-08-31 (later) — updated the Decision-log cross-cutting section to describe the two extensions to the Governance Framework's minimum-record schema: the added `run_id` column (per-run scoping, Bug 2 fix) and the widened `action_taken` vocabulary (per-stage values distinguished by the `stage` column, Option A in the code-review deliberation). Both extensions are recorded in Stage 5 revision log Table 3 rows 6 and 7.
