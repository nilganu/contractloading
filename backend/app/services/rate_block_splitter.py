"""Split a hotel sheet into one IR document per rate block.

Hotel contract sheets often contain multiple stacked rate blocks
(eg "Contract Rate", "Booking Window", "Early Booking", "Special Offer")
under the same hotel header. When we hand the whole sheet to the LLM it
sees ~3,000 cells of dense data and the row-emission rate plummets.

Splitting into one document per block keeps the LLM's attention focused
and lets the chunker schedule each block independently.

Detection strategy:
- A row is a "block header" if at least one cell contains a marker token
  like "Contract Rate", "Booking Window", "Early Booking", "Special Offer",
  "SPO", "Promotion" — case-insensitive, in a row that has fewer than N
  numeric cells (a true header, not a date row).
- The hotel-level metadata (currency, treatment, hotel name, occupancy
  table) lives ABOVE the first block header and gets duplicated into
  every block sub-document so each block carries enough context to be
  extracted standalone.
- Within a block, the sub-document spans from one header row to just
  before the next header row (or to end-of-sheet).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_BLOCK_MARKERS = [
    "contract rate",
    "booking window",
    "early booking",
    "ebd",
    "spo",
    "special offer",
    "promotion",
    "winter season",
    "summer season",
    "shoulder season",
    "high season",
    "low season",
]


def _row_text(row: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for c in row:
        v = c.get("value")
        if v is None:
            continue
        parts.append(str(v))
    return " | ".join(parts)


def _row_numeric_count(row: List[Dict[str, Any]]) -> int:
    n = 0
    for c in row:
        v = c.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if 5 <= abs(float(v)) <= 50_000:
                n += 1
    return n


def _row_filled_cell_count(row: List[Dict[str, Any]]) -> int:
    """Number of cells whose value is a non-empty string after str-strip."""
    n = 0
    for c in row:
        v = c.get("value")
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            n += 1
        elif not isinstance(v, str) and v != "":
            n += 1
    return n


# Column-header signature: a row is a column-header row (NOT a block boundary)
# if it contains both "from" and "to" as separate cells, or has many filled
# text cells with structural words like "release", "supplement", "rate", etc.
_COLUMN_HEADER_SIGNALS = {
    "from",
    "to",
    "release",
    "supplement",
    "reduction",
    "1st child",
    "2nd child",
    "3rd child",
    "extra adult",
    "child policy",
    "room type",
    "occupancies",
    "min pax",
    "max pax",
    "min adults",
    "max adults",
}


def _looks_like_column_header(row: List[Dict[str, Any]]) -> bool:
    """Identify the rate-table column-header row so we don't misread it as a
    block boundary. Such rows have many filled cells AND contain typical
    column-header words like FROM / TO / release / supplement."""
    if _row_filled_cell_count(row) < 5:
        return False
    text = _row_text(row).lower()
    hits = sum(1 for s in _COLUMN_HEADER_SIGNALS if s in text)
    return hits >= 2


def _is_block_header_row(row: List[Dict[str, Any]]) -> Optional[str]:
    """Return the matched marker text if this row is a block header, else None."""
    text = _row_text(row).lower()
    if not text.strip():
        return None
    # Skip rows that look like data rows (lots of numeric cells)
    if _row_numeric_count(row) >= 3:
        return None
    # Skip rate-table column-header rows even when they contain marker words
    # like "Booking Window" (Volonline puts that as the rightmost COLUMN name).
    if _looks_like_column_header(row):
        return None
    for m in _BLOCK_MARKERS:
        if m in text:
            return text.strip()
    # "BW" abbreviation only when used as a word (surrounded by spaces or
    # punctuation), not as part of another word.
    if re.search(r"(?<![a-z0-9])bw(?![a-z0-9])", text):
        return text.strip()
    return None


def _rows_to_text(rows: List[List[Dict[str, Any]]]) -> str:
    lines: List[str] = []
    for r in rows:
        parts = []
        for c in r:
            v = c.get("value")
            parts.append("" if v is None else str(v))
        while parts and parts[-1] == "":
            parts.pop()
        lines.append("\t".join(parts))
    return "\n".join(lines)


def split_sheet_into_rate_blocks(sheet: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of sub-sheet dicts, each describing one rate block.

    Each sub-sheet has:
      name      — original sheet name with " | <block-title>" appended
      title     — the block-header text (eg "Contract Rate")
      used_range, merged_ranges, hidden_rows, hidden_columns — copied through
      rows      — header rows (above first block) + this block's rows
    If no block headers are detected, returns a single sub-sheet covering
    the whole sheet (so the rest of the pipeline behaves unchanged).
    """
    rows = sheet.get("rows") or []
    name = sheet.get("name") or "Sheet"
    if not rows:
        return [sheet]

    # Find header-row indices (rows that mark a new block)
    header_indices: List[int] = []
    header_titles: List[str] = []
    for idx, r in enumerate(rows):
        marker = _is_block_header_row(r)
        if marker:
            header_indices.append(idx)
            header_titles.append(marker)

    # No markers found -> single block
    if not header_indices:
        return [{**sheet, "title": None}]

    # Hotel-level header lines = everything above the first block header
    preamble = rows[: header_indices[0]]

    sub_sheets: List[Dict[str, Any]] = []
    for i, start in enumerate(header_indices):
        end = header_indices[i + 1] if i + 1 < len(header_indices) else len(rows)
        block_rows = rows[start:end]
        # Each sub-sheet starts with the preamble (hotel context) then the block
        combined_rows = list(preamble) + list(block_rows)
        sub_sheets.append(
            {
                **sheet,
                "name": f"{name} | {header_titles[i][:40]}",
                "title": header_titles[i],
                "rows": combined_rows,
                "block_index": i,
                "block_count": len(header_indices),
                "preamble_rows": len(preamble),
            }
        )

    return sub_sheets
