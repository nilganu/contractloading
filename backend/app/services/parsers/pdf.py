"""PDF parser.

Strategy:
1. Try digital text extraction via pdfplumber.
2. Extract tables per page.
3. Flag the page for OCR/vision fallback when:
   - it has effectively no text AND no tables, OR
   - the extracted text is "scrambled" (lots of one-character tokens — common
     when pdfplumber misreads tight letter-spacing), OR
   - the page text contains rate-table tokens (PERIOD, FROM, TO, BB, HB, etc.)
     but no numeric table was extracted (the table was rendered as graphics).

The actual vision call is performed by the job pipeline through
parsers.image.run_vision_on_image so the text-extraction path stays cheap.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import pdfplumber

# Tokens that look like rate-table headers.
_RATE_TOKENS = {
    "from",
    "to",
    "period",
    "room",
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
    "board",
    "allotment",
    "occupancy",
    "per person",
    "per room",
    "per night",
    "price list",
    "season",
}


def _has_numeric_table(tables: List[Dict[str, Any]]) -> bool:
    """A table is "numeric" if at least one cell parses as a non-trivial number
    AND at least one other cell looks like a date or month label."""
    has_num = False
    has_date = False
    for t in tables:
        for row in (t.get("rows") or []):
            for cell in row:
                s = (cell or "").strip()
                if not s:
                    continue
                cleaned = s.replace(",", "").replace("€", "").replace("$", "").strip()
                try:
                    val = float(cleaned)
                    if abs(val) >= 5:  # rate-like, not just a footnote "1"
                        has_num = True
                except ValueError:
                    if re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", s) or re.search(
                        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", s, re.I
                    ):
                        has_date = True
        if has_num and has_date:
            return True
    return False


def _is_scrambled(text: str) -> bool:
    """Heuristic: lots of single-letter or two-letter tokens indicates that
    pdfplumber misread tight letter-spacing (eg "F L Y 4 Y O U" instead of
    "FLY4YOU"). When more than 35% of tokens are 1-2 chars, treat as scrambled.
    """
    if not text or len(text) < 80:
        return False
    tokens = re.findall(r"\S+", text)
    if len(tokens) < 30:
        return False
    short = sum(1 for t in tokens if len(t) <= 2 and t.isalnum())
    return (short / len(tokens)) > 0.35


def _rate_token_hits(text: str) -> int:
    lower = text.lower()
    return sum(1 for tok in _RATE_TOKENS if tok in lower)


def parse_pdf(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(p) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables_raw = []
            try:
                tables_raw = page.extract_tables() or []
            except Exception:  # noqa: BLE001
                tables_raw = []

            tables: List[Dict[str, Any]] = []
            for t_idx, t in enumerate(tables_raw, start=1):
                tables.append(
                    {
                        "index": t_idx,
                        "rows": [[(c or "") for c in row] for row in t],
                    }
                )

            scrambled = _is_scrambled(text)
            rate_hits = _rate_token_hits(text)
            has_numeric = _has_numeric_table(tables)

            empty_page = len(text.strip()) < 20 and not tables
            scrambled_page = scrambled
            rate_without_table = rate_hits >= 3 and not has_numeric

            needs_vision = empty_page or scrambled_page or rate_without_table

            vision_reasons: List[str] = []
            if empty_page:
                vision_reasons.append("empty_page")
            if scrambled_page:
                vision_reasons.append("scrambled_text")
            if rate_without_table:
                vision_reasons.append("rate_tokens_without_numeric_table")

            pages.append(
                {
                    "page_number": idx,
                    "text": text,
                    "tables": tables,
                    "needs_vision": needs_vision,
                    "vision_reasons": vision_reasons,
                    "rate_token_hits": rate_hits,
                    "has_numeric_table": has_numeric,
                    "scrambled": scrambled,
                    "width": float(page.width or 0),
                    "height": float(page.height or 0),
                }
            )
    return {
        "source_file": p.name,
        "input_format": "pdf",
        "pages": pages,
    }


def page_text_preview(page: Dict[str, Any], max_chars: int = 6000) -> str:
    text = page.get("text") or ""
    if page.get("vision_text"):
        text = (text + "\n\n=== VISION TRANSCRIPTION ===\n" + page["vision_text"]).strip()
    # Append vision-extracted tables as JSON so the LLM gets structured data
    vision_tables = page.get("vision_tables") or []
    if vision_tables:
        import json as _json
        text += (
            "\n\n=== VISION TABLES (structured) ===\n"
            + _json.dumps(vision_tables, ensure_ascii=False)
        )
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text
