"""Sheet / page classifier.

Classifies each Excel sheet or PDF page into one of:
- index_reference     (eg "Hotel List" — list of hotels with destination, codes)
- hotel_contract      (per-hotel rate sheet)
- support_notes       (cancellation, policies, generic notes)
- unknown
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Tuple

SheetKind = Literal["index_reference", "hotel_contract", "support_notes", "unknown"]


INDEX_NAME_HINTS = [
    "hotel list",
    "index",
    "summary",
    "contents",
    "hotels",
    "table of contents",
]

HOTEL_NAME_HINTS_REGEX = re.compile(
    r"\b(hotel|resort|inn|palace|villa|residence|suites|spa|club|riad)\b",
    re.IGNORECASE,
)

RATE_TABLE_HEADER_HINTS = {
    "from",
    "to",
    "valid from",
    "valid to",
    "start",
    "end",
    "room",
    "villa",
    "pavilion",
    "bungalow",
    "suite",
    "studio",
    "chalet",
    "cabana",
    "residence",
    "rate",
    "rates",
    "single",
    "double",
    "triple",
    "child",
    "chd",
    "sgl",
    "dbl",
    "tpl",
    "extra bed",
    "supplement",
    "release",
    "min stay",
    "meal",
    "bb",
    "hb",
    "fb",
    "ai",
}

NOTES_TEXT_HINTS = {
    "cancellation",
    "no show",
    "no-show",
    "terms",
    "conditions",
    "tax",
    "service charge",
    "vat",
    "gala",
    "christmas",
    "new year",
    "booking window",
}


def _flatten_sheet_text(sheet: Dict[str, Any], max_cells: int = 400) -> List[str]:
    out: List[str] = []
    for row in sheet.get("rows", []):
        for cell in row:
            v = cell.get("value")
            if v is None:
                continue
            s = str(v).strip().lower()
            if s:
                out.append(s)
            if len(out) >= max_cells:
                return out
    return out


def classify_excel_sheet(sheet: Dict[str, Any]) -> Tuple[SheetKind, Dict[str, Any]]:
    name = (sheet.get("name") or "").strip()
    name_l = name.lower()

    details: Dict[str, Any] = {"name": name}

    if any(hint in name_l for hint in INDEX_NAME_HINTS):
        details["reason"] = f"Sheet name matched index hint: '{name}'"
        return "index_reference", details

    cells = _flatten_sheet_text(sheet)
    cell_set = set(cells)

    rate_hits = len(RATE_TABLE_HEADER_HINTS & cell_set)
    note_hits = len(NOTES_TEXT_HINTS & cell_set)

    detected_hotel_name = None
    for row in sheet.get("rows", [])[:8]:
        for cell in row:
            v = cell.get("value")
            if v is None:
                continue
            s = str(v).strip()
            if HOTEL_NAME_HINTS_REGEX.search(s) and len(s) <= 80:
                detected_hotel_name = s
                break
        if detected_hotel_name:
            break

    details["detected_hotel_name"] = detected_hotel_name
    details["rate_header_hits"] = rate_hits
    details["notes_hits"] = note_hits

    if rate_hits >= 3:
        details["reason"] = (
            f"Detected {rate_hits} rate-table header tokens; treating as hotel contract."
        )
        return "hotel_contract", details

    if HOTEL_NAME_HINTS_REGEX.search(name):
        details["reason"] = f"Sheet name looks like a hotel name: '{name}'"
        return "hotel_contract", details

    if note_hits >= 3 and rate_hits < 2:
        details["reason"] = f"Detected {note_hits} policy/notes tokens; treating as support notes."
        return "support_notes", details

    details["reason"] = "Unable to classify confidently."
    return "unknown", details


def classify_pdf_page(page: Dict[str, Any]) -> Tuple[SheetKind, Dict[str, Any]]:
    text = (page.get("text") or "").lower()
    has_tables = bool(page.get("tables"))
    rate_hits = sum(1 for h in RATE_TABLE_HEADER_HINTS if h in text)
    note_hits = sum(1 for h in NOTES_TEXT_HINTS if h in text)

    details: Dict[str, Any] = {
        "page_number": page.get("page_number"),
        "rate_header_hits": rate_hits,
        "notes_hits": note_hits,
        "has_tables": has_tables,
    }
    if rate_hits >= 3 or (has_tables and rate_hits >= 1):
        details["reason"] = "Page contains rate-table tokens."
        return "hotel_contract", details
    if note_hits >= 3:
        details["reason"] = "Page contains policy/notes tokens."
        return "support_notes", details
    details["reason"] = "Page didn't match rate or notes hints."
    return "unknown", details
