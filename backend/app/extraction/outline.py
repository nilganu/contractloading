"""Document outline pass — Phase 2 Layer 1.

For multi-hotel contracts we need to know how many hotels there are and
where each one lives, BEFORE running the heavy per-hotel extraction. The
outline is then fed into ``splitters.split_for_hotel`` so each per-hotel
LLM call sees only that hotel's data.

Two implementations:
- Excel (.xlsx/.xls): list sheet names locally and filter out
  index/cover sheets — no LLM call needed, zero cost.
- Everything else (PDF, DOCX, image): one LLM call against the file with
  a strict ``DocumentOutline`` schema.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..config import get_settings
from .splitters import is_index_sheet, list_excel_sheets

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "extraction"
    / "contract-outline-v1.txt"
)


class HotelOutlineEntry(BaseModel):
    """One hotel detected in the contract."""

    name: str = Field(description="Hotel name as it appears in the contract.")
    source_hint: Optional[str] = Field(
        default=None,
        description=(
            "Short pointer to where this hotel's data lives: 'Sheet:<name>' "
            "for Excel, 'Pages 3-5' for PDF, or a section title for DOCX."
        ),
    )


class DocumentOutline(BaseModel):
    """Output of the outline pass."""

    is_multi_hotel: bool
    hotels: List[HotelOutlineEntry]
    notes: Optional[str] = Field(
        default=None,
        description="Quick observations about layout for downstream passes.",
    )


# --------------------------------------------------------------------------
# Local (Excel)
# --------------------------------------------------------------------------


def outline_excel_locally(file_path: Path) -> DocumentOutline:
    """For Excel files, the sheet names ARE the hotels (almost always).
    This skips the LLM entirely."""
    sheets = list_excel_sheets(file_path)
    hotels: List[HotelOutlineEntry] = []
    for s in sheets:
        if is_index_sheet(s):
            logger.info("outline (excel): skipping index sheet %r", s)
            continue
        hotels.append(HotelOutlineEntry(name=s, source_hint=f"Sheet:{s}"))
    return DocumentOutline(
        is_multi_hotel=len(hotels) > 1,
        hotels=hotels,
        notes=f"Excel workbook with {len(sheets)} sheet(s); kept {len(hotels)} as hotels.",
    )


# --------------------------------------------------------------------------
# LLM (PDF / DOCX / image / other)
# --------------------------------------------------------------------------


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def outline_via_llm(
    client,
    file_id: str,
    file_block: Dict[str, Any],
    *,
    source_filename: str,
) -> DocumentOutline:
    """One strict-schema LLM call against the uploaded file."""
    settings = get_settings()
    system_prompt = _load_prompt()
    user_directive = (
        f"Source filename: {source_filename}. "
        "Return the list of hotels in this file. Be exhaustive — a missing "
        "hotel here means that hotel's data won't be extracted later."
    )
    logger.info(
        "outline pass (llm): model=%s file_id=%s",
        settings.openai_model_mini, file_id,
    )
    response = client.responses.parse(
        model=settings.openai_model_mini,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "input_text", "text": user_directive},
                ],
            },
        ],
        text_format=DocumentOutline,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError(
            "Outline pass returned no parseable output. "
            f"Raw (first 300 chars): {(response.output_text or '')[:300]!r}"
        )
    return parsed


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def discover_hotels(
    file_path: Path,
    *,
    llm_client_factory=None,
    llm_file_id: Optional[str] = None,
    llm_file_block: Optional[Dict[str, Any]] = None,
) -> DocumentOutline:
    """Return the document outline.

    For Excel files this is a local operation (no LLM, no upload). For
    everything else the orchestrator must have already uploaded the file
    and pass in the client, file_id and file_block for the LLM call.
    """
    ext = file_path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return outline_excel_locally(file_path)
    if llm_client_factory is None or llm_file_id is None or llm_file_block is None:
        raise RuntimeError(
            f"discover_hotels for '{ext}' requires the LLM client + uploaded file_id."
        )
    return outline_via_llm(
        llm_client_factory,
        llm_file_id,
        llm_file_block,
        source_filename=file_path.name,
    )
