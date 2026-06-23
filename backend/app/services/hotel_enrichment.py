"""GPT-based hotel metadata enrichment.

Fills missing hotel-level address / contact / geo fields using the LLM's
world knowledge when the contract did not supply them. Rules:

- Only EMPTY fields are filled — extracted contract values are never
  overwritten.
- Enrichment is per distinct hotel (one LLM call per hotel), applied to all
  of that hotel's rows.
- Known contract values (eg city, country) are passed as hints to anchor the
  lookup and reduce hallucination.
- Every filled value is flagged AI-inferred (row warning + low-confidence
  _cellMeta) so the human reviewer verifies it before export.
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_settings

logger = logging.getLogger(__name__)

# Internal HotelRow header key -> JSON key used in the LLM exchange.
# NOTE: "Country Code " carries a trailing space (matches the Moonstride alias).
_FIELD_TO_JSONKEY: "OrderedDict[str, str]" = OrderedDict(
    [
        ("Address Line 1", "addressLine1"),
        ("Address Line 2", "addressLine2"),
        ("Address Line 3", "addressLine3"),
        ("Address Line 4", "addressLine4"),
        ("Postal Code", "postalCode"),
        ("Country Code ", "countryCode"),
        ("State / Province / Region", "stateOrRegion"),
        ("City / Area", "cityOrArea"),
        ("Phone Number", "phoneNumber"),
        ("Email Address", "emailAddress"),
        ("Hotel Website", "hotelWebsite"),
        ("Latitude", "latitude"),
        ("Longitude", "longitude"),
    ]
)

_NUMERIC_JSONKEYS = {"latitude", "longitude"}

_SYSTEM_PROMPT = (
    "You are a hotel reference-data assistant. Given a hotel name and any known "
    "location hints, return the hotel's real-world address, contact, and geo "
    "details.\n"
    "CRITICAL ANTI-HALLUCINATION RULES:\n"
    "- Only return a value you are genuinely confident is correct for THIS "
    "specific hotel. If you are not sure, return null for that field. Never "
    "invent plausible-looking data.\n"
    "- Use the known hints to disambiguate; the answer must be consistent with "
    "them (same city/country).\n"
    "- countryCode: ISO 3166-1 alpha-2, uppercase (eg 'GR', 'EG').\n"
    "- latitude/longitude: decimal degrees as numbers (eg 40.123, -3.456). "
    "Only if you know the hotel's actual location.\n"
    "- phoneNumber: international format. emailAddress / hotelWebsite: only if "
    "publicly known.\n"
    "- Fill ONLY the keys listed in missingFields. Omit or null everything else.\n"
    'Return JSON: {"fields": {<missingFieldKey>: value-or-null, ...}}'
)


def _call_openai_json(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    settings = get_settings()
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=60.0, max_retries=0)
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _first_nonempty(rows: List[Dict[str, Any]], header: str) -> Any:
    for r in rows:
        v = r.get(header)
        if v not in (None, ""):
            return v
    return None


def _coerce(jsonkey: str, value: Any) -> Any:
    if value in (None, ""):
        return None
    if jsonkey in _NUMERIC_JSONKEYS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if jsonkey == "countryCode":
        s = str(value).strip().upper()
        return s[:2] if len(s) >= 2 else None
    return str(value).strip()


def _mark_ai_inferred(row: Dict[str, Any], header: str) -> None:
    label = header.strip()
    warnings = row.setdefault("_warnings", [])
    msg = f"'{label}' filled by GPT (AI-inferred) — verify before export"
    if msg not in warnings:
        warnings.append(msg)
    meta = row.setdefault("_cellMeta", {})
    meta[header] = {
        "confidence": 0.3,
        "sourceRef": "GPT metadata enrichment",
        "aiInferred": True,
    }


def _ask_gpt(
    hotel_name: str, known: Dict[str, Any], missing: List[str]
) -> Dict[str, Any]:
    payload = {"hotelName": hotel_name, "known": known, "missingFields": missing}
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    data = _call_openai_json(messages)
    fields = data.get("fields")
    return fields if isinstance(fields, dict) else (data if isinstance(data, dict) else {})


def enrich_result(result: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """Fill missing hotel address/contact/geo fields in place.

    ``force`` re-queries every field even when a hotel already has values.
    Returns a summary dict; ``result`` is mutated in place.
    """
    settings = get_settings()
    rows = result.get("hotelRows") or []

    by_hotel: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for r in rows:
        name = (r.get("Hotel Name") or "").strip()
        if not name:
            continue
        by_hotel.setdefault(name, []).append(r)

    if not settings.openai_api_key:
        return {
            "hotelsProcessed": 0,
            "fieldsFilled": 0,
            "skipped": True,
            "message": "OpenAI API key not configured — enrichment skipped.",
            "details": [],
        }

    hotels_processed = 0
    fields_filled = 0
    details: List[Dict[str, Any]] = []

    for hotel_name, hrows in by_hotel.items():
        known: Dict[str, Any] = {}
        for header, jsonkey in _FIELD_TO_JSONKEY.items():
            existing = _first_nonempty(hrows, header)
            if existing not in (None, ""):
                known[jsonkey] = existing
        missing = [
            jsonkey
            for _, jsonkey in _FIELD_TO_JSONKEY.items()
            if force or jsonkey not in known
        ]
        if not missing:
            continue

        try:
            filled = _ask_gpt(hotel_name, known, missing)
        except Exception as exc:  # noqa: BLE001 - log and continue other hotels
            logger.exception("Hotel enrichment failed for %r", hotel_name)
            details.append({"hotel": hotel_name, "error": f"{type(exc).__name__}: {exc}"})
            continue

        hotels_processed += 1
        hotel_filled: List[str] = []
        for header, jsonkey in _FIELD_TO_JSONKEY.items():
            if jsonkey not in missing:
                continue
            value = _coerce(jsonkey, filled.get(jsonkey))
            if value is None:
                continue
            applied = False
            for r in hrows:
                if r.get(header) in (None, ""):
                    r[header] = value
                    _mark_ai_inferred(r, header)
                    applied = True
            if applied:
                hotel_filled.append(header.strip())
                fields_filled += 1
        details.append({"hotel": hotel_name, "filled": hotel_filled})

    return {
        "hotelsProcessed": hotels_processed,
        "fieldsFilled": fields_filled,
        "skipped": False,
        "details": details,
    }
