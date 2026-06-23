"""Render PDF pages to PNG and run OpenAI vision on each flagged page.

We keep this in its own module so the basic `parse_pdf` stays cheap and offline.
The job pipeline decides when to invoke this based on the page-level
`needs_vision` flag and the user-selected extraction_mode.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

from .image import run_vision_on_image


_VISION_PROMPT = (
    "You are transcribing a hotel contract page faithfully.\n"
    "\n"
    "OUTPUT FORMAT:\n"
    "Output TWO sections.\n"
    "\n"
    "Section 1 — TEXT TRANSCRIPTION (header: '## TEXT'):\n"
    "All non-table visible text on the page, in reading order. Preserve "
    "bullet points, headings, percentages, dates and numeric values exactly.\n"
    "\n"
    "Section 2 — TABLES (header: '## TABLES'):\n"
    "For every visible TABLE on the page, output a single fenced JSON block "
    "wrapped in ```json ... ```. The JSON must be an array of table objects:\n"
    "  [\n"
    "    {\n"
    "      \"title\": \"<short label, eg 'Price List' or 'Occupancies' or null>\",\n"
    "      \"columns\": [<list of column header strings, in left-to-right order>],\n"
    "      \"rows\": [\n"
    "        {<column header>: <cell value>, ...}\n"
    "      ]\n"
    "    }\n"
    "  ]\n"
    "\n"
    "RATE-TABLE RULES (CRITICAL):\n"
    "Hotel rate tables typically have one PERIOD column on the left, one "
    "BOARD column (BB/HB/FB/AI/RO), and several ROOM columns to the right "
    "(eg 'Double for Single', 'Double', 'Superior', 'Family').\n"
    "1. EVERY board line MUST carry its OWN period value. If the PERIOD cell "
    "is visually merged across N board rows (because it's a tall cell), "
    "REPEAT the period text into every board row in the JSON.\n"
    "2. If a PERIOD cell contains TWO OR MORE date ranges stacked vertically "
    "WITHIN THE SAME CELL (no horizontal divider line between them), join "
    "them with ' & ' in that period value (eg "
    "'01.04.2026 - 13.06.2026 & 15.09.2026 - 31.10.2026'). DO NOT promote "
    "the second range into a separate period row — that would shift all "
    "subsequent prices up by one row.\n"
    "3. Use the original room column labels exactly as printed — do not "
    "rename 'Double for Single' to 'SGL' or similar.\n"
    "4. Preserve all numeric values exactly: €62,00 stays as '€62,00' (not "
    "'62' or '62.00'). Comma vs dot is preserved.\n"
    "5. n/a, free, FOC, -30%, -50%, included — preserved literally.\n"
    "6. Do not summarise; one row per visible source row.\n"
    "\n"
    "VERIFY BEFORE RETURNING:\n"
    "Count the BB/HB/FB/AI lines in the rate table source. Count the rows in "
    "your JSON output. They must match. If you produced fewer rows, you "
    "swallowed a row — re-do until counts match.\n"
    "\n"
    "Return only the two sections — no commentary."
)


_TABLES_HEADER_RE = re.compile(r"##\s*TABLES", re.IGNORECASE)
_TEXT_HEADER_RE = re.compile(r"##\s*TEXT", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def split_vision_sections(raw_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Split the two-section vision response into plain text + parsed tables.

    Falls back gracefully: if the model returned plain text without the
    ## TEXT / ## TABLES headers, the whole thing is treated as text and no
    structured tables are returned.
    """
    if not raw_text:
        return "", []

    text_part = raw_text
    tables_block: str = ""

    if _TABLES_HEADER_RE.search(raw_text):
        m = _TABLES_HEADER_RE.search(raw_text)
        text_part = raw_text[: m.start()]
        tables_block = raw_text[m.end():]
        if _TEXT_HEADER_RE.search(text_part):
            tm = _TEXT_HEADER_RE.search(text_part)
            text_part = text_part[tm.end():]

    tables: List[Dict[str, Any]] = []
    if tables_block:
        fences = _JSON_FENCE_RE.findall(tables_block)
        for fence in fences:
            try:
                parsed = json.loads(fence)
                if isinstance(parsed, list):
                    for t in parsed:
                        if isinstance(t, dict) and "rows" in t:
                            tables.append(t)
                elif isinstance(parsed, dict) and "rows" in parsed:
                    tables.append(parsed)
            except json.JSONDecodeError:
                continue
        if not fences:
            try:
                parsed = json.loads(tables_block.strip())
                if isinstance(parsed, list):
                    tables.extend([t for t in parsed if isinstance(t, dict) and "rows" in t])
                elif isinstance(parsed, dict) and "rows" in parsed:
                    tables.append(parsed)
            except json.JSONDecodeError:
                pass

    return text_part.strip(), tables


def render_page_to_png(pdf_path: str | Path, page_number: int, *, resolution: int = 220) -> bytes:
    """Render a single page (1-indexed) to PNG bytes via pdfplumber."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_number - 1]
        im = page.to_image(resolution=resolution)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


def run_vision_on_pdf_page(
    pdf_path: str | Path,
    page_number: int,
    *,
    resolution: int = 220,
    tmp_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Render the page and forward to the OpenAI vision call.

    The vision call takes a file path; we materialize the rendered PNG to a
    temp file so we reuse run_vision_on_image unchanged.
    """
    import tempfile

    png = render_page_to_png(pdf_path, page_number, resolution=resolution)
    if tmp_dir is None:
        tmp_dir = Path(tempfile.gettempdir())
    out_path = tmp_dir / f"pdfpage-{Path(pdf_path).stem}-p{page_number}.png"
    out_path.write_bytes(png)
    return run_vision_on_image(out_path, prompt=_VISION_PROMPT)


def enrich_pdf_with_vision(
    parsed: Dict[str, Any],
    pdf_path: str | Path,
    *,
    extraction_mode: str = "auto",
    max_workers: int = 4,
    progress_cb=None,
) -> Dict[str, Any]:
    """Attach vision text to every page that the parser flagged as needing it.

    - extraction_mode='text_only'      : never call vision
    - extraction_mode='auto'           : call vision when needs_vision is true
    - extraction_mode='vision_allowed' : call vision when needs_vision is true
    - extraction_mode='vision_required': call vision on EVERY page

    Vision calls are parallelized up to `max_workers`. `progress_cb`, if given,
    is called with (done, total) after each page completes.
    """
    if extraction_mode == "text_only":
        return parsed

    from concurrent.futures import ThreadPoolExecutor, as_completed

    pages = parsed.get("pages", [])
    targets = [
        p for p in pages
        if p.get("needs_vision") or extraction_mode == "vision_required"
    ]
    if not targets:
        return parsed

    warnings: List[str] = []
    total = len(targets)
    done = 0

    def _work(page_dict: Dict[str, Any]) -> Dict[str, Any]:
        try:
            out = run_vision_on_pdf_page(pdf_path, page_dict["page_number"])
            raw = out.get("text") or ""
            text_part, tables = split_vision_sections(raw)
            return {
                "page_number": page_dict["page_number"],
                "text": text_part or raw,
                "tables": tables,
                "warnings": out.get("warnings") or [],
                "error": None,
            }
        except Exception as e:  # noqa: BLE001
            return {
                "page_number": page_dict["page_number"],
                "text": "",
                "tables": [],
                "warnings": [],
                "error": f"{type(e).__name__}: {e}",
            }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_work, p): p for p in targets}
        results: Dict[int, Dict[str, Any]] = {}
        for fut in as_completed(futures):
            r = fut.result()
            results[r["page_number"]] = r
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:  # noqa: BLE001
                    pass

    for page in pages:
        r = results.get(page["page_number"])
        if not r:
            continue
        page["vision_text"] = r["text"]
        page["vision_tables"] = r.get("tables") or []
        page["vision_warnings"] = r["warnings"]
        if r["error"]:
            warnings.append(f"Vision failed for page {page['page_number']}: {r['error']}")
        elif not r["text"] and not page["vision_tables"]:
            warnings.append(f"Vision produced no text for page {page['page_number']}")

    if warnings:
        parsed.setdefault("warnings", []).extend(warnings)
    return parsed
