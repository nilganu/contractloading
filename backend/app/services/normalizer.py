"""Post-extraction normalization.

Responsibilities:
- Ensure every HotelRow has every dynamic child column key.
- Coerce numeric strings to numbers, blank strings to null.
- Reject prose in numeric fields — move the prose into Extraction Notes.
- Normalize currency, meal plan, rate type, status, and dates.
- Sort dynamic child columns: ageFrom, ageTo, childPosition order, label.
- Apply default values (supplier, country, currency, status, check-in/out).
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .moonstride_templates import days_to_moonstride

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

MEAL_PLAN_MAP = {
    "AI": "All Inclusive",
    "ALL INCLUSIVE": "All Inclusive",
    "HARD ALL INCLUSIVE": "All Inclusive",
    "SOFT ALL INCLUSIVE": "All Inclusive",
    "ULTRA AI": "Ultra All Inclusive",
    "ULTRA ALL INCLUSIVE": "Ultra All Inclusive",
    "BB": "Bed & Breakfast",
    "BED AND BREAKFAST": "Bed & Breakfast",
    "B&B": "Bed & Breakfast",
    "HB": "Half Board",
    "HALF BOARD": "Half Board",
    "FB": "Full Board",
    "FULL BOARD": "Full Board",
    "RO": "Room Only",
    "ROOM ONLY": "Room Only",
}

RATE_TYPE_MAP = {
    "PER PERSON PER NIGHT": "Per Person Per Night",
    "PER PERSON PER DAY": "Per Person Per Day",
    "PER ROOM PER NIGHT": "Per Room Per Night",
    "PER UNIT PER NIGHT": "Per Room Per Night",
    "RATES PER NIGHT PER PERSON": "Per Person Per Night",
}

PROSE_SENTINELS = {"", "N/A", "NA", "-", "INCLUDED", "FREE", "FOC", "NULL", "UNDEFINED", "NONE"}

# Note: "Days" is intentionally NOT here — it's a weekday-mask string
# ("0 to 6"), not a number, so it must skip numeric coercion.
NUMERIC_FIELDS = {
    "Latitude",
    "Longitude",
    "Min Adult",
    "Max Adult",
    "Max Pax",
    "Min Stay",
    "Booking Limit",
    "Release Period",
    "Add Charge Value",
    "Charge",
    "SGL",
    "DBL",
    "TPL",
    "QDP",
    "Extra Bed",
    "SUPP-HB-ADULT",
    "SUPP-HB-CHILD",
    "SUPP-AI-ADULT",
    "SUPP-AI-CHILD",
}

INTEGER_FIELDS = {
    "Min Adult",
    "Max Adult",
    "Max Pax",
    "Min Stay",
    "Booking Limit",
    "Release Period",
}

DATE_FIELDS = {"Start Date", "End Date"}


def _normalize_currency(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s in CURRENCY_MAP:
        return CURRENCY_MAP[s]
    for token, code in CURRENCY_MAP.items():
        if token in s:
            return code
    if len(s) == 3 and s.isalpha():
        return s
    return None


def _normalize_meal_plan(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s in MEAL_PLAN_MAP:
        return MEAL_PLAN_MAP[s]
    for k, v in MEAL_PLAN_MAP.items():
        if k in s:
            return v
    # already normalized?
    title = s.title()
    if title in MEAL_PLAN_MAP.values():
        return title
    return str(value)


def _normalize_rate_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s in RATE_TYPE_MAP:
        return RATE_TYPE_MAP[s]
    for k, v in RATE_TYPE_MAP.items():
        if k in s:
            return v
    title = str(value).strip()
    if title in RATE_TYPE_MAP.values():
        return title
    return None


def _normalize_status(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if "request" in s:
        return "On Request"
    if "open" in s or "live" in s or "available" in s:
        return "Open"
    return None


def _normalize_iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})$", s)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def _coerce_number(
    value: Any,
    *,
    integer: bool,
    value_type: Optional[str] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """Return (coerced_value, prose_to_move) — second value is the original
    string when it was prose that we refused to coerce.

    `value_type` lets the caller signal that the field is a percentage rather
    than a currency amount. For discount_percentage fields:
      - "FREE" / "FOC" / "INCLUDED" → 100 (means 100% discount, fully free)
      - "N/A" / blank / "-" → None (NEVER 0)
    For amount/unknown fields:
      - "FREE" / "FOC" / "INCLUDED" → 0 (safest cost interpretation)
      - "N/A" / blank / "-" → None
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return (1 if value else 0) if not integer else (1 if value else 0), None
    if isinstance(value, (int, float)):
        return (int(value) if integer else float(value)), None
    s = str(value).strip()
    if not s:
        return None, None
    upper = s.upper()
    # Strip a trailing percent sign so "-50%" / "50%" parse as 50
    if upper.endswith("%"):
        try:
            cleaned = upper.rstrip("%").lstrip("-").strip()
            return float(cleaned), None
        except ValueError:
            pass
    if upper in PROSE_SENTINELS:
        if upper in {"", "N/A", "NA", "-", "NULL", "UNDEFINED", "NONE"}:
            return None, None
        if upper in {"FREE", "FOC", "INCLUDED"}:
            if value_type == "discount_percentage":
                return 100, None
            return 0, None
    # plain number?
    try:
        cleaned = s.replace(",", "").replace(" ", "")
        if integer:
            return int(float(cleaned)), None
        return float(cleaned), None
    except ValueError:
        return None, s


def _days_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        from datetime import date

        sy, sm, sd = (int(x) for x in start.split("-"))
        ey, em, ed = (int(x) for x in end.split("-"))
        delta = (date(ey, em, ed) - date(sy, sm, sd)).days + 1
        return delta if delta > 0 else None
    except Exception:  # noqa: BLE001
        return None


CHILD_POSITION_ORDER = {"first_child": 0, "second_child": 1, "third_child": 2, None: 3}


def _convert_discount_to_amount(result: Dict[str, Any]) -> None:
    """Convert percentage-style child + Extra Bed values to currency amounts.

    Three conversions in one pass:

    1. discount_percentage columns
       value = the % OFF the adult rate (free=100, -50%=50, n/a=null).
       amount = DBL × (1 - pct/100).

    2. percentage_of_adult columns
       value = the fraction or percent the child PAYS of the adult rate.
       - If value is in [0, 5]: treat as a decimal multiplier
         (0.5 = pays 50%, 1 = pays 100%, 0.75 = pays 75%).
         amount = DBL × value.
       - If value is in (5, 100]: treat as a percentage
         (50 = pays 50%, 75 = pays 75%, 100 = pays 100%).
         amount = DBL × value/100.

    3. Extra Bed flagged as percentage (`_extraBedIsPercentage=True`)
       Same as case 1 (discount_percentage).

    After conversion, the column's valueType is upgraded to "amount" and
    the label suffix is dropped so the export header is the clean
    CHD<pos>(<from>-<to>) form.

    Null values stay null (room doesn't accept that child position).
    DBL null -> no conversion; the original numeric value is preserved.
    Out-of-range pct -> no conversion.
    """
    cols = (result.get("dynamicColumns") or {}).get("childColumns") or []

    # Auto-detect: any CHD column whose ALL non-null values across rows
    # are in [0, 1] is almost certainly a percentage_of_adult multiplier,
    # regardless of how the LLM column-map classified it. Reclassify so
    # the conversion below picks it up.
    rows = result.get("hotelRows") or []
    for c in cols:
        if c.get("valueType") in ("amount", "unknown", None):
            key = c.get("key")
            if not isinstance(key, str):
                continue
            values = []
            for r in rows:
                v = (r.get("dynamicChildValues") or {}).get(key)
                if v is None:
                    continue
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    pass
            if values and all(0 <= v <= 1 for v in values):
                c["valueType"] = "percentage_of_adult"

    discount_keys = [
        c["key"]
        for c in cols
        if c.get("valueType") == "discount_percentage"
        and isinstance(c.get("key"), str)
    ]
    pct_of_adult_keys = [
        c["key"]
        for c in cols
        if c.get("valueType") == "percentage_of_adult"
        and isinstance(c.get("key"), str)
    ]

    for row in result.get("hotelRows") or []:
        dbl = row.get("DBL")
        if not isinstance(dbl, (int, float)):
            continue
        dyn = row.get("dynamicChildValues") or {}

        # discount_percentage -> DBL × (1 - pct/100)
        for k in discount_keys:
            v = dyn.get(k)
            if v is None:
                continue
            try:
                pct = float(v)
            except (TypeError, ValueError):
                continue
            if pct < 0 or pct > 100:
                continue
            dyn[k] = round(float(dbl) * (1 - pct / 100), 2)

        # percentage_of_adult -> DBL × multiplier (with auto-detect of
        # fraction vs percent form).
        for k in pct_of_adult_keys:
            v = dyn.get(k)
            if v is None:
                continue
            try:
                pv = float(v)
            except (TypeError, ValueError):
                continue
            if pv < 0:
                continue
            if pv <= 5:
                # Fraction form: 0.5 = 50%, 1 = 100%, 0.75 = 75%.
                dyn[k] = round(float(dbl) * pv, 2)
            elif pv <= 100:
                # Percent form: 50 = 50%, 75 = 75%, 100 = 100%.
                dyn[k] = round(float(dbl) * pv / 100.0, 2)
            # else: already an amount, leave alone.

        row["dynamicChildValues"] = dyn

        # Extra Bed: if the direct extractor flagged it as a percentage,
        # convert here. The flag is removed afterwards so downstream code
        # sees a plain numeric amount.
        if row.pop("_extraBedIsPercentage", False):
            eb = row.get("Extra Bed")
            if eb is not None:
                try:
                    pct = float(eb)
                    if 0 <= pct <= 100:
                        row["Extra Bed"] = round(float(dbl) * (1 - pct / 100), 2)
                except (TypeError, ValueError):
                    pass

    for c in cols:
        vt = c.get("valueType")
        if vt in ("discount_percentage", "percentage_of_adult"):
            c["valueType"] = "amount"
            c["label"] = c.get("key") or c.get("label")


def _sort_dynamic_columns(cols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(c: Dict[str, Any]) -> Tuple[Any, ...]:
        af = c.get("ageFrom")
        at = c.get("ageTo")
        cp = CHILD_POSITION_ORDER.get(c.get("childPosition"), 4)
        return (
            af if af is not None else float("inf"),
            at if at is not None else float("inf"),
            cp,
            c.get("label") or c.get("key") or "",
        )

    return sorted(cols, key=key)


def _ensure_dynamic_values(row: Dict[str, Any], keys: List[str]) -> None:
    dynamic = dict(row.get("dynamicChildValues") or {})
    for k in keys:
        if k not in dynamic:
            dynamic[k] = None
    # drop unknown keys not in the canonical column set
    dynamic = {k: dynamic[k] for k in keys if k in dynamic}
    row["dynamicChildValues"] = dynamic


def _apply_defaults(row: Dict[str, Any], options: Dict[str, Any]) -> None:
    mapping = {
        "Supplier": "supplierDefault",
        "Country Code ": "countryDefault",
        "City / Area": "cityAreaDefault",
        "Currency": "currencyDefault",
        "Customer Price Currency": "currencyDefault",
        "Check-In": "checkInDefault",
        "Check-Out": "checkOutDefault",
        "Status": "statusDefault",
    }
    for field, opt_key in mapping.items():
        if (row.get(field) in (None, "")) and options.get(opt_key):
            row[field] = options[opt_key]


def normalize_result(
    result: Dict[str, Any],
    options: Dict[str, Any],
    source_file: str,
) -> Dict[str, Any]:
    """Normalize a NormalizedExtractionResult-shaped dict in place and return it."""
    if not isinstance(result, dict):
        raise ValueError("Extraction result must be a JSON object")

    # workbookSummary
    summary = result.get("workbookSummary") or {}
    summary.setdefault("sourceFile", source_file)
    summary.setdefault("inputFormat", "unknown")
    summary.setdefault("sheetsOrPagesProcessed", [])
    summary.setdefault("indexSheets", [])
    summary.setdefault("hotelSheets", [])
    summary.setdefault("ignoredSheetsOrPages", [])
    summary.setdefault("overallConfidence", 0.5)
    result["workbookSummary"] = summary

    # dynamic columns
    dyn = result.get("dynamicColumns") or {}
    cols = dyn.get("childColumns") or []
    cols = _sort_dynamic_columns(cols)

    # de-dup keys
    seen: Dict[str, Dict[str, Any]] = {}
    for c in cols:
        key = c.get("key") or c.get("label") or "CHD(Unknown)"
        c["key"] = key
        c.setdefault("label", key)
        c.setdefault("ageFrom", None)
        c.setdefault("ageTo", None)
        c.setdefault("ageLabel", None)
        c.setdefault("childPosition", None)
        c.setdefault("valueType", "unknown")
        seen.setdefault(key, c)
    cols = list(seen.values())
    cols = _sort_dynamic_columns(cols)

    # Annotate the label so the export header makes the unit explicit:
    # discount_percentage columns get a " %" suffix, amount columns stay as-is.
    # The label ALWAYS starts from the KEY (CHD<pos>(<from>-<to>)) so the
    # exported header stays in Moonstride's CHD(...) format — model-provided
    # free-form labels like "0,1 - 11,99" are not used for the header.
    for c in cols:
        base = c.get("key") or c.get("label") or ""
        if c.get("valueType") == "discount_percentage":
            c["label"] = f"{base} (% off)"
        elif c.get("valueType") == "percentage_of_adult":
            c["label"] = f"{base} (% of adult)"
        else:
            c["label"] = base

    result["dynamicColumns"] = {"childColumns": cols}
    dynamic_keys = [c["key"] for c in cols]

    # Hotel rows
    hotel_rows = list(result.get("hotelRows") or [])
    extraction_notes: List[Dict[str, Any]] = list(result.get("extractionNotes") or [])

    for row in hotel_rows:
        row.setdefault("id", f"row_{uuid.uuid4().hex[:8]}")
        row.setdefault("sourceSheetOrPage", "—")

        _ensure_dynamic_values(row, dynamic_keys)
        _apply_defaults(row, options)

        # currency / meal plan / rate type / status / dates
        row["Currency"] = _normalize_currency(row.get("Currency")) or row.get("Currency")
        row["Customer Price Currency"] = (
            _normalize_currency(row.get("Customer Price Currency"))
            or row.get("Customer Price Currency")
        )
        if row.get("Meal Plan"):
            row["Meal Plan"] = _normalize_meal_plan(row["Meal Plan"]) or row["Meal Plan"]
        if row.get("Rate Type"):
            row["Rate Type"] = _normalize_rate_type(row["Rate Type"]) or row["Rate Type"]
        if row.get("Status"):
            row["Status"] = _normalize_status(row["Status"]) or row["Status"]

        # dates
        for d_field in DATE_FIELDS:
            row[d_field] = _normalize_iso_date(row.get(d_field))

        # Auto-correct end-date-year typos: contracts occasionally type
        # the wrong year on the End Date (eg "2026-04-10 -> 2025-05-03"
        # where the End year should also be 2026). If End < Start AND
        # bumping End's year up by 1 makes it land in [Start, Start+1y],
        # apply the bump with a warning. This catches the common source
        # typo without ever destroying a legitimately-bounded period.
        sd_v = row.get("Start Date")
        ed_v = row.get("End Date")
        if sd_v and ed_v and sd_v > ed_v:
            try:
                sy, sm, sday = (int(x) for x in sd_v.split("-"))
                ey, em, eday = (int(x) for x in ed_v.split("-"))
                if ey < sy:
                    bumped = f"{sy:04d}-{em:02d}-{eday:02d}"
                    if bumped > sd_v:
                        row["End Date"] = bumped
                        warns = list(row.get("_warnings") or [])
                        warns.append(
                            f"End Date year auto-corrected from {ed_v} -> {bumped} "
                            f"(source contract typo)"
                        )
                        row["_warnings"] = warns
            except (ValueError, TypeError):
                pass

        # numeric coercion
        moved_warnings: List[str] = list(row.get("_warnings") or [])
        for field in NUMERIC_FIELDS:
            v = row.get(field)
            coerced, prose = _coerce_number(v, integer=field in INTEGER_FIELDS)
            if prose is not None:
                # move prose to extraction notes
                extraction_notes.append(
                    {
                        "id": f"note_{uuid.uuid4().hex[:8]}",
                        "Source File": source_file,
                        "Page": row.get("sourceSheetOrPage", "—"),
                        "Category": "Rate anomaly",
                        "Note": (
                            f"Field '{field}' on row {row.get('id')} contained non-numeric "
                            f"text and was moved here for review: '{prose}'"
                        ),
                        "_sourceRefs": list(row.get("_sourceRefs") or []),
                        "_confidence": 0.4,
                        "hotelName": row.get("Hotel Name"),
                        "linkedHotelRowId": row.get("id"),
                    }
                )
                moved_warnings.append(f"{field}: '{prose}' moved to Extraction Notes")
                row[field] = None
            else:
                row[field] = coerced

        # dynamic numeric coercion — context-aware so "FREE" maps to 100 for
        # discount_percentage columns and 0 for amount columns, and "N/A"
        # always maps to null (never 0).
        col_value_types = {c["key"]: c.get("valueType") for c in cols}
        dynamic = row["dynamicChildValues"]
        for k, v in list(dynamic.items()):
            coerced, prose = _coerce_number(
                v,
                integer=False,
                value_type=col_value_types.get(k),
            )
            if prose is not None:
                extraction_notes.append(
                    {
                        "id": f"note_{uuid.uuid4().hex[:8]}",
                        "Source File": source_file,
                        "Page": row.get("sourceSheetOrPage", "—"),
                        "Category": "Child policy",
                        "Note": (
                            f"Child column '{k}' on row {row.get('id')} contained "
                            f"non-numeric text and was moved here for review: '{prose}'"
                        ),
                        "_sourceRefs": list(row.get("_sourceRefs") or []),
                        "_confidence": 0.4,
                        "hotelName": row.get("Hotel Name"),
                        "linkedHotelRowId": row.get("id"),
                    }
                )
                moved_warnings.append(f"{k}: '{prose}' moved to Extraction Notes")
                dynamic[k] = None
            else:
                dynamic[k] = coerced

        # Days is a Moonstride weekday mask "1234567" (1=Mon..7=Sun, all
        # week = "1234567"). Default to all-week when missing. Do NOT
        # recompute from the date range; the inclusive night-count is NOT
        # what Moonstride wants. Legacy 0..6 comma masks and bare ints
        # (night-counts) are normalized to the Moonstride format.
        if row.get("Days") in (None, "") or isinstance(row.get("Days"), (int, float)):
            row["Days"] = "1234567"
        else:
            row["Days"] = days_to_moonstride(row.get("Days"))

        row["_warnings"] = moved_warnings
        row.setdefault("_sourceRefs", [])
        row.setdefault("_confidence", 0.5)
        row.setdefault("_childPolicyDetails", [])
        row.setdefault("_cellMeta", {})
        row.setdefault("_reviewState", "auto")

    # Notes
    for note in extraction_notes:
        note.setdefault("id", f"note_{uuid.uuid4().hex[:8]}")
        note.setdefault("Source File", source_file)
        note.setdefault("Page", "—")
        note.setdefault("Category", "Other")
        note.setdefault("Note", "")
        note.setdefault("_sourceRefs", [])
        note.setdefault("_confidence", 0.5)
        note.setdefault("hotelName", None)
        note.setdefault("linkedHotelRowId", None)

    result["hotelRows"] = hotel_rows
    result["extractionNotes"] = extraction_notes
    result.setdefault("hotels", [])
    result.setdefault("validationIssues", [])

    # Final pass: convert any discount-percentage child columns to actual
    # currency amounts using each row's DBL. Exported child columns are
    # then real money, not percentages.
    _convert_discount_to_amount(result)

    return result
