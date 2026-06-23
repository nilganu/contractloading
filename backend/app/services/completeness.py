"""Post-extraction completeness check.

For each hotel_contract document with a vision-extracted rate table, count
how many (period × room × board) combinations exist and compare to the
number of hotel rows the LLM produced for that document. If the gap is
material, surface an extraction note so reviewers see it before exporting.

This is intentionally a soft check — it doesn't block the job, just adds
warnings + a note. Hand-edits in the UI can resolve the gap.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Tuple


_ROOM_HINTS = {
    "double",
    "single",
    "twin",
    "triple",
    "quad",
    "suite",
    "superior",
    "deluxe",
    "family",
    "studio",
    "bungalow",
    "villa",
    "room",
}
_BOARD_TOKENS = {"BB", "HB", "FB", "AI", "RO", "UAI"}
_DATE_RE = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}")


def _is_room_label(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    low = s.strip().lower()
    if not low or len(low) < 3:
        return False
    return any(token in low for token in _ROOM_HINTS)


def _is_period_label(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    return bool(_DATE_RE.search(s))


def _is_board_label(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    upper = s.strip().upper()
    return upper in _BOARD_TOKENS


def estimate_rate_dimensions(table: Dict[str, Any]) -> Tuple[int, int, int]:
    """Return (rooms, periods, boards) detected in a vision-style table.

    Vision-style tables are dict-shaped (columns + list of row dicts). Heuristic:
    - Rooms: columns whose header text looks like a room label.
    - Periods: distinct values in the "period" / first-textual column whose
      cell value contains a date.
    - Boards: distinct board codes that appear in any cell.
    """
    rooms = 0
    periods: set[str] = set()
    boards: set[str] = set()

    cols = table.get("columns") or []
    if cols:
        rooms = sum(1 for c in cols if _is_room_label(c))

    rows = table.get("rows") or []
    for row in rows:
        if isinstance(row, dict):
            cells = list(row.values())
            keys = list(row.keys())
        elif isinstance(row, list):
            cells = list(row)
            keys = []
        else:
            continue
        for cell in cells + keys:
            if _is_period_label(cell):
                # normalize whitespace so '01.04.2026 - 13.06.2026' counts once
                periods.add(re.sub(r"\s+", " ", str(cell).strip()))
            if _is_board_label(cell):
                boards.add(str(cell).strip().upper())

    return rooms, len(periods), len(boards)


def check_completeness(ir: Dict[str, Any], result: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (extra_notes, extra_warnings) describing under-extraction.

    Only fires for documents with structured vision tables that look like rate
    tables (>= 2 rooms, >= 1 period, >= 1 board).
    """
    extra_notes: List[Dict[str, Any]] = []
    extra_warnings: List[str] = []
    source_file = (result.get("workbookSummary") or {}).get("sourceFile") or ir.get(
        "source_file", "unknown"
    )

    rows_by_source: Dict[str, int] = {}
    for r in result.get("hotelRows") or []:
        key = r.get("sourceSheetOrPage") or "—"
        rows_by_source[key] = rows_by_source.get(key, 0) + 1

    for doc in ir.get("documents") or []:
        doc_id = doc.get("id") or "doc"
        if (doc.get("classification") or "") != "hotel_contract":
            continue
        for t in doc.get("tables") or []:
            if not isinstance(t, dict):
                continue
            if t.get("source") != "vision":
                continue
            rooms, periods, boards = estimate_rate_dimensions(t)
            if rooms < 2 or periods < 1 or boards < 1:
                continue
            expected = rooms * periods * boards
            actual = rows_by_source.get(doc_id, 0)
            if actual < int(expected * 0.5):  # less than half = significantly short
                gap = expected - actual
                msg = (
                    f"Detected a rate table on {doc_id} with {rooms} room column(s), "
                    f"{periods} period(s) and {boards} board plan(s) — expected up to "
                    f"{expected} Hotel rows but only {actual} were generated "
                    f"({gap} missing). Review the source preview and add the missing "
                    "rows by hand, or re-run with Force Vision and a different DPI."
                )
                extra_warnings.append(msg)
                extra_notes.append(
                    {
                        "id": f"note_{uuid.uuid4().hex[:8]}",
                        "Source File": source_file,
                        "Page": doc_id,
                        "Category": "Source ambiguity",
                        "Note": msg,
                        "_sourceRefs": [doc.get("source_ref")] if doc.get("source_ref") else [],
                        "_confidence": 0.3,
                        "hotelName": None,
                        "linkedHotelRowId": None,
                    }
                )

    return extra_notes, extra_warnings
