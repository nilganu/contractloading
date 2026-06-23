"""Defensive cell audit.

The LLM extraction has a non-trivial failure mode: a price cell visible in
the source rate table never lands in any HotelRow's SGL/DBL/TPL/QDP/dyn
field. That data is then lost — neither in a row nor in the Extraction Notes
sheet. From the reviewer's perspective there's no way to know what was
dropped.

This module compares the structured "vision skeleton" tables (or any
structured rate table in the IR) against the final HotelRows and emits
extraction notes for every numeric price cell that wasn't matched by any
row's price field. It also flags rows whose Room Name has NO price values
populated at all.

This runs after normalize_result. Failures become notes; the job still
completes. The Extraction Notes sheet is the single source of truth for
"what the model saw but didn't fit into the grid."
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple


_RATE_FIELDS = ("SGL", "DBL", "TPL", "QDP", "Extra Bed")
# Anything < 5 is unlikely to be a hotel rate; >50_000 looks like a phone
# number; we accept the rest.
_MIN_RATE = 5.0
_MAX_RATE = 50_000.0


_NUM_RE = re.compile(r"-?\d{1,5}(?:[.,]\d{1,2})?")
_COMPACT_NUM_RE = re.compile(r"-?\d{1,5}(?:\.\d{1,2})?")
_CURRENCY_RE = re.compile(r"(?i)\b(EUR|EURO|USD|US\$|GBP|AED|EGP)\b|[€$£]")
_DATE_OR_PERIOD_RE = re.compile(
    r"\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b"
    r"|\b\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\d{2,4}\b"
    r"|\b\d{1,2}\s*\.\s*\d{1,2}\s*-\s*\d{1,2}\s*\.\s*\d{1,2}\b"
)


def _parse_cell_number(value: Any) -> Optional[float]:
    """Try to extract a numeric price from a cell value.

    Accepts: 62, 62.0, "62", "62,00", "€62", "€62,00", "62.00 EUR".
    Returns None for n/a, free, FOC, -, blanks, or pure-text cells.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if _MIN_RATE <= abs(v) <= _MAX_RATE else None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    upper = s.upper()
    if upper in {"N/A", "NA", "-", "FREE", "FOC", "INCLUDED", "NULL"}:
        return None
    if "%" in s:
        return None

    # pdfplumber can emit whole contract paragraphs or date/min-stay
    # ranges as table cells. They contain numbers, but they are not prices.
    if len(s) > 80 or "|" in s or _DATE_OR_PERIOD_RE.search(s):
        return None

    cleaned = _CURRENCY_RE.sub("", s)
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"\s+", "", cleaned.strip())
    if not _COMPACT_NUM_RE.fullmatch(cleaned):
        return None

    try:
        v = float(cleaned)
    except ValueError:
        return None
    return v if _MIN_RATE <= abs(v) <= _MAX_RATE else None


def _collect_row_prices(row: Dict[str, Any]) -> List[float]:
    out: List[float] = []
    for f in _RATE_FIELDS:
        v = row.get(f)
        if isinstance(v, (int, float)):
            out.append(float(v))
    for v in (row.get("dynamicChildValues") or {}).values():
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def _norm_key(v: Any) -> str:
    if isinstance(v, str):
        return v.strip().lower()
    return ""


def _iter_structured_tables(ir: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Yield (doc_id, table) for every structured table in the IR — pdfplumber
    tables, vision-extracted tables (dict rows or list rows)."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for doc in ir.get("documents") or []:
        for t in doc.get("tables") or []:
            if not isinstance(t, dict):
                continue
            out.append((doc.get("id") or doc.get("source_ref") or "doc", t))
    return out


def _row_signature(row: Dict[str, Any]) -> Tuple:
    """Cheap fingerprint to identify a hotel row in messages."""
    return (
        (row.get("Hotel Name") or "—"),
        (row.get("Room Name") or "—"),
        row.get("Start Date") or "—",
        row.get("End Date") or "—",
        row.get("Meal Plan") or "—",
    )


def audit_cells(ir: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a dict {notes, warnings, stats} describing un-mapped source cells
    and unmapped rows. Callers should append notes to the result and warnings
    to the job.
    """
    new_notes: List[Dict[str, Any]] = []
    new_warnings: List[str] = []

    source_file = (result.get("workbookSummary") or {}).get("sourceFile") or ir.get(
        "source_file", "unknown"
    )

    # All numeric prices observed across hotel rows. We treat this as the
    # "mapped" set. A source cell is "covered" if its value matches at least
    # one row's price.
    mapped_prices: set[float] = set()
    for r in result.get("hotelRows") or []:
        for v in _collect_row_prices(r):
            mapped_prices.add(round(v, 2))

    # Collect every numeric cell from structured tables.
    source_cells: List[Dict[str, Any]] = []
    for doc_id, table in _iter_structured_tables(ir):
        rows = table.get("rows") or []
        columns = table.get("columns") or []

        for r_idx, row in enumerate(rows):
            if isinstance(row, dict):
                # vision-style dict rows
                for col_key, cell in row.items():
                    price = _parse_cell_number(cell)
                    if price is None:
                        continue
                    source_cells.append(
                        {
                            "doc": doc_id,
                            "row_idx": r_idx,
                            "col": col_key,
                            "value": price,
                            "raw": cell,
                        }
                    )
            elif isinstance(row, list):
                for c_idx, cell in enumerate(row):
                    price = _parse_cell_number(cell)
                    if price is None:
                        continue
                    col_name = columns[c_idx] if c_idx < len(columns) else f"col{c_idx + 1}"
                    source_cells.append(
                        {
                            "doc": doc_id,
                            "row_idx": r_idx,
                            "col": col_name,
                            "value": price,
                            "raw": cell,
                        }
                    )

    # Unmapped source cells
    unmapped: List[Dict[str, Any]] = []
    for cell in source_cells:
        if round(cell["value"], 2) not in mapped_prices:
            unmapped.append(cell)

    if unmapped:
        # Group by doc + col so the note is compact instead of one-per-cell.
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for c in unmapped:
            grouped.setdefault((c["doc"], c["col"]), []).append(c)
        for (doc, col), cells in grouped.items():
            sample = ", ".join(
                f"{c['raw']!r}" if isinstance(c["raw"], str) else str(c["raw"])
                for c in cells[:8]
            )
            extra = f" (+{len(cells) - 8} more)" if len(cells) > 8 else ""
            new_notes.append(
                {
                    "id": f"note_{uuid.uuid4().hex[:8]}",
                    "Source File": source_file,
                    "Page": doc,
                    "Category": "Rate anomaly",
                    "Note": (
                        f"Source table on {doc} column {col!r} contained "
                        f"{len(cells)} numeric value(s) that no Hotel row "
                        f"used: {sample}{extra}. Cross-check the rate table "
                        "and add or correct the rows manually if needed."
                    ),
                    "_sourceRefs": [],
                    "_confidence": 0.3,
                    "hotelName": None,
                    "linkedHotelRowId": None,
                }
            )
        new_warnings.append(
            f"{len(unmapped)} source price cell(s) not represented in any Hotel row."
        )

    # Rows that have a Room Name but ZERO numeric price values — these are
    # almost certainly mistakes. Drop them in the defensive filter elsewhere;
    # here we just record the count.
    empty_rows = [
        _row_signature(r)
        for r in (result.get("hotelRows") or [])
        if r.get("Room Name") and not _collect_row_prices(r)
    ]
    if empty_rows:
        new_warnings.append(
            f"{len(empty_rows)} Hotel row(s) carry a Room Name but no rate values."
        )

    return {
        "notes": new_notes,
        "warnings": new_warnings,
        "stats": {
            "source_price_cells": len(source_cells),
            "mapped_price_values": len(mapped_prices),
            "unmapped_cells": len(unmapped),
            "rows_without_prices": len(empty_rows),
        },
    }
