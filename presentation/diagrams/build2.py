"""Diagrams 04 (layered architecture) and 05 (ticket-processing sequence).

Sources: docs/architecture.md (Layers, components), evaluation/harness.py::process_ticket
and main(), src/guardrails.py::run_all, src/route.py, at commit 9a1302d (report code a288388).
"""
from build import (t, rect, arrow, svg, num, W, H, FONT, MONO, INK, MUTED, LINE, PANEL, BAND,
                   SEND, SEND_BG, ESC, ESC_BG, BLOCK, BLOCK_BG, OUT)

LLM, LLM_BG = "#6D3FD6", "#F1ECFD"
VEC, VEC_BG = "#0F7F82", "#E6F4F4"
LOG, LOG_BG = "#475569", "#EEF1F5"
MET, MET_BG = "#A86412", "#FBF1E4"


def chip(x, y, label, col, bg):
    w = 12 + 10.5 * len(label)
    return (rect(x, y, w, 26, fill=bg, stroke=col, sw=1.5, r=13)
            + t(x + w / 2, y + 19, label, size=15, weight=700, fill=col, anchor="middle")), w


def chips(x, y, items):
    out, cx = [], x
    for label, col, bg in items:
        s, w = chip(cx, y, label, col, bg)
        out.append(s)
        cx += w + 8
    return "".join(out)


# ================================================================ 04 — three layers
def diagram_d():
    b = []
    b.append(t(56, 70, "CloudServe Draft: the three layers", size=44, weight=700))
    b.append(t(56, 112, "Keeping the layers apart meant swapping the model provider was a configuration change, "
                        "not a rewrite (D-01a).", size=23, fill=MUTED))

    def band(y, h, name, sub):
        b.append(rect(56, y, 1814, h, fill=BAND, stroke="none", r=16))
        name = name if isinstance(name, list) else [name]
        b.append(t(78, y + 40, name, size=24, weight=700, lh=1.15))
        b.append(t(78, y + 40 + 28 * len(name) + 6, sub, size=17, fill=MUTED, lh=1.25))

    # ---------------- Application
    ay, ah = 140, 196
    band(ay, ah, "Application", ["How work gets in", "and results", "get out"])
    # input
    b.append(rect(330, ay + 22, 250, 152, fill="#FFFFFF", stroke=LINE))
    b.append(t(348, ay + 56, "Ticket file (JSON)", size=21, weight=700))
    b.append(t(348, ay + 86, ["validation_tickets.json,", "demo tickets, or the", "hidden 120-ticket set"], size=17, lh=1.25))
    b.append(arrow(580, ay + 98, 626, ay + 98))
    b.append(rect(630, ay + 22, 420, 152, fill="#FFFFFF", stroke=INK, sw=2.5))
    b.append(t(648, ay + 56, "Evaluation harness (graded path)", size=21, weight=700))
    b.append(t(648, ay + 86, ["evaluation/harness.py --input --output", "One command, unattended (A9)",
                              "Writes the metrics report itself (A10)"], size=17, lh=1.25, family=FONT))
    b.append(arrow(1050, ay + 98, 1096, ay + 98))
    b.append(rect(1100, ay + 22, 350, 152, fill="#FFFFFF", stroke=LINE))
    b.append(t(1118, ay + 56, "Outputs per run", size=21, weight=700))
    b.append(t(1118, ay + 86, ["results.jsonl (row per ticket)", "metrics_report.json",
                               "results table, fairness table"], size=17, lh=1.25))
    b.append(rect(1480, ay + 22, 370, 152, fill="#FFFFFF", stroke=LINE, dash="7 5"))
    b.append(t(1498, ay + 56, "FastAPI service (demo)", size=21, weight=700))
    b.append(t(1498, ay + 86, ["src/api.py  POST /ticket", "GET /healthz  ·  GET /metrics", "Same six calls, same order"], size=17, lh=1.25))

    # ---------------- Domain
    dy, dh = 356, 300
    band(dy, dh, "Domain", ["The pipeline:", "six modules,", "always in this", "order"])
    mods = [
        ("ingest.py", ["Normalise 4 channels", "injection.py flags", "suspicious input"], [("log", LOG, LOG_BG)]),
        ("classify.py", ["Intent, urgency,", "confidence, top-3", "alternatives"], [("LLM", LLM, LLM_BG), ("log", LOG, LOG_BG)]),
        ("retrieve.py", ["Top passages,", "cosine floor 0.25", "or nothing"], [("vector", VEC, VEC_BG), ("log", LOG, LOG_BG)]),
        ("generate.py", ["Cited JSON draft,", "citation self-check,", "one retry"], [("LLM", LLM, LLM_BG), ("log", LOG, LOG_BG)]),
        ("guardrails.py", ["Six blocking checks,", "concurrent,", "max 4 (D-12)"], [("LLM", LLM, LLM_BG), ("log", LOG, LOG_BG)]),
        ("route.py", ["Eight ordered rules,", "no model call,", "EscalationBundle"], [("log", LOG, LOG_BG)]),
    ]
    mx0, mw, mg = 330, 240, 16
    for i, (name, lines, cs) in enumerate(mods):
        x = mx0 + i * (mw + mg)
        b.append(rect(x, dy + 22, mw, 186, fill="#FFFFFF", stroke=INK if name == "route.py" else LINE,
                      sw=2.5 if name == "route.py" else 2))
        b.append(num(x + 28, dy + 52, str(i + 1)))
        b.append(t(x + 54, dy + 59, name, size=20, weight=700, family=MONO))
        b.append(t(x + 16, dy + 98, lines, size=18, lh=1.25))
        b.append(chips(x + 16, dy + 170, cs))
        if i < 5:
            b.append(arrow(x + mw, dy + 115, x + mw + mg - 3, dy + 115, sw=2.5))
    b.append(rect(330, dy + 222, 1520, 62, fill="#FFFFFF", stroke=LINE, r=12))
    b.append(t(350, dy + 250, "Shared:", size=18, weight=700))
    b.append(t(440, dy + 250, "prompts/build/*.md, versioned (PR-CLASSIFY-01, PR-GENERATE-01, PR-GUARDRAIL-*) via prompt_loader.py",
               size=17))
    b.append(t(440, dy + 274, "schema.py typed objects: Ticket, ClassificationResult, Passage, GeneratedResponse, "
                              "GuardrailResult, EscalationBundle, Route", size=17))

    # ---------------- Infrastructure / persistence
    iy, ih = 676, 300
    band(iy, ih, ["Infrastructure", "and persistence"], ["Swappable", "without touching", "the domain code"])
    cards = [
        ("LLM", LLM, LLM_BG, "Model access", ["model_call.py: 180 s deadline", "(D-13)", "model_cache.py (D-08)",
                                              "usage.py: tokens and cost"]),
        ("vector", VEC, VEC_BG, "Vector store", ["Chroma, storage/chroma", "all-MiniLM-L6-v2", "29 articles, 800/120",
                                                 "built by index_docs.py"]),
        ("log", LOG, LOG_BG, "Decision log", ["SQLite storage/decisions.db", "One row per stage, run_id",
                                              "prompt_version, requirement_ids", "reconciled every run (A8)"]),
        ("metrics", MET, MET_BG, "Metrics", ["Prometheus client (metrics.py)", ":8001 harness, :8000 API",
                                             "ops/prometheus.yml", "No Grafana dashboard built"]),
        ("config", INK, PANEL, "Configuration", ["config.py + .env", "CONFIDENCE_THRESHOLD 0.85", "KILL_SWITCH (D-15)",
                                                 "GUARDRAIL_MAX_WORKERS"]),
    ]
    cx0, cw, cg = 330, 290, 17
    for i, (tag, col, bg, title, lines) in enumerate(cards):
        x = cx0 + i * (cw + cg)
        b.append(rect(x, iy + 22, cw, 196, fill="#FFFFFF", stroke=col, sw=2.5))
        s, _ = chip(x + 16, iy + 38, tag, col, bg)
        b.append(s)
        b.append(t(x + 16, iy + 96, title, size=21, weight=700, fill=col))
        b.append(t(x + 16, iy + 126, lines, size=17, lh=1.28))
    # providers under model access
    b.append(arrow(cx0 + cw / 2, iy + 218, cx0 + cw / 2, iy + 238, color=LLM, sw=2.5))
    b.append(rect(cx0, iy + 240, 1520, 48, fill=LLM_BG, stroke=LLM, sw=1.5, r=10))
    b.append(t(cx0 + 18, iy + 271, "Model providers:", size=18, weight=700, fill=LLM))
    b.append(t(cx0 + 176, iy + 271, "graded run gpt-4o-mini (drafts) + gpt-4o (guardrails)   ·   free tier: Ollama "
                                    "llama3.1-8b + qwen2.5-7b, 50 dev tickets on 27 Sep at $0   ·   OpenRouter (D-01)", size=18))

    b.append(t(56, 1046, "Source: docs/architecture.md (Layers) and src/. Chips show which infrastructure each module uses.",
               size=16, fill=MUTED))
    return svg("".join(b))


# ================================================================ 05 — sequence of one ticket
def diagram_e():
    b = []
    b.append(t(56, 64, "What happens to one ticket, in order", size=42, weight=700))
    b.append(t(56, 102, "evaluation/harness.py::process_ticket. The same sequence runs behind POST /ticket.",
               size=22, fill=MUTED))

    lanes = [("Harness", INK), ("Ingest", INK), ("Classify", INK), ("Retrieve", INK), ("Generate", INK),
             ("Guardrails", INK), ("Route", INK), ("Model provider", LLM), ("Decision log", LOG)]
    lx = {name: 150 + i * 205 for i, (name, _) in enumerate(lanes)}
    top, bottom = 124, 1016
    for name, col in lanes:
        x = lx[name]
        bg = LLM_BG if col == LLM else (LOG_BG if col == LOG else "#FFFFFF")
        b.append(rect(x - 92, top, 184, 44, fill=bg, stroke=col, sw=2, r=10))
        b.append(t(x, top + 29, name, size=19, weight=700, fill=col, anchor="middle"))
        b.append(f'<line x1="{x}" y1="{top + 44}" x2="{x}" y2="{bottom}" stroke="{LINE}" stroke-width="2" stroke-dasharray="6 6"/>')

    y = [190]
    RH = 32.5

    def call(a, z, label, col=INK, dashed=False, above=True, size=16):
        ya = y[0]
        x1, x2 = lx[a], lx[z]
        pad = 6 if x2 > x1 else -6
        b.append(arrow(x1, ya, x2 - pad, ya, color=col, sw=2.2, dash="7 5" if dashed else None))
        mid = (x1 + x2) / 2
        b.append(t(mid, ya - 7, label, size=size, fill=col if col != MUTED else INK, anchor="middle",
                   style="italic" if dashed else ""))

    def pair(stage, ret_label, log_label="log row"):
        """Stage returns to harness (left) and writes a log row (right) on one line."""
        ya = y[0]
        call(stage, "Harness", ret_label, col=MUTED, dashed=True)
        x1, x2 = lx[stage], lx["Decision log"]
        b.append(arrow(x1, ya, x2 - 6, ya, color=LOG, sw=2))
        b.append(t(x2 - 12, ya - 7, log_label, size=15, fill=LOG, anchor="end"))

    def note(lane, text, w=190, col=MUTED, dx=12):
        ya = y[0]
        x = lx[lane] + dx
        b.append(rect(x, ya - 20, w, 28, fill="#FFFFFF", stroke=LINE, sw=1.2, r=6))
        b.append(t(x + 8, ya - 1, text, size=14.5, fill=col))

    def nxt(n=1):
        y[0] += RH * n

    # setup (once per run)
    call("Harness", "Decision log", "set_run_id(): one run_id for this whole invocation", col=LOG)
    nxt(1.1)
    # loop frame
    loop_top = y[0] - 14
    nxt(1.15)

    call("Harness", "Ingest", "normalise(raw ticket)")
    nxt()
    call("Ingest", "Harness", "Ticket + warnings + injection flags", col=MUTED, dashed=True)
    nxt()
    call("Harness", "Classify", "classify(ticket)")
    nxt()
    call("Classify", "Model provider", "PR-CLASSIFY-01  →  intent, urgency, confidence", col=LLM)
    nxt()
    pair("Classify", "ClassificationResult")
    nxt()
    call("Harness", "Retrieve", "retrieve(subject + body)")
    note("Retrieve", "MiniLM + Chroma, floor 0.25", w=196, dx=10)
    nxt()
    pair("Retrieve", "passages (can be empty)")
    nxt()
    call("Harness", "Generate", "generate(ticket, passages)")
    nxt()
    call("Generate", "Model provider", "PR-GENERATE-01  →  answer, citations, unknown", col=LLM)
    nxt()
    note("Generate", "citation self-check, 1 retry", w=190, dx=10)
    nxt(0.9)
    pair("Generate", "draft")
    nxt()
    call("Harness", "Guardrails", "run_all(draft, passages)")
    nxt()
    # par frame
    nxt(0.35)
    par_top = y[0] - 40
    call("Guardrails", "Model provider", "draft review: PII + tone/scope + relevance", col=LLM, size=15)
    nxt()
    call("Guardrails", "Model provider", "grounding: each claim vs the passages", col=LLM, size=15)
    nxt(0.75)
    b.append(t(lx["Guardrails"] + 12, y[0] + 4, "+ regex PII, instruction integrity, confidence floor (no model call)",
               size=14.5, fill=MUTED, anchor="start"))
    par_bot = y[0] + 12
    b.append(rect(lx["Guardrails"] - 20, par_top, lx["Model provider"] - lx["Guardrails"] + 40, par_bot - par_top,
                  fill="none", stroke=LLM, sw=1.5, r=6, dash="5 4"))
    pr = lx["Model provider"] + 20
    b.append(rect(pr - 140, par_top, 140, 22, fill=LLM_BG, stroke=LLM, sw=1.5, r=4))
    b.append(t(pr - 132, par_top + 16, "par, max 4 (D-12)", size=13.5, weight=700, fill=LLM))
    nxt(1.15)
    pair("Guardrails", "6 verdicts, in guardrail order")
    nxt()
    call("Harness", "Route", "route(ticket, classification, passages, draft, verdicts)")
    note("Route", "rules 0-6, first match wins", w=190, dx=10)
    nxt()
    pair("Route", "decision + reason (+ EscalationBundle)", log_label="routing row")
    nxt()
    # outcomes (alt) on the harness lane
    ax = lx["Harness"] - 90
    b.append(rect(ax, y[0] - 20, 1060, 58, fill="#FFFFFF", stroke=LINE, sw=1.5, r=8))
    b.append(t(ax + 12, y[0] + 2, "alt", size=14, weight=700, fill=MUTED))
    items = [("auto_respond", SEND, "reply sent, citation markers stripped"),
             ("escalate", ESC, "bundle to a person"),
             ("block", BLOCK, "draft withheld, flagged draft_blocked")]
    xx = ax + 50
    for lab, col, desc in items:
        b.append(t(xx, y[0] + 2, lab, size=16, weight=700, fill=col))
        b.append(t(xx, y[0] + 24, desc, size=14.5, fill=INK))
        xx += 330
    nxt(1.9)
    b.append(t(lx["Harness"] - 90, y[0] - 4, "row appended to results.jsonl · tickets_processed_total and "
                                           "response_seconds updated", size=15, fill=MUTED))
    loop_bot = y[0] + 8
    b.append(rect(58, loop_top, 1804, loop_bot - loop_top, fill="none", stroke=INK, sw=1.8, r=8))
    b.append(rect(58, loop_top, 508, 24, fill=INK, stroke=INK, sw=1, r=4))
    b.append(t(68, loop_top + 18, "loop: each ticket in --input  (a crash escalates it as degraded, FR-23)",
               size=14.5, weight=700, fill="#FFFFFF"))
    nxt(1.1)
    call("Harness", "Decision log", "reconcile(run_id): logged decisions = tickets processed  (A8, 80/80)", col=LOG)
    nxt()
    b.append(t(lx["Harness"] - 90, y[0] + 2, "then metrics_report.json is written with no manual step (A10)",
               size=16, weight=700, fill=INK))
    return svg("".join(b)), y[0]


if __name__ == "__main__":
    (OUT / "04_architecture_layers.svg").write_text(diagram_d(), encoding="utf-8")
    s, ylast = diagram_e()
    (OUT / "05_ticket_sequence.svg").write_text(s, encoding="utf-8")
    print("last y", ylast)
