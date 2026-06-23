"""PDF extraction strategy router.

Different PDF contracts demand different pipelines:

  native_text_llm   — clean digital PDF, real text + tables. Cheapest:
                      send the IR's parsed text to the LLM extractor.
                      Vision is skipped.
  two_call_vision   — PDF with tables that pdfplumber couldn't extract
                      cleanly (merged cells, low-quality OCR'd text,
                      rate-table tokens with no numeric table). Run
                      skeleton-then-fill vision on each batch.
  vision_only       — Scanned PDF: no text at all. Render every page and
                      ask vision to do the full job.

Strategy is chosen from per-page parser diagnostics. The user's
extractionMode option overrides the auto-detection:

  text_only         → force native_text_llm
  vision_required   → force vision_only
  vision_allowed/auto → use auto-detection (this module)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal

logger = logging.getLogger(__name__)

Strategy = Literal["native_text_llm", "two_call_vision", "vision_only"]


def choose_strategy(parsed_pdf: Dict[str, Any], extraction_mode: str) -> Strategy:
    """Decide which strategy to use for a parsed PDF.

    parsed_pdf is the dict returned by parse_pdf — pages carry needs_vision,
    vision_reasons, rate_token_hits, has_numeric_table, scrambled.
    """
    if extraction_mode == "text_only":
        return "native_text_llm"
    if extraction_mode == "vision_required":
        return "vision_only"

    pages = parsed_pdf.get("pages") or []
    if not pages:
        return "native_text_llm"

    total = len(pages)
    empty_pages = sum(
        1 for p in pages if (len((p.get("text") or "").strip()) < 20 and not p.get("tables"))
    )
    scrambled_pages = sum(1 for p in pages if p.get("scrambled"))
    rate_without_table = sum(
        1 for p in pages
        if p.get("rate_token_hits", 0) >= 3 and not p.get("has_numeric_table")
    )
    has_useful_tables = any(p.get("has_numeric_table") for p in pages)
    rate_hits_total = sum(p.get("rate_token_hits", 0) for p in pages)

    # Mostly empty/scanned -> vision only.
    if empty_pages >= max(1, int(total * 0.6)):
        logger.info("Strategy: vision_only (%d/%d empty pages)", empty_pages, total)
        return "vision_only"

    # Visible rate text but no numeric tables, or scrambled text — use
    # two-call vision so we capture the actual price grid.
    if scrambled_pages or rate_without_table:
        logger.info(
            "Strategy: two_call_vision (scrambled=%d, rate_without_table=%d)",
            scrambled_pages,
            rate_without_table,
        )
        return "two_call_vision"

    # If pdfplumber extracted real numeric tables and the text isn't
    # scrambled, the LLM-on-text path is cheaper and good enough.
    if has_useful_tables and rate_hits_total >= 3:
        logger.info("Strategy: native_text_llm (clean tables + rate tokens)")
        return "native_text_llm"

    # Anything else — default to two-call vision; it costs more but is more
    # robust on unfamiliar layouts.
    logger.info("Strategy: two_call_vision (default for ambiguous layout)")
    return "two_call_vision"
