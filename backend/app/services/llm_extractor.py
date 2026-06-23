"""OpenAI extraction wrapper.

Primary path: OpenAI Chat Completions with response_format=json_object.
- Single user message containing trimmed IR + options + schema instructions.
- Repair retry on invalid JSON.
- Per-document raw_excerpt and tables are truncated to keep the prompt
  within model context limits while still preserving meaningful structure.

Fallback path: when no OPENAI_API_KEY is configured (eg local CI without
secrets), the deterministic stub extractor is used so the rest of the
pipeline is still exercisable.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_settings
from .stub_extractor import stub_extract

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "hotel-contract-extraction-v1.txt"
)


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _strip_codefence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _safe_json_loads(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        return json.loads(_strip_codefence(text)), None
    except json.JSONDecodeError as e:
        return None, f"{e.msg} at line {e.lineno} col {e.colno}"


# Per-document caps. Format-aware: Excel cells are tightly packed and we
# can afford the full sheet; PDFs benefit from trimming verbose prose.
_MAX_DOCS = 40
_RAW_EXCERPT_CAPS = {
    "xlsx": 60_000,  # full sheet — Excel is dense, fits in gpt-4o context
    "xls":  60_000,
    "pdf":  10_000,
    "docx": 12_000,
    "image": 8_000,
    "mixed": 12_000,
    "unknown": 8_000,
}
_TABLE_ROW_CAPS = {
    "xlsx": 1_000,
    "xls":  1_000,
    "pdf":   120,
    "docx":  200,
    "image": 120,
    "mixed": 200,
    "unknown": 200,
}
_TABLE_COL_CAPS = {
    "xlsx": 100,
    "xls":  100,
    "pdf":   40,
    "docx":  40,
    "image": 40,
    "mixed": 40,
    "unknown": 40,
}


def _format_caps(input_format: str) -> tuple[int, int, int]:
    fmt = (input_format or "unknown").lower()
    return (
        _RAW_EXCERPT_CAPS.get(fmt, _RAW_EXCERPT_CAPS["unknown"]),
        _TABLE_ROW_CAPS.get(fmt, _TABLE_ROW_CAPS["unknown"]),
        _TABLE_COL_CAPS.get(fmt, _TABLE_COL_CAPS["unknown"]),
    )


def _trim_table(table: Dict[str, Any], *, max_rows: int, max_cols: int) -> Dict[str, Any]:
    """Cap rows / columns. Rows may be list-shaped (pdfplumber) or
    dict-shaped (vision-style structured tables)."""
    rows = table.get("rows") or []
    trimmed: List[Any] = []
    for r in rows[:max_rows]:
        if isinstance(r, dict):
            items = list(r.items())[:max_cols]
            trimmed.append(dict(items))
        elif isinstance(r, (list, tuple)):
            trimmed.append(list(r[:max_cols]))
        else:
            trimmed.append(r)
    return {**table, "rows": trimmed}


def _trim_ir_for_prompt(ir: Dict[str, Any]) -> Dict[str, Any]:
    ir = copy.deepcopy(ir)
    input_format = ir.get("input_format") or "unknown"
    raw_cap, row_cap, col_cap = _format_caps(input_format)

    docs = ir.get("documents") or []
    # Always include index/reference sheets first (they're informative and small),
    # then hotel_contract sheets, then everything else.
    def _doc_sort_key(d: Dict[str, Any]) -> int:
        cls = d.get("classification") or ""
        if cls == "hotel_contract":
            return 0
        if cls == "index_reference":
            return 1
        return 2

    docs.sort(key=_doc_sort_key)
    docs = docs[:_MAX_DOCS]
    for d in docs:
        if d.get("raw_excerpt") and len(d["raw_excerpt"]) > raw_cap:
            d["raw_excerpt"] = (
                d["raw_excerpt"][:raw_cap] + "\n...[truncated]"
            )
        if d.get("tables"):
            d["tables"] = [
                _trim_table(t, max_rows=row_cap, max_cols=col_cap)
                for t in d["tables"]
            ]
    ir["documents"] = docs
    return ir


def _build_user_message(ir: Dict[str, Any], options: Dict[str, Any]) -> str:
    payload = {"options": options, "ir": _trim_ir_for_prompt(ir)}
    return (
        "Extract the hotel contract data from the following intermediate "
        "representation. Output a SINGLE JSON object matching the schema in "
        "the system prompt. Do not include any text outside the JSON.\n\n"
        f"<INPUT>\n{json.dumps(payload, ensure_ascii=False, default=str)}\n</INPUT>"
    )


def _call_openai(messages: List[Dict[str, str]]) -> Tuple[str, Dict[str, Any]]:
    settings = get_settings()
    from openai import OpenAI

    # Tight timeout + zero retries so a wrong/missing model id fails fast
    # instead of stalling the chunker for minutes.
    client = OpenAI(api_key=settings.openai_api_key, timeout=60.0, max_retries=0)
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    usage = response.usage.model_dump() if response.usage else {}
    return content, {
        "model": settings.openai_model,
        "usage": usage,
        "id": response.id,
    }


def run_extraction(
    ir: Dict[str, Any],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the LLM extraction step.

    Returns dict with: result, raw_request, raw_response, model, usage,
    warnings, errors.
    """
    settings = get_settings()
    request_id = str(uuid.uuid4())

    if not settings.openai_api_key:
        result = stub_extract(ir, options)
        return {
            "result": result,
            "raw_request": {"mode": "stub", "id": request_id},
            "raw_response": json.dumps(result, ensure_ascii=False, default=str),
            "model": "stub",
            "usage": {},
            "warnings": [
                "OpenAI API key not configured — used deterministic stub extractor."
            ],
            "errors": [],
        }

    system_prompt = _load_prompt()
    user_message = _build_user_message(ir, options)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        raw_text, meta = _call_openai(messages)
    except Exception as e:  # noqa: BLE001
        logger.exception("OpenAI call failed")
        return {
            "result": None,
            "raw_request": {"id": request_id, "messages": messages},
            "raw_response": "",
            "model": settings.openai_model,
            "usage": {},
            "warnings": [],
            "errors": [f"OpenAI call failed: {type(e).__name__}: {e}"],
        }

    parsed, err = _safe_json_loads(raw_text)
    if parsed is None:
        repair_messages = list(messages) + [
            {"role": "assistant", "content": raw_text},
            {
                "role": "user",
                "content": (
                    f"Your previous response was not valid JSON ({err}). "
                    "Return ONLY a valid JSON object matching the schema."
                ),
            },
        ]
        try:
            raw_text_2, meta_2 = _call_openai(repair_messages)
        except Exception as e:  # noqa: BLE001
            return {
                "result": None,
                "raw_request": {
                    "id": request_id,
                    "messages": messages,
                    "repair_messages": repair_messages,
                },
                "raw_response": raw_text,
                "model": meta["model"],
                "usage": meta.get("usage", {}),
                "warnings": [],
                "errors": [f"OpenAI repair call failed: {type(e).__name__}: {e}"],
            }
        parsed_2, err_2 = _safe_json_loads(raw_text_2)
        if parsed_2 is None:
            return {
                "result": None,
                "raw_request": {
                    "id": request_id,
                    "messages": messages,
                    "repair_messages": repair_messages,
                },
                "raw_response": raw_text + "\n---REPAIR---\n" + raw_text_2,
                "model": meta_2["model"],
                "usage": meta_2.get("usage", {}),
                "warnings": [],
                "errors": [f"LLM returned invalid JSON after repair: {err_2}"],
            }
        parsed = parsed_2
        meta = meta_2
        raw_text = raw_text + "\n---REPAIR---\n" + raw_text_2

    return {
        "result": parsed,
        "raw_request": {"id": request_id, "messages": messages},
        "raw_response": raw_text,
        "model": meta["model"],
        "usage": meta.get("usage", {}),
        "warnings": [],
        "errors": [],
    }
