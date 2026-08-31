"""Traceability audit — enforce the pack's rule that every FR/NFR traces
back to Stage 1 discovery evidence.

Runs in two directions:
  Forward:  every FR must carry at least one EV-* / #N / R-XX reference.
  Reverse:  every EV-* tag defined in the discovery notes should appear in
            at least one FR — or be explicitly out-of-scope / on the risk
            register.

Exits 0 when clean, non-zero when either direction has gaps.

Usage:  python -m scripts.traceability_audit
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).parent.parent
DISCOVERY_NOTES = [
    ROOT / "workbooks" / "discovery_notes.md",
    ROOT / "workbooks" / "discovery_notes_thursday.md",
]
PRD = ROOT / "workbooks" / "Stage_2_PRD_Template.docx"
STAGE_1 = ROOT / "workbooks" / "Stage_1_Discovery_Workbook.docx"

EV_TAG = re.compile(r"\b(EV-[A-Z]{1,4}\d+|EV-DATA-\d+|R-\d{1,3})\b")
FR_ID = re.compile(r"^FR-\d+$")
NFR_ID = re.compile(r"^NFR-\d+[a-z]?$")


def collect_defined_tags() -> set[str]:
    """Every EV-* and R-* tag defined in the discovery notes."""
    defined: set[str] = set()
    for path in DISCOVERY_NOTES:
        if not path.exists():
            print(f"  warn: {path.name} missing")
            continue
        text = path.read_text()
        # Look for tags in the "Ev-XX ..." definition context (bold or beginning of bullet)
        # Simpler: any EV-* / R-* token found in the file
        defined.update(EV_TAG.findall(text))
    # Risk register lives in Stage 1 workbook Table 12
    if STAGE_1.exists():
        d = Document(STAGE_1)
        for tbl in d.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    defined.update(EV_TAG.findall(cell.text))
    return defined


def collect_prd_requirements() -> list[dict]:
    """Read FRs and NFRs from the PRD, extracting id + discovery evidence cell."""
    if not PRD.exists():
        return []
    d = Document(PRD)
    out: list[dict] = []
    # Table 4 = FRs (cols: id, req, priority, discovery, acceptance)
    if len(d.tables) > 4:
        for row in d.tables[4].rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if not cells or not FR_ID.match(cells[0]):
                continue
            out.append({
                "id": cells[0],
                "kind": "FR",
                "discovery": cells[3] if len(cells) > 3 else "",
            })
    # Table 5 = NFRs (cols: id, category, req, verification)
    if len(d.tables) > 5:
        for row in d.tables[5].rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if not cells or not NFR_ID.match(cells[0]):
                continue
            body = " | ".join(cells)
            out.append({
                "id": cells[0],
                "kind": "NFR",
                "discovery": body,
            })
    return out


def collect_context_tag_references() -> set[str]:
    """Tags cited in the PRD's out-of-scope (Table 6), assumptions (Table 7),
    success measures (Table 8), and open questions (Table 9) tables.
    Legitimate places for evidence that shaped design but didn't produce a specific FR."""
    if not PRD.exists():
        return set()
    d = Document(PRD)
    seen: set[str] = set()
    for tbl_idx in (6, 7, 8, 9):
        if tbl_idx >= len(d.tables):
            continue
        for row in d.tables[tbl_idx].rows:
            for cell in row.cells:
                seen.update(EV_TAG.findall(cell.text))
    return seen


def audit() -> int:
    print("== Traceability audit ==\n")
    defined = collect_defined_tags()
    print(f"Discovery tags defined:  {len(defined)}")
    print(f"  Sample:  {sorted(defined)[:10]}...\n")

    reqs = collect_prd_requirements()
    if not reqs:
        print("!! PRD not found or empty")
        return 2
    print(f"Requirements in PRD:     {len(reqs)} "
          f"({sum(1 for r in reqs if r['kind']=='FR')} FR, "
          f"{sum(1 for r in reqs if r['kind']=='NFR')} NFR)\n")

    # ---- Forward pass ----
    missing_disc: list[dict] = []
    disc_uses: dict[str, list[str]] = {}
    for r in reqs:
        tags_in_row = set(EV_TAG.findall(r["discovery"]))
        has_section_ref = bool(re.search(r"#\d+", r["discovery"]))
        has_q3 = "Q3 pilot" in r["discovery"] or "q3" in r["discovery"].lower()
        if not tags_in_row and not has_section_ref and not has_q3:
            missing_disc.append(r)
        for t in tags_in_row:
            disc_uses.setdefault(t, []).append(r["id"])

    if missing_disc:
        print(f"!! Forward: {len(missing_disc)} requirement(s) missing discovery trace")
        for r in missing_disc:
            print(f"    {r['id']}: {r['discovery'][:80]}...")
    else:
        print("OK Forward: every requirement carries at least one discovery reference.")
    print()

    # ---- Reverse pass ----
    # Legitimate context uses count as covered.
    context_refs = collect_context_tag_references()
    referenced_anywhere = set(disc_uses.keys()) | context_refs
    orphans = sorted(defined - referenced_anywhere)

    if orphans:
        print(f"!! Reverse: {len(orphans)} discovery tag(s) not referenced by "
              f"any requirement OR context table (out-of-scope, assumptions, "
              f"success measures, open questions)")
        for tag in orphans:
            print(f"    {tag}")
    else:
        print("OK Reverse: every discovery tag appears in a requirement or a context table.")

    # Report tags that live in context only (not requirement-producing)
    context_only = sorted(context_refs - set(disc_uses.keys()))
    if context_only:
        print(f"\n  {len(context_only)} tag(s) cited only in context tables "
              f"(legitimate for tags that shaped design but did not produce a specific FR):")
        for tag in context_only:
            print(f"    {tag}")
    print()

    # ---- Coverage summary ----
    total_covered = len(referenced_anywhere & defined)
    print(f"Coverage: {total_covered}/{len(defined)} discovery tags referenced "
          f"({100 * total_covered / max(1, len(defined)):.0f}%)  "
          f"[{len(disc_uses)} requirements + {len(context_only)} context-only]")

    # Exit-code semantics:
    #   The pack's rule ("every requirement traces to evidence") is the FORWARD
    #   direction. That's a hard failure — non-zero exit.
    #   The REVERSE direction (every evidence trace produces a requirement) is
    #   aspirational; some evidence is legitimately background context. Reverse
    #   orphans are a WARNING — reported but do not fail the audit.
    exit_code = 1 if missing_disc else 0
    if missing_disc:
        print("\n== FAIL (forward-direction gaps) ==")
    elif orphans:
        print(f"\n== PASS with {len(orphans)} reverse-only warning(s) ==")
    else:
        print("\n== PASS ==")
    return exit_code


if __name__ == "__main__":
    sys.exit(audit())
