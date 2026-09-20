"""B-18 human scoring sheet: build it, and import the scores it produces.

  build   writes evaluation/calibration/scoring_sheet.html, a single self-contained page
          (no network, no external scripts). Open it in a browser, score each item on
          three 1-5 dimensions, then press "Download scores".
  import  merges the downloaded file into tests/fixtures/judge_calibration.json.

The sheet shows only what the judge sees — channel, subject, body, passages, reply —
plus the rubric, copied from the "## Scoring rubric" section of PR-EVAL-JUDGE-01 at
build time so the human and the judge read identical wording. Labels, routing outcomes,
guardrail verdicts and the judge's own scores are never embedded: scoring is blind.

Scores autosave in the browser (localStorage, keyed to this fixture), so the sheet can
be closed and reopened. The downloaded file carries a fixture_id; import refuses a file
made from a different fixture.

Usage:
    python -m evaluation.calibration_sheet build
    python -m evaluation.calibration_sheet import --scores ~/Downloads/judge_calibration_scores.json
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
FIXTURE = _ROOT / "tests" / "fixtures" / "judge_calibration.json"
SHEET = _ROOT / "evaluation" / "calibration" / "scoring_sheet.html"
PROMPT_FILE = _ROOT / "prompts" / "evaluation" / "PR-EVAL-JUDGE-01.md"
# The page itself lives beside the output: it is HTML, CSS and JavaScript, not Python.
TEMPLATE_FILE = _ROOT / "evaluation" / "calibration" / "sheet_template.html"
DIMENSIONS = ("context_relevance", "groundedness", "answer_relevance")


def fixture_id(fixture: dict) -> str:
    h = hashlib.sha256()
    for item in fixture["items"]:
        h.update(item["item_id"].encode())
        h.update(item["reply"].encode())
    return h.hexdigest()[:12]


def rubric_markdown(prompt_text: str) -> str:
    m = re.search(r"^## Scoring rubric\s*\n(.*?)^## ", prompt_text, re.S | re.M)
    if not m:
        raise ValueError("PR-EVAL-JUDGE-01 has no '## Scoring rubric' section")
    return m.group(1).strip()


def rubric_html(markdown: str) -> str:
    out, in_list = [], False
    for line in markdown.splitlines():
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)


def blind_items(fixture: dict) -> list[dict]:
    """Only the fields the judge sees. Nothing from `meta` leaves the fixture."""
    return [{"item_id": i["item_id"], "ticket": i["ticket"], "passages": i["passages"],
             "reply": i["reply"]} for i in fixture["items"]]


def embed_json(data) -> str:
    # "</" would let a reply containing "</script>" end the data block early.
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def build_html(fixture: dict, prompt_text: str) -> str:
    payload = {"fixture_id": fixture_id(fixture), "prompt_id": fixture["prompt_id"],
               "dimensions": list(DIMENSIONS), "items": blind_items(fixture)}
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    return template.replace("%%RUBRIC%%", rubric_html(rubric_markdown(prompt_text))) \
                   .replace("%%DATA%%", embed_json(payload))


def import_scores(fixture: dict, payload: dict) -> dict:
    """Merge downloaded scores into the fixture. Raises ValueError on anything invalid."""
    if payload.get("fixture_id") != fixture_id(fixture):
        raise ValueError("scores were made from a different calibration fixture")
    items = {i["item_id"]: i for i in fixture["items"]}
    updated = 0
    for item_id, entry in payload.get("scores", {}).items():
        if item_id not in items:
            raise ValueError(f"unknown item {item_id}")
        for dim in DIMENSIONS:
            value = entry.get(dim)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError(f"{item_id}.{dim} must be an integer 1-5, got {value!r}")
            items[item_id]["human_scores"][dim] = value
        notes = entry.get("notes", "")
        if not isinstance(notes, str):
            raise ValueError(f"{item_id}.notes must be text")
        items[item_id]["human_notes"] = notes
        updated += 1
    complete = sum(all(v is not None for v in i["human_scores"].values())
                   for i in fixture["items"])
    return {"items_updated": updated, "items_complete": complete, "items_total": len(items)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    imp = sub.add_parser("import")
    imp.add_argument("--scores", required=True)
    args = ap.parse_args(argv)
    fixture = json.loads(FIXTURE.read_text())
    if args.cmd == "build":
        SHEET.parent.mkdir(parents=True, exist_ok=True)
        SHEET.write_text(build_html(fixture, PROMPT_FILE.read_text()), encoding="utf-8")
        print(f"[sheet] wrote {SHEET} ({len(fixture['items'])} items, "
              f"fixture {fixture_id(fixture)})")
        return 0
    report = import_scores(fixture, json.loads(Path(args.scores).read_text()))
    FIXTURE.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")
    print(f"[sheet] imported: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
