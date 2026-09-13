"""Replay the 13 Sep gate run's stored drafts through the NEW guardrail only.
No regeneration: same drafts, same tickets, so the comparison is clean."""
import json
from src.logging_config import configure_logging
from src.logging_store import new_run_id, set_run_id
from src.ingest import normalise_any
from src.guardrails import AnswerRelevanceGuardrail
from src.schema import GeneratedResponse, GuardrailContext, ClassificationResult

configure_logging(); set_run_id(new_run_id())
val = {t["ticket_id"]: t for t in json.load(open("data/validation_tickets.json"))}
rows = [json.loads(l) for l in open("evaluation/results/b21_gate_20260913/results.jsonl")]
clean = [r for r in rows if not r.get("classifier_error")
         and not r.get("generator_error") and r.get("answer")]

g = AnswerRelevanceGuardrail()
out = []
for r in clean:
    t = normalise_any(val[r["ticket_id"]])
    resp = GeneratedResponse(answer=r["answer"], citations=r["citations"],
                             confidence=r["confidence"], unknown=r["unknown"])
    ctx = GuardrailContext(ticket=t, passages=[],
                           classification=ClassificationResult(
                               intent=r["intent"], urgency=r.get("urgency","medium"),
                               confidence=r["confidence"]))
    v = g.check(resp, ctx)
    out.append({"ticket_id": r["ticket_id"],
                "answerable": val[r["ticket_id"]]["labels"].get("answerable_from_docs"),
                "old_decision": r["decision"], "relevance_passed": v.passed,
                "fail_safe": v.fail_safe, "reason": v.reason[:150],
                "question_asked": (v.details or {}).get("question_asked","")})
    print(".", end="", flush=True)
print()
json.dump(out, open("/private/tmp/claude-503/-Users-alokkulkarni-Documents-Claude-Projects-fde-capstone/8b02a7c0-b4e6-4f89-9ced-ee1f9d29c481/scratchpad/relevance_ab.json","w"), indent=1)
