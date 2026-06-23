"""Deterministic stub extractor.

Used when no OpenAI API key is configured (local dev, tests, CI). It walks the
IR and produces a NormalizedExtractionResult-shaped dict that exercises every
downstream stage:
- workbookSummary populated from IR
- per-hotel-sheet (or single doc) hotel extractions
- shallow rate-block detection (look for a "FROM"/"TO" header row)
- one hotel row per detected date pair / room column
- a few representative extraction notes (taxes/cancellation/etc when keywords appear)
- a few dynamic child columns when CHD-like tokens appear in the text

It deliberately stays conservative: when in doubt it produces a note rather
than fabricating a numeric row.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple


DATE_PATTERNS = [
    # d/m/y or d-m-y or d.m.y, but separators must match on both sides
    # — so "2-11.99" (child band) is rejected
    re.compile(r"(?<!\d)(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})(?!\d)"),
    # ISO YYYY-MM-DD (optionally followed by Tnn:nn)
    re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"),
]


def _validate_ymd(y: int, mo: int, d: int) -> Optional[str]:
    from datetime import date as _date

    try:
        return _date(y, mo, d).isoformat()
    except (ValueError, TypeError):
        return None


def _to_iso_date(s: str) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return _validate_ymd(int(y), int(mo), int(d))
    m = re.match(r"^(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})$", s)
    if m:
        d, _sep, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return _validate_ymd(int(y), int(mo), int(d))
    return None


def _days_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        from datetime import date

        sy, sm, sd = (int(x) for x in start.split("-"))
        ey, em, ed = (int(x) for x in end.split("-"))
        return (date(ey, em, ed) - date(sy, sm, sd)).days + 1
    except Exception:  # noqa: BLE001
        return None


CURRENCY_MAP = {
    "EUR": "EUR",
    "€": "EUR",
    "EURO": "EUR",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "GBP": "GBP",
    "£": "GBP",
    "AED": "AED",
    "EGP": "EGP",
}


def _normalize_currency(s: str) -> Optional[str]:
    if not s:
        return None
    upper = s.strip().upper()
    if upper in CURRENCY_MAP:
        return CURRENCY_MAP[upper]
    for token, code in CURRENCY_MAP.items():
        if token in upper:
            return code
    return None


MEAL_PLAN_MAP = {
    "AI": "All Inclusive",
    "ALL INCLUSIVE": "All Inclusive",
    "HARD ALL INCLUSIVE": "All Inclusive",
    "SOFT ALL INCLUSIVE": "All Inclusive",
    "BB": "Bed & Breakfast",
    "BED AND BREAKFAST": "Bed & Breakfast",
    "HB": "Half Board",
    "HALF BOARD": "Half Board",
    "FB": "Full Board",
    "FULL BOARD": "Full Board",
    "RO": "Room Only",
    "ROOM ONLY": "Room Only",
}


def _normalize_meal_plan(s: str) -> Optional[str]:
    if not s:
        return None
    u = s.strip().upper()
    if u in MEAL_PLAN_MAP:
        return MEAL_PLAN_MAP[u]
    for k, v in MEAL_PLAN_MAP.items():
        if k in u:
            return v
    return None


CHD_AGE_REGEX = re.compile(
    r"CHD\s*\(?\s*(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*\)?",
    re.IGNORECASE,
)
CHD_LABEL_REGEX = re.compile(
    r"\b(CHD|CHILD|INFANT|BABY|TEEN|JUNIOR)\b",
    re.IGNORECASE,
)


def _detect_child_columns(text_blob: str) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for m in CHD_AGE_REGEX.finditer(text_blob):
        a = float(m.group(1))
        b = float(m.group(2))
        af = f"{a:g}"
        bf = f"{b:g}"
        key = f"CHD({af}-{bf})"
        seen.setdefault(
            key,
            {
                "key": key,
                "label": key,
                "ageFrom": a,
                "ageTo": b,
                "ageLabel": None,
                "childPosition": None,
                "valueType": "amount",
            },
        )
    return list(seen.values())


def _detect_currency(text_blob: str) -> Optional[str]:
    for token, code in CURRENCY_MAP.items():
        if token in text_blob.upper():
            return code
    return None


def _detect_meal_plan(text_blob: str) -> Optional[str]:
    u = text_blob.upper()
    for k, v in MEAL_PLAN_MAP.items():
        if re.search(rf"\b{re.escape(k)}\b", u):
            return v
    return None


def _flatten_tables(doc: Dict[str, Any]) -> str:
    parts: List[str] = []
    parts.append(doc.get("raw_excerpt") or "")
    for t in doc.get("tables") or []:
        for row in t.get("rows") or []:
            parts.append("\t".join((c or "") for c in row))
    return "\n".join(parts)


def _extract_dates_from_text(text: str) -> List[Tuple[str, str]]:
    matches: List[str] = []
    seen: set[int] = set()
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            if m.start() in seen:
                continue
            iso = _to_iso_date(m.group(0))
            if iso:
                matches.append(iso)
                seen.add(m.start())
    pairs: List[Tuple[str, str]] = []
    for i in range(0, len(matches) - 1, 2):
        pairs.append((matches[i], matches[i + 1]))
    return pairs


def _make_note(
    *,
    source_file: str,
    page: str,
    category: str,
    note_text: str,
    source_ref: Optional[str] = None,
    hotel_name: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": f"note_{uuid.uuid4().hex[:8]}",
        "Source File": source_file,
        "Page": page,
        "Category": category,
        "Note": note_text,
        "_sourceRefs": [source_ref] if source_ref else [],
        "_confidence": 0.4,
        "hotelName": hotel_name,
        "linkedHotelRowId": None,
    }


NOTES_TRIGGERS = [
    ("Taxes/service", re.compile(r"\b(tax(es)?|service charge|VAT|municipality)\b", re.IGNORECASE)),
    ("Cancellation", re.compile(r"\b(cancellation|no[- ]show|no show|early departure)\b", re.IGNORECASE)),
    ("Gala dinner", re.compile(r"\b(gala|christmas|new ?year)\b", re.IGNORECASE)),
    ("Special offer", re.compile(r"\b(special offer|promotion|free night|stay pay)\b", re.IGNORECASE)),
    ("Booking window", re.compile(r"\b(booking window|EBD|early booking)\b", re.IGNORECASE)),
    ("Minimum stay", re.compile(r"\b(min(imum)? stay|MLOS)\b", re.IGNORECASE)),
    ("Child policy", re.compile(r"\b(child policy|free of charge|FOC|infant)\b", re.IGNORECASE)),
]


def _hotel_name_from_doc(doc: Dict[str, Any]) -> Optional[str]:
    if doc.get("detected_hotel_name"):
        return doc["detected_hotel_name"]
    if doc.get("kind") == "excel_sheet":
        return doc.get("summary", {}).get("sheet_name")
    return None


def _row_template(
    *,
    row_id: str,
    source_sheet: str,
    hotel_name: str,
    start_date: Optional[str],
    end_date: Optional[str],
    currency: Optional[str],
    meal_plan: Optional[str],
    options: Dict[str, Any],
    dynamic_keys: List[str],
) -> Dict[str, Any]:
    days = _days_between(start_date, end_date)
    return {
        "id": row_id,
        "sourceSheetOrPage": source_sheet,
        "Hotel Name": hotel_name,
        "Supplier": options.get("supplierDefault"),
        "Star Rating": None,
        "Short Description": None,
        "Address Line 1": None,
        "Address Line 2": None,
        "Address Line 3": None,
        "Address Line 4": None,
        "Postal Code": None,
        "Country Code ": options.get("countryDefault"),
        "State / Province / Region": None,
        "City / Area": options.get("cityAreaDefault"),
        "Phone Number": None,
        "Email Address": None,
        "Hotel Website": None,
        "Latitude": None,
        "Longitude": None,
        "Check-In": options.get("checkInDefault"),
        "Check-Out": options.get("checkOutDefault"),
        "Currency": currency or options.get("currencyDefault"),
        "Rate Type": None,
        "Room Name": None,
        "Min Adult": None,
        "Max Adult": None,
        "Max Pax": None,
        "Season": None,
        "Start Date": start_date,
        "End Date": end_date,
        "Days": days,
        "Min Stay": None,
        "Rate Plan": None,
        "Meal Plan": meal_plan,
        "Status": options.get("statusDefault") or "Open",
        "Booking Limit": None,
        "Release Period": None,
        "Customer Price Currency": currency or options.get("currencyDefault"),
        "Add Charge Type": None,
        "Add Charge Value": None,
        "Charge": None,
        "SGL": None,
        "DBL": None,
        "TPL": None,
        "QDP": None,
        "Extra Bed": None,
        "dynamicChildValues": {k: None for k in dynamic_keys},
        "SUPP-HB-ADULT": None,
        "SUPP-HB-CHILD": None,
        "SUPP-AI-ADULT": None,
        "SUPP-AI-CHILD": None,
        "_childPolicyDetails": [],
        "_sourceRefs": [],
        "_confidence": 0.35,
        "_warnings": [
            "Stub extractor produced this row from coarse pattern matching — review every field."
        ],
    }


def stub_extract(ir: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    source_file = ir.get("source_file", "unknown")
    input_format = ir.get("input_format", "unknown")

    sheets_or_pages_processed: List[str] = []
    index_sheets: List[str] = []
    hotel_sheets: List[str] = []
    ignored: List[Dict[str, Any]] = []

    hotels: List[Dict[str, Any]] = []
    hotel_rows: List[Dict[str, Any]] = []
    notes: List[Dict[str, Any]] = []

    # First pass — collect all CHD-like tokens from every doc.
    combined_text = "\n".join(_flatten_tables(d) for d in ir.get("documents", []))
    dynamic_child_columns = _detect_child_columns(combined_text)

    if not dynamic_child_columns and re.search(CHD_LABEL_REGEX, combined_text):
        dynamic_child_columns = [
            {
                "key": "CHD(Child)",
                "label": "CHD(Child)",
                "ageFrom": None,
                "ageTo": None,
                "ageLabel": "Child",
                "childPosition": None,
                "valueType": "unknown",
            }
        ]

    dynamic_keys = [c["key"] for c in dynamic_child_columns]

    for doc in ir.get("documents", []):
        doc_id = doc.get("id") or doc.get("source_ref") or "doc"
        sheets_or_pages_processed.append(doc_id)
        classification = doc.get("classification") or "unknown"

        if classification == "index_reference":
            index_sheets.append(doc_id)
            continue
        if classification == "support_notes":
            ignored.append({"name": doc_id, "reason": "Support / policy sheet"})

        hotel_name = _hotel_name_from_doc(doc) or "Unknown Hotel"
        hotel_sheets.append(doc_id)

        doc_text = _flatten_tables(doc)
        currency = _detect_currency(doc_text)
        meal_plan = _detect_meal_plan(doc_text)

        # Trigger-based notes
        for cat, regex in NOTES_TRIGGERS:
            for m in regex.finditer(doc_text):
                snippet_start = max(0, m.start() - 40)
                snippet_end = min(len(doc_text), m.end() + 80)
                snippet = doc_text[snippet_start:snippet_end].strip().replace("\n", " ")
                notes.append(
                    _make_note(
                        source_file=source_file,
                        page=doc_id,
                        category=cat,
                        note_text=snippet,
                        source_ref=doc.get("source_ref"),
                        hotel_name=hotel_name,
                    )
                )
                break  # one note per trigger per doc

        date_pairs = _extract_dates_from_text(doc_text)
        if not date_pairs:
            notes.append(
                _make_note(
                    source_file=source_file,
                    page=doc_id,
                    category="Source ambiguity",
                    note_text=(
                        f"No date pairs detected on {doc_id}. Review manually to find rate periods."
                    ),
                    source_ref=doc.get("source_ref"),
                    hotel_name=hotel_name,
                )
            )

        rate_blocks: List[Dict[str, Any]] = []
        for idx, (start, end) in enumerate(date_pairs[:3]):
            rate_blocks.append(
                {
                    "title": f"Block {idx + 1}",
                    "ratePlan": "Contract",
                    "season": None,
                    "startDate": start,
                    "endDate": end,
                    "sourceRange": doc.get("source_ref"),
                }
            )

            row_id = f"row_{uuid.uuid4().hex[:8]}"
            row = _row_template(
                row_id=row_id,
                source_sheet=doc_id,
                hotel_name=hotel_name,
                start_date=start,
                end_date=end,
                currency=currency,
                meal_plan=meal_plan,
                options=options,
                dynamic_keys=dynamic_keys,
            )
            row["Rate Plan"] = "Contract"
            row["_sourceRefs"] = [doc.get("source_ref")] if doc.get("source_ref") else []
            hotel_rows.append(row)

        hotels.append(
            {
                "hotelName": hotel_name,
                "sourceSheetOrPage": doc_id,
                "metadata": {
                    "hotelName": hotel_name,
                    "supplier": options.get("supplierDefault"),
                    "countryCode": options.get("countryDefault"),
                    "cityOrArea": options.get("cityAreaDefault"),
                    "currency": currency or options.get("currencyDefault"),
                },
                "rateBlocks": rate_blocks,
                "roomTypes": [],
                "childPolicies": [],
            }
        )

    if not hotel_sheets:
        # nothing matched — keep result valid but flagged
        notes.append(
            {
                "id": f"note_{uuid.uuid4().hex[:8]}",
                "Source File": source_file,
                "Page": "—",
                "Category": "Source ambiguity",
                "Note": "Stub extractor could not identify any hotel contract sheets/pages.",
                "_sourceRefs": [],
                "_confidence": 0.2,
                "hotelName": None,
                "linkedHotelRowId": None,
            }
        )

    return {
        "workbookSummary": {
            "sourceFile": source_file,
            "inputFormat": input_format,
            "sheetsOrPagesProcessed": sheets_or_pages_processed,
            "indexSheets": index_sheets,
            "hotelSheets": hotel_sheets,
            "ignoredSheetsOrPages": ignored,
            "overallConfidence": 0.35,
        },
        "dynamicColumns": {"childColumns": dynamic_child_columns},
        "hotels": hotels,
        "hotelRows": hotel_rows,
        "extractionNotes": notes,
        "validationIssues": [],
    }
