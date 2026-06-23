"""Phase 4 — independent verifier pass.

For each hotel, sends the contract file + the current canonical
extraction to the LLM acting as an auditor. The auditor's job is NOT
to re-extract; it's to spot what's missing or wrong and label each
finding with a precise ``finding_kind`` so the orchestrator can act:

- ``MISSING_SUPPLEMENT`` → trigger a focused retry that re-emits the
  supplement table for this hotel, expecting at least the listed names.
- Other ``finding_kind`` values are surfaced for visibility but don't
  drive auto-fix here (Phase 5 / human review).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..config import get_settings
from .canonical import HotelExtraction, Supplement

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "extraction"
    / "contract-verifier-v1.txt"
)


# --------------------------------------------------------------------------
# Verifier output schema (strict json_schema enforced)
# --------------------------------------------------------------------------


class VerifierFinding(BaseModel):
    """One thing the auditor noticed about the current extraction."""

    finding_kind: Literal[
        "MISSING_SUPPLEMENT",
        "MISSING_RATE_ROW",
        "MISSING_CHILD_BAND",
        "WRONG_VALUE",
        "OTHER",
    ]
    severity: Literal["error", "warning", "info"]
    field_path: str = Field(
        description="Dot/bracket path naming what the finding refers to."
    )
    observation: str = Field(
        description="Plain-English description of what's missing or wrong."
    )
    contract_quote: Optional[str] = Field(
        default=None,
        description="Short verbatim quote from the contract supporting the finding.",
    )
    # Retry payload fields:
    missing_supplement_name: Optional[str] = Field(
        default=None,
        description=(
            "When finding_kind == 'MISSING_SUPPLEMENT': the contract-given name "
            "of the supplement that was not emitted (e.g. 'X-Mass Gala Dinner — Italian Market')."
        ),
    )


class VerifierReport(BaseModel):
    hotel_name: str
    findings: List[VerifierFinding]


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def verify_hotel(
    client,
    file_block: Dict[str, Any],
    hotel: HotelExtraction,
    supplements_for_hotel: List[Supplement],
    *,
    file_name: str,
) -> VerifierReport:
    """One strict-schema LLM call. Returns the auditor's findings."""
    settings = get_settings()
    system_prompt = _load_prompt()
    payload = {
        "hotel_name": hotel.metadata.name,
        "metadata": hotel.metadata.model_dump(mode="json"),
        "rooms": [r.model_dump(mode="json") for r in hotel.rooms],
        "seasons": [s.model_dump(mode="json") for s in hotel.seasons],
        "meal_plans": [m.model_dump(mode="json") for m in hotel.meal_plans],
        "rates": [r.model_dump(mode="json") for r in hotel.rates],
        "child_policy": [b.model_dump(mode="json") for b in hotel.child_policy],
        "supplements": [s.model_dump(mode="json") for s in supplements_for_hotel],
    }
    user_text = (
        f"Source filename: {file_name}\n"
        f"Audit the extraction for hotel "
        f"{hotel.metadata.name!r} below. List EVERY missing supplement "
        f"row you can identify in the contract that's not in the JSON, "
        f"any rate-grid cells the extraction skipped, child age bands "
        f"that were dropped, and any value contradictions. Do NOT propose "
        f"fixes — just report. Return a VerifierReport per the schema.\n\n"
        f"CURRENT EXTRACTION:\n{json.dumps(payload, ensure_ascii=False, indent=1)}"
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
                    {"type": "input_text", "text": user_text},
                ],
            },
        ],
        text_format=VerifierReport,
    )
    report: Optional[VerifierReport] = response.output_parsed
    if report is None:
        raise RuntimeError(
            "Verifier returned no parseable output: "
            f"{(response.output_text or '')[:300]!r}"
        )
    return report


def collect_missing_supplement_names(report: VerifierReport) -> List[str]:
    """Return the verifier's suggested missing supplement names, deduped."""
    out: List[str] = []
    seen = set()
    for f in report.findings:
        if f.finding_kind != "MISSING_SUPPLEMENT":
            continue
        name = (f.missing_supplement_name or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out
