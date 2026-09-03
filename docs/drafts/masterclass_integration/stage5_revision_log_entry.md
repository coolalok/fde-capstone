# Stage 5 PRD Revision Log — 2026-09-03 entry

Paste as a new row in the revision log table.

---

**Date:** 2026-09-03 (Thu, Week 2 Day 4)
**Trigger:** Post-Masterclass 3 / Masterclass 4 review + audit of RAG_demo reference implementation.

**Changes to PRD:**
- Added FR-GUARD-01..04 under §Guardrails, evidenced against EV-RAGD-* and EV-MC4-SAFETY.
- §Non-functional requirements restructured under the five pillars of go-live readiness (Reliability & Resilience / Observability / Safety & Guardrails / Cost & Scalability / Governance & Compliance) per EV-MC4-PILLARS. Content unchanged; ordering re-mapped.
- §Success measures split into business (cost per resolved ticket, FCR, TTR, CSAT) / technical (hit@3, faithfulness, latency p95) / governance (auditability, refusal rate on blocked intents) tiers per EV-MC4-EVAL.

**Changes to ADRs:**
- Added D-03a (decision-log trace schema extension) extending D-03 with 14 additive columns per EV-MC4-TRACE.
- Added D-05a (confidence threshold dual role — floor + routing boundary) extending D-05 per EV-RAGD-CONF and EV-MC4-SAFETY.
- D-06 alternatives-considered section flagged for rewrite in the Masterclass 3 five-step decision-framework language (EV-MC3-DECISION). Owner: Alok. Target: pre-video record.

**Changes to Sprint Plan (Stage 4):**
- B-07 scope amended: added tiktoken chunker as second benchmark axis (EV-RAGD-CHUNK). *If B-07 already closed on Mon, this stays here as post-hoc validation to run in the B-08 window; noted.*
- B-11 DoD replaced: now targets FR-GUARD-01..04 with the RAG_demo interface shape. Test contract already written to `tests/test_guardrails.py`.
- B-15 scope amended: loads PR-GENERATE-01 v1.0.0 (created 2026-09-03, `prompts/build/PR-GENERATE-01.md`).
- B-16 spec upgraded from 1-D to 2-D threshold sweep (per D-05a) with LLM-as-judge faithfulness metric added (per EV-MC4-EVAL). Time-box impact ~+45 min, absorbed.
- B-19 scope amended: includes D-03a additive migration.

**Deferred to Stage 5 (not in-sprint):**
- Fallback path when OpenRouter is unavailable (Masterclass 4 "resilience" pillar) — new potential B-XX row, not added yet.
- LangSmith or equivalent hosted tracing (EV-RAGD-TRACE) — future work; current Prometheus + SQLite trace shape covers observability needs.
- Containerisation (Masterclass 4 §Foundations) — capstone deploys as single harness; noted as production-hardening future work.
- Cost anomaly detection ("cost as a leading indicator of malfunction", EV-MC3-COST) — noted; not added to sprint.

**Not adopted (with reason):**
- Multi-agent architecture (Masterclass 3 §Multi-Agent) — Q3 findings show retrieval essentially solved, no decomposable sub-goals. D-06 stays with Router + inline Self-RAG check.
- Planner-Executor pattern (Masterclass 3 §Orchestration) — same reason. D-06 unchanged.
- CrewAI or LangGraph framework layer (Masterclass 3 §Frameworks) — cost-nothing rule already satisfied by pack-native LangChain / LangGraph primitives; adopting a full framework increases lock-in without capability gain for this problem.

**Skill / process changes:**
- `capstone-conventions.md` extended with EV-MC3-* / EV-MC4-* / EV-RAGD-* evidence tag families (2026-09-03). `capstone-component-impl` now reads these tags on any FR / DoD it satisfies and consults the cited source before generating code.

**Evidence audit result:** traceability audit passes. All new FR-GUARD-* rows cite EV-*; all new ADRs cite EV-* and the FRs they constrain.
