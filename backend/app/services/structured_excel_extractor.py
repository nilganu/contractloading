"""Deterministic Excel rate-block extractor.

Strategy:
1. For each hotel-contract sheet, ask the LLM ONLY for a "column map":
   - which columns are FROM/TO/release/base/SGL/TPL/CHD/upgrade/meal/note
   - which row range each rate block covers
   - hotel metadata + occupancy table + special-offer text
2. Iterate the grid in Python. For every data row in every block we emit
   exactly (1 base + N upgrades) Hotel rows. No LLM laziness possible.
3. Merge across sheets, apply normalizer (which converts
   percentage_of_adult → amount using DBL).

This guarantees full coverage of every (date row × room column) cell.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_settings
from .parsers.excel import sheet_text_preview

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "excel-column-map-v1.txt"
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


def _call_column_map_llm(sheet_grid_text: str) -> Dict[str, Any]:
    """One OpenAI call per sheet that returns the column map JSON."""
    settings = get_settings()
    if not settings.openai_api_key:
        return {
            "result": None,
            "raw": "",
            "error": "OpenAI API key not configured.",
            "model": "stub",
            "usage": {},
        }

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=60.0, max_retries=0)
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _load_prompt()},
                {
                    "role": "user",
                    "content": (
                        "Identify rate blocks and classify every column in the "
                        "sheet rendered below. Return ONLY the JSON object.\n\n"
                        + sheet_grid_text
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as e:  # noqa: BLE001
        return {
            "result": None,
            "raw": "",
            "error": f"{type(e).__name__}: {e}",
            "model": settings.openai_model,
            "usage": {},
        }
    raw = response.choices[0].message.content or ""
    parsed, err = _safe_json_loads(raw)
    usage = response.usage.model_dump() if response.usage else {}
    return {
        "result": parsed,
        "raw": raw,
        "error": err,
        "model": settings.openai_model,
        "usage": usage,
    }


def _cell_at(rows: List[List[Dict[str, Any]]], r_idx: int, c_idx: Optional[int]) -> Any:
    if c_idx is None or r_idx < 0 or r_idx >= len(rows):
        return None
    row = rows[r_idx]
    if c_idx < 0 or c_idx >= len(row):
        return None
    return row[c_idx].get("value")


def _to_iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            pass
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


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    upper = s.upper()
    if upper in {"N/A", "NA", "-", "FREE", "FOC", "NULL", "INCLUDED"}:
        return None
    try:
        cleaned = s.replace(",", ".").replace("€", "").replace("$", "").strip()
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1].strip()
        return float(cleaned)
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    if f is None:
        return None
    return int(f)


def _days_inclusive(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        from datetime import date

        sy, sm, sd = (int(x) for x in start.split("-"))
        ey, em, ed = (int(x) for x in end.split("-"))
        return (date(ey, em, ed) - date(sy, sm, sd)).days + 1
    except Exception:  # noqa: BLE001
        return None


def _compute_sgl(base: float, supp: Optional[float]) -> Optional[float]:
    """SGL = base + supplement.
    Value < 1: treat as a multiplier (e.g. 0.7 means +70%, so SGL = base × 1.7).
    Value ≥ 1: treat as a flat currency amount added to the base.
    """
    if supp is None:
        return None
    if 0 < supp < 1:
        return round(base * (1 + supp), 2)
    return round(base + supp, 2)


def _compute_tpl(base: float, reduct: Optional[float]) -> Optional[float]:
    """TPL = base − reduction.
    Value < 1: treat as a multiplier (e.g. 0.3 means −30%, TPL = base × 0.7).
    Value ≥ 1: treat as a flat currency reduction subtracted from the base.
    """
    if reduct is None:
        return None
    if 0 < reduct < 1:
        return round(base * (1 - reduct), 2)
    return round(base - reduct, 2)


def _compute_qdp(base: float, reduct: Optional[float]) -> Optional[float]:
    if reduct is None:
        return None
    if 0 < reduct < 1:
        return round(base * (1 - reduct), 2)
    return round(base - reduct, 2)


def _child_col_key(child_col: Dict[str, Any]) -> str:
    af = child_col.get("age_from")
    at = child_col.get("age_to")
    pos = child_col.get("position")
    pref = ""
    if pos == "first_child":
        pref = "CHD1"
    elif pos == "second_child":
        pref = "CHD2"
    elif pos == "third_child":
        pref = "CHD3"
    else:
        pref = "CHD"
    af_str = (f"{af:g}" if isinstance(af, (int, float)) else "?")
    at_str = (f"{at:g}" if isinstance(at, (int, float)) else "?")
    return f"{pref}({af_str}-{at_str})"


def _apply_meta(row: Dict[str, Any], meta: Dict[str, Any], options: Dict[str, Any]) -> None:
    """Fill hotel-level fields from the column map's hotel_meta or the user
    upload defaults, preferring meta values."""
    def _pick(meta_key: str, opt_key: str) -> Optional[Any]:
        v = meta.get(meta_key)
        if v in (None, ""):
            return options.get(opt_key)
        return v

    row["Hotel Name"] = meta.get("name") or row.get("Hotel Name")
    row["Supplier"] = _pick("supplier", "supplierDefault")
    row["Country Code "] = _pick("country_code", "countryDefault")
    row["State / Province / Region"] = meta.get("state_or_region")
    row["City / Area"] = _pick("city_or_area", "cityAreaDefault")
    row["Currency"] = _pick("currency", "currencyDefault")
    row["Customer Price Currency"] = row["Currency"]
    row["Rate Type"] = meta.get("rate_type")
    # Star Rating: meta might have a numeric or "4*/4-star" format
    if meta.get("stars"):
        row["Star Rating"] = str(meta["stars"])


def _meal_plan_from_treatment(treatment: Optional[str]) -> Optional[str]:
    if not treatment:
        return None
    t = treatment.lower()
    if "all inclusive" in t or t.strip() in {"ai", "hai", "sai"}:
        return "All Inclusive"
    if "half board" in t or t.strip() == "hb":
        return "Half Board"
    if "full board" in t or t.strip() == "fb":
        return "Full Board"
    if "bed" in t and "breakfast" in t:
        return "Bed & Breakfast"
    if t.strip() in {"bb", "b&b"}:
        return "Bed & Breakfast"
    if "room only" in t or t.strip() == "ro":
        return "Room Only"
    return treatment.strip().title()


_ROOM_NAME_NOISE = {
    "room", "rooms", "type", "view", "couple", "only", "side",
    "the", "a", "an", "&",
}
_ROOM_NAME_SYNONYMS = {
    # short-form → canonical tokens
    "sup": "superior",
    "dlx": "deluxe",
    "jun": "junior",
    "fam": "family",
    "gv": "gardenview",
    "sv": "seaview",
    "ssv": "seasideview",
    "bf": "beachfront",
    "pv": "poolview",
}


def _room_tokens(name: str) -> set[str]:
    """Tokenize a room name into a set of normalized tokens for matching.
    "SUPERIOR GV" and "SUP GV" should both produce {'superior', 'gardenview'}.
    """
    if not name:
        return set()
    s = name.strip().lower()
    # split on whitespace and common separators
    raw = re.split(r"[\s/_\-\(\)\.\,]+", s)
    out: set[str] = set()
    for t in raw:
        if not t:
            continue
        if t in _ROOM_NAME_NOISE:
            continue
        canon = _ROOM_NAME_SYNONYMS.get(t, t)
        out.add(canon)
    return out


def _apply_occupancy(row: Dict[str, Any], room_name: str, occupancy_table: List[Dict[str, Any]]) -> None:
    """Match room_name to an occupancy table entry via:
    1. exact (case-insensitive) match
    2. substring match in either direction
    3. token-set overlap >= 1 with the canonical synonym map (so
       "SUPERIOR GV" matches "SUP GV", "Jun Suite SV" matches "JUNIOR SUITE", etc.)
    """
    if not room_name:
        return
    rn = room_name.strip().lower()
    rn_tokens = _room_tokens(room_name)

    best_match = None
    best_score = 0

    for entry in occupancy_table or []:
        en = (entry.get("room_name") or "").strip().lower()
        if not en:
            continue
        # 1. exact
        if en == rn:
            best_match = entry
            best_score = 999
            break
        # 2. substring
        score = 0
        if en in rn or rn in en:
            score = 100
        # 3. token-set overlap
        en_tokens = _room_tokens(en)
        if rn_tokens and en_tokens:
            overlap = rn_tokens & en_tokens
            if overlap:
                # weight by how unique the overlap is
                score = max(score, 10 * len(overlap))
        if score > best_score:
            best_score = score
            best_match = entry

    if not best_match:
        return

    min_a = _to_int(best_match.get("min_adult"))
    max_a = _to_int(best_match.get("max_adult"))
    max_p = _to_int(best_match.get("max_pax"))
    max_c = _to_int(best_match.get("max_child"))
    if min_a is not None and row.get("Min Adult") in (None, ""):
        row["Min Adult"] = min_a
    if max_a is not None and row.get("Max Adult") in (None, ""):
        row["Max Adult"] = max_a
    if max_p is not None and row.get("Max Pax") in (None, ""):
        row["Max Pax"] = max_p

    # If the occupancy table says this room cannot accept children at all
    # (Max Children = 0), zero out every dynamic CHD value on the row.
    # Couple-only suites and swim-up rooms commonly have Max Children = 0
    # while the rate-table block still shows a child policy that applies
    # to OTHER rooms in the same block.
    if max_c is not None and max_c <= 0:
        dyn = row.get("dynamicChildValues") or {}
        for k in list(dyn.keys()):
            dyn[k] = None
        row["dynamicChildValues"] = dyn
        warns = list(row.get("_warnings") or [])
        warns.append(
            f"Child rates cleared because occupancy table says Max Children = 0 "
            f"for room '{room_name}'."
        )
        row["_warnings"] = warns


def _narrow_child_age_from_overrides(
    child_cols: List[Dict[str, Any]],
    overrides: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """If a separate "Children Policy" detailed table specified narrower
    (more accurate) age ranges for a child position, replace the inline
    rate-table age band with the narrower one.

    Heuristic: pick the override that:
      - matches the inline column's child_position (eg first_child)
      - has an age range FULLY CONTAINED inside the inline column's range
        AND is strictly narrower (smaller span)
    Multiple matches: pick the narrowest.

    Returns a NEW list of column descriptors with updated age_from/age_to.
    """
    if not overrides:
        return list(child_cols)
    out: List[Dict[str, Any]] = []
    for cc in child_cols:
        af = cc.get("age_from")
        at = cc.get("age_to")
        pos = cc.get("position")
        best: Optional[Tuple[float, float]] = None
        if isinstance(af, (int, float)) and isinstance(at, (int, float)) and pos:
            for ov in overrides:
                ov_af = ov.get(f"{pos}_age_from")
                ov_at = ov.get(f"{pos}_age_to")
                # Fallback: look for explicit position+ages on the override
                if ov_af is None or ov_at is None:
                    # The LLM may emit overrides as a flat list with
                    # `position` and `age_from`/`age_to` directly.
                    if ov.get("position") == pos:
                        ov_af = ov.get("age_from")
                        ov_at = ov.get("age_to")
                if not isinstance(ov_af, (int, float)) or not isinstance(ov_at, (int, float)):
                    continue
                # Contained in original range?
                if ov_af >= af and ov_at <= at and (ov_at - ov_af) < (at - af):
                    span = ov_at - ov_af
                    if best is None or span < (best[1] - best[0]):
                        best = (ov_af, ov_at)
        if best is not None:
            new_cc = dict(cc)
            new_cc["age_from"] = best[0]
            new_cc["age_to"] = best[1]
            out.append(new_cc)
        else:
            out.append(cc)
    return out


def _expand_block(
    rows: List[List[Dict[str, Any]]],
    block: Dict[str, Any],
    meta: Dict[str, Any],
    occupancy_table: List[Dict[str, Any]],
    options: Dict[str, Any],
    sheet_name: str,
    source_file: str,
    child_policy_overrides: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (hotel_rows, child_columns) for a single rate block."""
    cols = block.get("columns") or {}
    title = block.get("title") or "Contract"
    first_row = int(block.get("first_data_row_idx", 0))
    last_row = int(block.get("last_data_row_idx", first_row))
    meal_plan = _meal_plan_from_treatment(meta.get("basic_treatment"))

    # Build child column descriptors (returned for the workbook-level merge).
    child_cols = cols.get("child_cols") or []
    # If the sheet has a detailed Children Policy table that gives narrower
    # age ranges (eg "2-5.99" instead of "0-5.99"), use those.
    child_cols = _narrow_child_age_from_overrides(child_cols, child_policy_overrides or [])
    child_keys: List[Tuple[str, Dict[str, Any]]] = []
    for cc in child_cols:
        key = _child_col_key(cc)
        child_keys.append((key, cc))

    upgrade_cols = cols.get("upgrade_cols") or []
    meal_upgrade_cols = cols.get("meal_upgrade_cols") or []
    note_cols = cols.get("note_cols") or []

    base_col = cols.get("base_room")
    base_label = cols.get("base_room_label") or "Standard"

    hotel_rows: List[Dict[str, Any]] = []

    for r_idx in range(first_row, last_row + 1):
        if r_idx < 0 or r_idx >= len(rows):
            continue

        date_from = _to_iso_date(_cell_at(rows, r_idx, cols.get("date_from")))
        date_to = _to_iso_date(_cell_at(rows, r_idx, cols.get("date_to")))
        base_val = _to_float(_cell_at(rows, r_idx, base_col))

        if base_val is None or not date_from or not date_to:
            continue  # skip empty/blank lines

        sgl_supp = _to_float(_cell_at(rows, r_idx, cols.get("sgl_supp")))
        tpl_reduct = _to_float(_cell_at(rows, r_idx, cols.get("tpl_reduct")))
        qdp_reduct = _to_float(_cell_at(rows, r_idx, cols.get("qdp_reduct")))
        extra_bed = _to_float(_cell_at(rows, r_idx, cols.get("extra_bed")))
        release = _to_int(_cell_at(rows, r_idx, cols.get("release")))
        # Moonstride 'Days' is a weekday mask "1234567" (1=Mon..7=Sun), not a
        # night count. Default to all seven days. If the contract restricts a
        # rate to specific weekdays (eg weekend-only), that override goes here.
        days = "1234567"

        # Per-row child values
        child_values_for_row: Dict[str, Optional[float]] = {}
        for key, cc in child_keys:
            v = _to_float(_cell_at(rows, r_idx, cc.get("col_idx")))
            child_values_for_row[key] = v

        # Meal-plan supplements (SUPP-AI-ADULT etc.)
        meal_supps: Dict[str, Optional[float]] = {}
        for mc in meal_upgrade_cols:
            supp_field = mc.get("supp_field") or "SUPP-AI-ADULT"
            v = _to_float(_cell_at(rows, r_idx, mc.get("col_idx")))
            if v is not None:
                meal_supps[supp_field] = v

        # Common row template
        def _make_row(room_name: str, dbl_value: float, confidence: float = 0.9) -> Dict[str, Any]:
            row: Dict[str, Any] = {
                "id": f"row_{uuid.uuid4().hex[:8]}",
                "sourceSheetOrPage": f"Sheet:{sheet_name}",
                "Hotel Name": None,
                "Room Name": room_name,
                "Start Date": date_from,
                "End Date": date_to,
                "Days": days,
                "Release Period": release,
                "Rate Plan": title,
                "Meal Plan": meal_plan,
                "Status": options.get("statusDefault") or "Open",
                "Check-In": options.get("checkInDefault"),
                "Check-Out": options.get("checkOutDefault"),
                "DBL": dbl_value,
                "SGL": _compute_sgl(dbl_value, sgl_supp),
                "TPL": _compute_tpl(dbl_value, tpl_reduct),
                "QDP": _compute_qdp(dbl_value, qdp_reduct),
                "Extra Bed": extra_bed,
                "dynamicChildValues": dict(child_values_for_row),
                "_sourceRefs": [f"{source_file} | {sheet_name}!Row {r_idx + 1}"],
                "_confidence": confidence,
                "_warnings": [],
                "_cellMeta": {},
                "_reviewState": "auto",
            }
            for supp_field, supp_v in meal_supps.items():
                row[supp_field] = supp_v
            _apply_meta(row, meta, options)
            _apply_occupancy(row, room_name, occupancy_table)
            return row

        # Base-room row
        hotel_rows.append(_make_row(base_label, base_val, confidence=0.92))

        # Upgrade-room rows
        for uc in upgrade_cols:
            label = uc.get("label") or "Upgrade"
            supp = _to_float(_cell_at(rows, r_idx, uc.get("col_idx")))
            if supp is None:
                continue
            hotel_rows.append(_make_row(label, round(base_val + supp, 2), confidence=0.8))

    # Build the dynamicColumns descriptor for this block
    dynamic_columns: List[Dict[str, Any]] = []
    for key, cc in child_keys:
        dynamic_columns.append(
            {
                "key": key,
                "label": key,
                "ageFrom": cc.get("age_from"),
                "ageTo": cc.get("age_to"),
                "ageLabel": cc.get("age_label"),
                "childPosition": cc.get("position"),
                "valueType": cc.get("value_type") or "unknown",
            }
        )

    return hotel_rows, dynamic_columns


def extract_excel_structured(
    parsed_excel: Dict[str, Any],
    options: Dict[str, Any],
    *,
    max_workers: int = 6,
    progress_cb=None,
) -> Dict[str, Any]:
    """Run the column-map + Python-expansion pipeline across every hotel
    sheet in a parsed Excel workbook.

    Returns the same envelope shape as `run_extraction_chunked`:
      { result, raw_request, raw_response, model, usage, warnings, errors, chunks }
    so the existing job pipeline can consume it unchanged.
    """
    source_file = parsed_excel.get("source_file") or "unknown"
    sheets = parsed_excel.get("sheets") or []
    # Identify hotel-contract sheets (skip index/reference / support_notes).
    from .classifier import classify_excel_sheet

    targets: List[Dict[str, Any]] = []
    index_sheets: List[str] = []
    ignored: List[Dict[str, Any]] = []
    for sheet in sheets:
        kind, details = classify_excel_sheet(sheet)
        if kind == "hotel_contract":
            targets.append(sheet)
        elif kind == "index_reference":
            index_sheets.append(sheet["name"])
        else:
            ignored.append({"name": sheet["name"], "reason": kind})

    if not targets:
        return {
            "result": None,
            "raw_request": {"mode": "structured_excel"},
            "raw_response": "",
            "model": "none",
            "usage": {},
            "warnings": ["No hotel_contract sheets detected."],
            "errors": [],
            "chunks": [],
        }

    raw_chunks: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []
    usage_total: Dict[str, int] = {}
    model_used = "unknown"
    chunk_diagnostics: List[Dict[str, Any]] = []

    all_hotel_rows: List[Dict[str, Any]] = []
    all_dynamic_columns: List[Dict[str, Any]] = []
    all_notes: List[Dict[str, Any]] = []
    all_hotels: List[Dict[str, Any]] = []

    def _process_sheet(idx: int, sheet: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        grid_text = sheet_text_preview(sheet)
        out = _call_column_map_llm(grid_text)
        return idx, {"sheet": sheet, "out": out, "grid_text": grid_text}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_process_sheet, i, s): i for i, s in enumerate(targets)}
        done = 0
        for fut in as_completed(futures):
            idx, payload = fut.result()
            sheet = payload["sheet"]
            out = payload["out"]
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, len(targets))
                except Exception:  # noqa: BLE001
                    pass

            sheet_name = sheet["name"]
            raw_chunks.append(f"=== sheet {sheet_name} ===\n{out.get('raw', '')}")
            for k, v in (out.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    usage_total[k] = usage_total.get(k, 0) + v
            if out.get("model"):
                model_used = out["model"]

            col_map = out.get("result")
            if not col_map:
                warnings.append(
                    f"Sheet {sheet_name!r}: column-map call failed ({out.get('error')})."
                )
                errors.extend(filter(None, [out.get("error")]))
                chunk_diagnostics.append(
                    {
                        "chunk_index": idx,
                        "sheet": sheet_name,
                        "errors": [out.get("error")] if out.get("error") else [],
                        "model": out.get("model"),
                        "usage": out.get("usage") or {},
                    }
                )
                continue

            meta = col_map.get("hotel_meta") or {}
            occupancy_table = col_map.get("occupancy_table") or []
            child_policy_overrides = col_map.get("child_policy_overrides") or []
            blocks = col_map.get("blocks") or []
            rows = sheet.get("rows") or []

            hotel_row_count_for_sheet = 0
            for block in blocks:
                block_rows, block_dynamic_cols = _expand_block(
                    rows, block, meta, occupancy_table, options, sheet_name, source_file,
                    child_policy_overrides=child_policy_overrides,
                )
                all_hotel_rows.extend(block_rows)
                all_dynamic_columns.extend(block_dynamic_cols)
                hotel_row_count_for_sheet += len(block_rows)

            # Hotel-level entry
            if meta.get("name"):
                all_hotels.append(
                    {
                        "hotelName": meta.get("name"),
                        "sourceSheetOrPage": f"Sheet:{sheet_name}",
                        "metadata": meta,
                        "rateBlocks": [],
                        "roomTypes": occupancy_table,
                        "childPolicies": col_map.get("child_policy_overrides") or [],
                    }
                )

            # Convert special-offer / cancellation / etc to extraction notes
            for txt in col_map.get("special_offers_text") or []:
                if not txt:
                    continue
                all_notes.append(
                    _mk_note(source_file, sheet_name, "Special offer", txt, meta.get("name"))
                )
            for txt in col_map.get("gala_text") or []:
                if not txt:
                    continue
                all_notes.append(
                    _mk_note(source_file, sheet_name, "Gala dinner", txt, meta.get("name"))
                )
            if col_map.get("cancellation_text"):
                all_notes.append(
                    _mk_note(
                        source_file, sheet_name, "Cancellation",
                        col_map["cancellation_text"], meta.get("name"),
                    )
                )
            if col_map.get("early_booking_text"):
                all_notes.append(
                    _mk_note(
                        source_file, sheet_name, "Special offer",
                        col_map["early_booking_text"], meta.get("name"),
                    )
                )
            if col_map.get("minimum_stay_text"):
                all_notes.append(
                    _mk_note(
                        source_file, sheet_name, "Minimum stay",
                        col_map["minimum_stay_text"], meta.get("name"),
                    )
                )

            chunk_diagnostics.append(
                {
                    "chunk_index": idx,
                    "sheet": sheet_name,
                    "blocks": len(blocks),
                    "row_count": hotel_row_count_for_sheet,
                    "errors": [],
                    "model": out.get("model"),
                    "usage": out.get("usage") or {},
                }
            )

    # Dedup dynamic columns by key
    dedup: Dict[str, Dict[str, Any]] = {}
    for col in all_dynamic_columns:
        key = col.get("key")
        if key and key not in dedup:
            dedup[key] = col

    result: Dict[str, Any] = {
        "workbookSummary": {
            "sourceFile": source_file,
            "inputFormat": "xlsx",
            "sheetsOrPagesProcessed": [s["name"] for s in sheets],
            "indexSheets": index_sheets,
            "hotelSheets": [s["name"] for s in targets],
            "ignoredSheetsOrPages": ignored,
            "overallConfidence": 0.85,
        },
        "dynamicColumns": {"childColumns": list(dedup.values())},
        "hotels": all_hotels,
        "hotelRows": all_hotel_rows,
        "extractionNotes": all_notes,
        "validationIssues": [],
    }

    return {
        "result": result,
        "raw_request": {"mode": "structured_excel"},
        "raw_response": "\n\n".join(raw_chunks),
        "model": model_used,
        "usage": usage_total,
        "warnings": warnings,
        "errors": errors,
        "chunks": chunk_diagnostics,
    }


def _mk_note(
    source_file: str, sheet_name: str, category: str, text: str, hotel_name: Optional[str]
) -> Dict[str, Any]:
    return {
        "id": f"note_{uuid.uuid4().hex[:8]}",
        "Source File": source_file,
        "Page": f"Sheet:{sheet_name}",
        "Category": category,
        "Note": text,
        "_sourceRefs": [],
        "_confidence": 0.7,
        "hotelName": hotel_name,
        "linkedHotelRowId": None,
    }
