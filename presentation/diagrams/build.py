"""Build the three architecture diagrams for the capstone video (1920x1080 SVG + PNG).

Source of truth: docs/architecture.md and src/route.py in fde-capstone.
Counts: evaluation/results/final_val_paid_80_20260927 (80 validation tickets, 27 Sep 2026).
"""
from pathlib import Path
from html import escape

W, H = 1920, 1080
FONT = "Calibri, Carlito, 'Segoe UI', Arial, sans-serif"
MONO = "Consolas, 'DejaVu Sans Mono', monospace"

INK = "#1F2430"
MUTED = "#5B6272"
LINE = "#C4CAD6"
PANEL = "#F4F6FA"
BAND = "#EDF0F5"
SEND = "#1E8E5A"
SEND_BG = "#E8F5EE"
ESC = "#2F5BEA"
ESC_BG = "#EAF0FE"
BLOCK = "#C0392B"
BLOCK_BG = "#FBECEA"
STAGE = "#1F2430"

OUT = Path(__file__).parent


def t(x, y, lines, size=22, weight=400, fill=INK, anchor="start", lh=1.22, family=FONT, style=""):
    if isinstance(lines, str):
        lines = [lines]
    spans = []
    for i, ln in enumerate(lines):
        dy = 0 if i == 0 else size * lh
        spans.append(f'<tspan x="{x}" dy="{dy:.1f}">{escape(ln)}</tspan>')
    st = f' font-style="{style}"' if style else ""
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}>{"".join(spans)}</text>')


def rect(x, y, w, h, fill=PANEL, stroke=LINE, sw=2, r=14, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'


def arrow(x1, y1, x2, y2, color=MUTED, sw=3, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d} '
            f'marker-end="url(#ah-{color.strip("#")})"/>')


def path_arrow(d, color=MUTED, sw=3):
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" marker-end="url(#ah-{color.strip("#")})"/>'


def markers():
    out = []
    for c in (MUTED, SEND, ESC, BLOCK, INK, "#6D3FD6", "#475569", "#0F7F82", "#A86412"):
        k = c.strip("#")
        out.append(f'<marker id="ah-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                   f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>')
    return "<defs>" + "".join(out) + "</defs>"


def svg(body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'{markers()}<rect width="{W}" height="{H}" fill="#FFFFFF"/>{body}</svg>')


def num(cx, cy, label, fill=STAGE):
    return (f'<circle cx="{cx}" cy="{cy}" r="17" fill="{fill}"/>'
            + t(cx, cy + 7, label, size=19, weight=700, fill="#FFFFFF", anchor="middle"))


# ---------------------------------------------------------------- shared layout
BX0, BW, GAP, BY, BH = 262, 192, 20, 196, 300
def bx(i):
    return BX0 + i * (BW + GAP)


def channels_card(y0=196, h=300):
    b = [rect(56, y0, 176, h, fill="#FFFFFF", stroke=LINE)]
    b.append(t(74, y0 + 40, "Tickets in", size=24, weight=700))
    for i, ch in enumerate(["Email", "Live chat", "Docs comment", "Forum"]):
        yy = y0 + 70 + i * 54
        b.append(rect(72, yy, 144, 40, fill=PANEL, stroke=LINE, sw=1.5, r=20))
        b.append(t(144, yy + 27, ch, size=19, anchor="middle"))
    b.append(arrow(232, y0 + h / 2, BX0 - 4, y0 + h / 2))
    return "".join(b)


def outcomes(cards, x=1566, w=304, y0=196, h=150, gap=18, route_mid=None):
    """cards: list of (title, colour, bg, lines, count)."""
    b = []
    rx = bx(5) + BW
    sy = route_mid if route_mid else BY + BH / 2
    spine = rx + 24
    mids = [y0 + i * (h + gap) + h / 2 for i in range(len(cards))]
    b.append(f'<line x1="{rx}" y1="{sy}" x2="{spine}" y2="{sy}" stroke="{MUTED}" stroke-width="3"/>')
    b.append(f'<line x1="{spine}" y1="{mids[0]}" x2="{spine}" y2="{mids[-1]}" stroke="{MUTED}" stroke-width="3"/>')
    for i, (title, col, bg, lines, count) in enumerate(cards):
        y = y0 + i * (h + gap)
        b.append(rect(x, y, w, h, fill=bg, stroke=col, sw=2.5))
        b.append(t(x + 18, y + 36, title, size=23, weight=700, fill=col))
        b.append(t(x + 18, y + 68, lines, size=19, fill=INK, lh=1.2))
        if count:
            b.append(t(x + w - 16, y + 36, count, size=19, weight=700, fill=col, anchor="end"))
        b.append(arrow(spine, mids[i], x - 5, mids[i], color=col, sw=3))
    return "".join(b)


# ================================================================ Diagram A — plain language (slide S6)
def diagram_a():
    b = []
    b.append(t(56, 78, "How a ticket moves through CloudServe Draft", size=46, weight=700))
    b.append(t(56, 124, "Six steps, always in this order. The decision to send, escalate or block is made last, "
                        "from what the first five found.", size=24, fill=MUTED))
    b.append(channels_card())

    stages = [
        ("1", "INGEST", ["Put every channel", "into one shape", "and flag suspicious", "instructions"]),
        ("2", "CLASSIFY", ["What is it about,", "how urgent, and", "how sure are we?"]),
        ("3", "SEARCH", ["Find the passages", "in the 29 help", "articles that", "answer it"]),
        ("4", "DRAFT", ["Write a reply that", "cites those", "articles, or say", "\"I don't know\""]),
        ("5", "CHECK", ["Six safety checks", "on the draft.", "Any one of them", "can stop it"]),
        ("6", "DECIDE", ["Send, escalate", "or block.", "Same ticket,", "same decision,", "every time"]),
    ]
    for i, (n, name, lines) in enumerate(stages):
        x = bx(i)
        hl = name in ("CHECK", "DECIDE")
        b.append(rect(x, BY, BW, BH, fill="#FFFFFF" if not hl else PANEL, stroke=INK if hl else LINE, sw=2.5 if hl else 2))
        b.append(num(x + 34, BY + 38, n))
        b.append(t(x + 60, BY + 46, name, size=24, weight=700))
        b.append(t(x + 18, BY + 100, lines, size=21, lh=1.28))
        if i < 5:
            b.append(arrow(x + BW, BY + BH / 2, x + BW + GAP - 4, BY + BH / 2))

    # six checks panel under CHECK
    cx = bx(4) + BW / 2
    px, py, pw, ph = 846, 540, 640, 176
    b.append(f'<line x1="{cx}" y1="{BY + BH}" x2="{cx}" y2="{py}" stroke="{INK}" stroke-width="2.5"/>')
    b.append(rect(px, py, pw, ph, fill=PANEL, stroke=INK, sw=2))
    b.append(t(px + 22, py + 36, "The six checks (every one blocks, none just warns)", size=22, weight=700))
    checks = ["No private data", "Every claim backed by an article", "Not redirected by the ticket",
              "No refund or timeline promises", "Answers the question asked", "Classifier sure enough"]
    for i, c in enumerate(checks):
        col, row = i % 2, i // 2
        xx = px + 22 + col * 312
        yy = py + 76 + row * 36
        b.append(f'<circle cx="{xx + 7}" cy="{yy - 7}" r="5" fill="{INK}"/>')
        b.append(t(xx + 22, yy, c, size=20))

    b.append(outcomes([
        ("SEND", SEND, SEND_BG, ["A cited reply goes to", "the customer"], "61 of 80"),
        ("ESCALATE", ESC, ESC_BG, ["A person gets the ticket with", "the articles found, the draft", "and why the system was unsure"], "14 of 80"),
        ("BLOCK", BLOCK, BLOCK_BG, ["A check failed. The draft is", "withheld and a person", "reviews it; it is never sent as-is"], "5 of 80"),
    ]))

    # around every step
    y0 = 770
    b.append(rect(56, y0, 1814, 200, fill=BAND, stroke="none", r=16))
    b.append(t(80, y0 + 40, "Around every step", size=24, weight=700))
    cards = [
        ("Decision log", ["Every step writes a row: what it", "decided, why, and which prompt.", "80 of 80 reconciled on the run."], False),
        ("Live metrics", ["Volume, speed, blocks and", "confidence, readable while", "the system runs."], False),
        ("Kill switch", ["One setting sends every", "ticket to a person. No", "redeploy needed."], False),
        ("Feedback loop", ["Reviewers' verdicts feed back", "into the next version.", "Designed, not yet built."], True),
    ]
    cw, cg = 424, 20
    for i, (title, lines, dashed) in enumerate(cards):
        x = 80 + i * (cw + cg)
        b.append(rect(x, y0 + 58, cw, 124, fill="#FFFFFF", stroke=MUTED if dashed else LINE, sw=2,
                      dash="8 6" if dashed else None))
        b.append(t(x + 18, y0 + 92, title, size=22, weight=700, fill=MUTED if dashed else INK))
        b.append(t(x + 18, y0 + 122, lines, size=19, fill=MUTED if dashed else INK, lh=1.2))

    b.append(t(56, 1040, "Source: docs/architecture.md. Counts are from the graded run of 27 Sep 2026 "
                         "(final_val_paid_80_20260927, 80 validation tickets).", size=17, fill=MUTED))
    return svg("".join(b))


# ================================================================ Diagram B — the decision ladder (slide S7)
def diagram_b():
    b = []
    b.append(t(56, 78, "How the system decides: the first rule that matches wins", size=46, weight=700))
    b.append(t(56, 124, "route() runs last and makes no model call of its own, so the same ticket always gets the "
                        "same decision and the same reason (A5).", size=24, fill=MUTED))
    rules = [
        ("0", "Is the kill switch on?", "kill_switch_active", "D-15", "esc", "0"),
        ("1", "Did a decision fail to reach the log?", "decision_not_logged", "D-03b", "esc", "0"),
        ("2", "Did any of the five checks that read the draft fail?", "guardrail_blocked", "D-14", "blk", "5"),
        ("2b", "Was a prompt-injection attempt flagged on the way in?", "injection_suspected", "D-16", "esc", "0"),
        ("3", "Is it an intent that never auto-answers? (compliance, security incident, feature request, unclear, unknown)",
         "never_auto_respond_intent", "D-07", "esc", "14"),
        ("4", "Did search find nothing above the 0.25 relevance floor?", "empty_retrieval", "D-02a", "esc", "0"),
        ("5", "Did the drafter say the articles do not answer it?", "generator_unknown", "FR-14", "esc", "0"),
        ("6", "Is the classifier's confidence below 0.85?", "low_confidence", "D-05b", "esc", "0"),
        ("", "None of the above: confident and grounded", "confident_and_grounded", "", "send", "61"),
    ]
    x0, y0, rh, rg = 56, 164, 84, 10
    colx = {"q": 150, "out": 1140, "trig": 1350, "adr": 1655, "n": 1850}
    # header
    b.append(t(colx["q"], y0 + 6, "Question the router asks", size=19, weight=700, fill=MUTED))
    b.append(t(colx["out"], y0 + 6, "Outcome", size=19, weight=700, fill=MUTED))
    b.append(t(colx["trig"], y0 + 6, "Reason logged", size=19, weight=700, fill=MUTED))
    b.append(t(colx["adr"], y0 + 6, "Decision", size=19, weight=700, fill=MUTED))
    b.append(t(colx["n"], y0 + 6, "Graded run", size=19, weight=700, fill=MUTED, anchor="end"))
    y = y0 + 22
    styles = {"esc": ("ESCALATE", ESC, ESC_BG), "blk": ("BLOCK", BLOCK, BLOCK_BG), "send": ("SEND", SEND, SEND_BG)}
    for n, q, trig, adr, kind, cnt in rules:
        label, col, bg = styles[kind]
        last = kind == "send"
        b.append(rect(x0, y, 1814, rh, fill=SEND_BG if last else "#FFFFFF", stroke=SEND if last else LINE,
                      sw=2.5 if last else 1.5, r=12))
        if n:
            b.append(num(x0 + 44, y + rh / 2, n))
        else:
            b.append(f'<circle cx="{x0 + 44}" cy="{y + rh / 2}" r="17" fill="{SEND}"/>'
                     + t(x0 + 44, y + rh / 2 + 7, "✓", size=20, weight=700, fill="#FFFFFF", anchor="middle"))
        if len(q) > 70:
            head, tail = q.split(" (", 1)
            b.append(t(colx["q"], y + 36, head, size=23, weight=600 if not last else 700))
            b.append(t(colx["q"], y + 64, "(" + tail, size=19, fill=MUTED))
        else:
            b.append(t(colx["q"], y + rh / 2 + 8, q, size=23, weight=600 if not last else 700))
        # outcome pill
        b.append(rect(colx["out"], y + 21, 170, 42, fill=bg, stroke=col, sw=2, r=21))
        b.append(t(colx["out"] + 85, y + 49, label, size=19, weight=700, fill=col, anchor="middle"))
        b.append(t(colx["trig"], y + rh / 2 + 7, trig, size=18, family=MONO, fill=INK))
        b.append(t(colx["adr"], y + rh / 2 + 7, adr, size=19, fill=MUTED))
        b.append(t(colx["n"], y + rh / 2 + 9, cnt, size=26, weight=700, fill=col if cnt != "0" else MUTED, anchor="end"))
        if not last:
            b.append(arrow(x0 + 44, y + rh / 2 + 17, x0 + 44, y + rh + rg + rh / 2 - 19, color=LINE, sw=2.5))
        y += rh + rg
    b.append(t(56, 1050, "Source: src/route.py and docs/architecture.md §6. Counts: final_val_paid_80_20260927, 80 validation tickets "
                         "(61 sent, 14 escalated, 5 blocked).", size=17, fill=MUTED))
    return svg("".join(b))


# ================================================================ Diagram C — technical view (backup / Q&A)
def diagram_c():
    b = []
    b.append(t(56, 70, "CloudServe Draft: technical architecture", size=42, weight=700))
    b.append(t(56, 110, "Router agent. Six components in sequence; route() reads the results of the first five. "
                        "Every box names its requirements (FR) and design decisions (D).", size=22, fill=MUTED))

    # entry points strip
    b.append(rect(300, 132, 1196, 46, fill=BAND, stroke="none", r=10))
    b.append(t(318, 163, "Entry points, same pipeline:", size=19, weight=700))
    b.append(t(578, 163, "evaluation/harness.py --input --output  (graded, writes metrics_report.json)"
                         "    ·    src/api.py  POST /ticket  (demo)", size=19, family=FONT))

    b.append(channels_card(y0=196, h=300))
    stages = [
        ("1", "INGEST", ["FR-01 to FR-03", "One Ticket object", "Empty fields become", "warnings, not errors", "Injection flags (D-16)"]),
        ("2", "CLASSIFY", ["FR-04, FR-05", "22 intents + urgency", "Confidence 0 to 1", "Top-3 alternatives", "Blind to tier, region,", "fluency, name"]),
        ("3", "RETRIEVE", ["FR-06 to FR-08", "all-MiniLM-L6-v2 (D-02)", "Chroma, cosine space", "Floor 0.25 (D-02a)", "800/120 + title (D-04)", "Subject + body (D-09)"]),
        ("4", "GENERATE", ["FR-13 to FR-15", "JSON: answer,", "citations, unknown", "Ticket in delimiters", "Citation self-check,", "1 retry (D-06a)"]),
        ("5", "VALIDATE", ["FR-15 to FR-19", "Six guardrails,", "all blocking", "Concurrent, max 4", "workers (D-12)"]),
        ("6", "ROUTE", ["FR-09 to FR-12", "8 ordered rules,", "first match wins", "Pure function, no", "model call (A5)", "EscalationBundle"]),
    ]
    for i, (n, name, lines) in enumerate(stages):
        x = bx(i)
        b.append(rect(x, BY, BW, BH, fill="#FFFFFF", stroke=INK if name == "ROUTE" else LINE, sw=2.5 if name == "ROUTE" else 2))
        b.append(num(x + 32, BY + 36, n))
        b.append(t(x + 56, BY + 44, name, size=22, weight=700))
        b.append(t(x + 16, BY + 90, lines[0], size=18, weight=700, fill=MUTED))
        b.append(t(x + 16, BY + 122, lines[1:], size=18, lh=1.3))
        if i < 5:
            b.append(arrow(x + BW, BY + BH / 2, x + BW + GAP - 4, BY + BH / 2))

    # guardrail panel
    cx = bx(4) + BW / 2
    px, py, pw, ph = 846, 526, 640, 236
    b.append(f'<line x1="{cx}" y1="{BY + BH}" x2="{cx}" y2="{py}" stroke="{INK}" stroke-width="2.5"/>')
    b.append(rect(px, py, pw, ph, fill=PANEL, stroke=INK, sw=2))
    b.append(t(px + 20, py + 34, "Guardrails: .check() returns GuardrailResult{passed, reason, blocking}", size=19, weight=700))
    g = [("PII", "FR-16, D-11 value-shaped"), ("Grounding", "FR-17"), ("Instruction integrity", "FR-18"),
         ("Tone and scope", "no commitments"), ("Answer relevance", "RAG triad"), ("Confidence floor", "FR-19, escalates (D-14)")]
    for i, (name, note) in enumerate(g):
        col, row = i % 2, i // 2
        xx = px + 20 + col * 310
        yy = py + 72 + row * 48
        b.append(t(xx, yy, name, size=19, weight=700))
        b.append(t(xx, yy + 21, note, size=16, fill=MUTED))
    b.append(t(px + 20, py + ph - 16, "Five read the draft and give BLOCK. The floor reads classifier confidence and gives ESCALATE.",
               size=16, fill=MUTED, style="italic"))

    b.append(outcomes([
        ("auto_respond", SEND, SEND_BG, ["confident_and_grounded", "Cited reply sent"], "61 / 80"),
        ("escalate", ESC, ESC_BG, ["Rules 0, 1, 2b, 3, 4, 5, 6", "EscalationBundle: passages,", "top-3 intents, draft, reason"], "14 / 80"),
        ("block", BLOCK, BLOCK_BG, ["Rule 2: a draft check failed", "Draft travels flagged", "draft_blocked, never sendable"], "5 / 80"),
    ]))

    # cross-cutting / persistence
    y0 = 782
    b.append(rect(56, y0, 1814, 214, fill=BAND, stroke="none", r=16))
    b.append(t(80, y0 + 36, "Cross-cutting and persistence", size=22, weight=700))
    cards = [
        ("Decision log", ["SQLite storage/decisions.db", "One row per stage, run_id", "prompt_version, requirement_ids", "D-03, D-03a, D-03b · FR-20/21"], False),
        ("Metrics", ["Prometheus /metrics", ":8001 harness, :8000 API", "ops/prometheus.yml", "FR-22 · no Grafana built"], False),
        ("Model calls", ["Response cache (D-08)", "180 s caller deadline (D-13)", "Tokens and cost logged", "Graded: gpt-4o-mini + gpt-4o"], False),
        ("Kill switch", ["KILL_SWITCH=1", "Router rule 0, every call", "No redeploy (D-15)", "Tested in test_route.py"], False),
        ("Feedback loop", ["Verdict table designed", "in architecture.md", "No code, no FR yet", "Next step in report §10"], True),
    ]
    cw, cg = 339, 15
    for i, (title, lines, dashed) in enumerate(cards):
        x = 80 + i * (cw + cg)
        b.append(rect(x, y0 + 52, cw, 146, fill="#FFFFFF", stroke=MUTED if dashed else LINE, sw=2, dash="8 6" if dashed else None))
        b.append(t(x + 16, y0 + 84, title, size=21, weight=700, fill=MUTED if dashed else INK))
        b.append(t(x + 16, y0 + 112, lines, size=17, fill=MUTED if dashed else INK, lh=1.25))
    b.append(t(56, 1046, "Source: docs/architecture.md, src/route.py, docs/adr/. Free-tier corroboration: "
                         "llama3.1-8b + qwen2.5-7b via Ollama, 50/50 dev tickets on 27 Sep, $0. Counts: final_val_paid_80_20260927.", size=16, fill=MUTED))
    return svg("".join(b))


if __name__ == "__main__":
    for name, fn in [("01_architecture_plain", diagram_a), ("02_decision_ladder", diagram_b),
                     ("03_architecture_technical", diagram_c)]:
        (OUT / f"{name}.svg").write_text(fn(), encoding="utf-8")
        print("wrote", name)
