"""Direct vision-to-JSON extraction for PDFs and images.

Instead of the two-hop "vision → text/tables → LLM → JSON" pipeline, this
extractor renders each PDF page (or accepts an image directly) and sends it to
gpt-4o with the FULL extraction schema baked into the prompt. The model
returns the Moonstride row JSON in one call. This avoids the lossy text
intermediate that has caused row collapsing and period mis-alignment on
visually complex rate tables.

Per-page calls are parallelized and merged using the same merge logic as
llm_chunker.merge_chunk_results so the rest of the pipeline (normalize,
validate, export) is unchanged.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_settings
from .llm_chunker import merge_chunk_results

logger = logging.getLogger(__name__)

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "direct-vision-extraction-v1.txt"
)
SKELETON_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "direct-vision-skeleton-v1.txt"
)
FILL_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "direct-vision-fill-v1.txt"
)


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_skeleton_prompt() -> str:
    return SKELETON_PROMPT_PATH.read_text(encoding="utf-8")


def _load_fill_prompt() -> str:
    return FILL_PROMPT_PATH.read_text(encoding="utf-8")


def _strip_codefence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _safe_json_loads(text: str):
    try:
        return json.loads(_strip_codefence(text)), None
    except json.JSONDecodeError as e:
        return None, f"{e.msg} at line {e.lineno} col {e.colno}"


def _render_pdf_page_to_png(pdf_path: str | Path, page_number: int, *, resolution: int = 220) -> bytes:
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_number - 1]
        im = page.to_image(resolution=resolution)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


def _png_bytes_from_image_path(image_path: str | Path) -> bytes:
    return Path(image_path).read_bytes()


def _call_vision_for_extraction(
    png_bytes_list: List[bytes],
    *,
    system_prompt: str,
    user_context: str,
    page_labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One OpenAI vision call that accepts ONE OR MORE page images.

    Multi-image calls give the model the holistic view: page 1's rate table
    plus page 2's occupancy/cancellation context produces correct merged
    rows in one shot instead of two disjoint partial answers.
    """
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

    if not png_bytes_list:
        return {
            "result": None,
            "raw": "",
            "error": "No images to send.",
            "model": settings.openai_vision_model,
            "usage": {},
        }

    page_labels = page_labels or [f"Page {i + 1}" for i in range(len(png_bytes_list))]

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_context}]
    for i, png in enumerate(png_bytes_list):
        user_content.append({"type": "text", "text": f"--- {page_labels[i]} ---"})
        b64 = base64.b64encode(png).decode("ascii")
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            }
        )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    client = OpenAI(api_key=settings.openai_api_key, timeout=300.0, max_retries=2)
    try:
        response = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as e:  # noqa: BLE001
        return {
            "result": None,
            "raw": "",
            "error": f"{type(e).__name__}: {e}",
            "model": settings.openai_vision_model,
            "usage": {},
        }

    raw = response.choices[0].message.content or ""
    parsed, err = _safe_json_loads(raw)
    if parsed is None:
        # Repair retry
        try:
            response2 = client.chat.completions.create(
                model=settings.openai_vision_model,
                messages=messages
                + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was not valid JSON ({err}). "
                            "Return ONLY a valid JSON object matching the schema."
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw2 = response2.choices[0].message.content or ""
            parsed2, err2 = _safe_json_loads(raw2)
            if parsed2 is not None:
                usage = response2.usage.model_dump() if response2.usage else {}
                return {
                    "result": parsed2,
                    "raw": raw + "\n---REPAIR---\n" + raw2,
                    "error": None,
                    "model": settings.openai_vision_model,
                    "usage": usage,
                }
        except Exception as e:  # noqa: BLE001
            return {
                "result": None,
                "raw": raw,
                "error": f"Repair call failed: {type(e).__name__}: {e}",
                "model": settings.openai_vision_model,
                "usage": {},
            }
        return {
            "result": None,
            "raw": raw,
            "error": f"Invalid JSON after repair: {err}",
            "model": settings.openai_vision_model,
            "usage": {},
        }

    usage = response.usage.model_dump() if response.usage else {}
    return {
        "result": parsed,
        "raw": raw,
        "error": None,
        "model": settings.openai_vision_model,
        "usage": usage,
    }


def _page_result_to_normalized(
    page_result: Dict[str, Any],
    *,
    source_file: str,
    source_ref: str,
    page_id: str,
) -> Dict[str, Any]:
    """Wrap a single page's direct-extraction result into a partial
    NormalizedExtractionResult shape so the chunk merger can stitch them
    together. We give every row/note an id and propagate the source ref."""
    hotels_raw = page_result.get("pageHotels") or []
    rows_raw = page_result.get("hotelRows") or []
    notes_raw = page_result.get("extractionNotes") or []
    dyn_raw = page_result.get("dynamicChildColumns") or []

    hotels: List[Dict[str, Any]] = []
    for h in hotels_raw:
        hotels.append(
            {
                "hotelName": h.get("hotelName") or "Unknown Hotel",
                "sourceSheetOrPage": page_id,
                "metadata": h.get("metadata") or {},
                "rateBlocks": h.get("rateBlocks") or [],
                "roomTypes": h.get("roomTypes") or [],
                "childPolicies": h.get("childPolicies") or [],
            }
        )

    hotel_rows: List[Dict[str, Any]] = []
    for r in rows_raw:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or f"row_{uuid.uuid4().hex[:8]}"
        r["id"] = rid
        r["sourceSheetOrPage"] = page_id
        r.setdefault("_sourceRefs", [source_ref])
        r.setdefault("_confidence", 0.7)
        r.setdefault("_warnings", [])
        r.setdefault("dynamicChildValues", {})
        r.setdefault("_cellMeta", {})
        r.setdefault("_reviewState", "auto")
        hotel_rows.append(r)

    notes: List[Dict[str, Any]] = []
    for n in notes_raw:
        if not isinstance(n, dict):
            continue
        nid = n.get("id") or f"note_{uuid.uuid4().hex[:8]}"
        notes.append(
            {
                "id": nid,
                "Source File": source_file,
                "Page": page_id,
                "Category": n.get("Category") or "Other",
                "Note": n.get("Note") or "",
                "_sourceRefs": n.get("_sourceRefs") or [source_ref],
                "_confidence": n.get("_confidence") or 0.5,
                "hotelName": (hotels[0]["hotelName"] if hotels else None),
                "linkedHotelRowId": None,
            }
        )

    return {
        "workbookSummary": {
            "sourceFile": source_file,
            "inputFormat": "pdf",
            "sheetsOrPagesProcessed": [page_id],
            "indexSheets": [],
            "hotelSheets": [page_id],
            "ignoredSheetsOrPages": [],
            "overallConfidence": 0.7,
        },
        "dynamicColumns": {"childColumns": dyn_raw},
        "hotels": hotels,
        "hotelRows": hotel_rows,
        "extractionNotes": notes,
        "validationIssues": [],
    }


_DEFAULT_BATCH_PAGES = 4  # max pages per single vision call
_PRICED_FIELDS = ("SGL", "DBL", "TPL", "QDP", "Extra Bed")


def _row_has_any_price(row: Dict[str, Any]) -> bool:
    for f in _PRICED_FIELDS:
        v = row.get(f)
        if v is not None and v != "":
            return True
    dyn = row.get("dynamicChildValues") or {}
    for v in dyn.values():
        if v is not None:
            return True
    return False


def _filter_skeleton_rows(
    normalized: Dict[str, Any], *, source_file: str
) -> Dict[str, Any]:
    """Drop rows that have no Hotel Name AND no price values — these are
    layout artifacts that vision sometimes emits from occupancy/min-stay
    tables. Replace them with a single Extraction Note so the data isn't
    lost silently."""
    rows = normalized.get("hotelRows") or []
    keep: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for r in rows:
        hotel_name = (r.get("Hotel Name") or "").strip()
        if hotel_name or _row_has_any_price(r):
            keep.append(r)
        else:
            dropped.append(r)
    if dropped:
        normalized["hotelRows"] = keep
        normalized.setdefault("extractionNotes", []).append(
            {
                "id": f"note_{uuid.uuid4().hex[:8]}",
                "Source File": source_file,
                "Page": ",".join(sorted({d.get("sourceSheetOrPage", "—") for d in dropped})),
                "Category": "Source ambiguity",
                "Note": (
                    f"{len(dropped)} candidate row(s) were dropped because they had "
                    "neither a Hotel Name nor any rate values. These were likely "
                    "occupancy / min-stay artifacts. Review the source preview if "
                    "you expect rates from those rows."
                ),
                "_sourceRefs": [],
                "_confidence": 0.2,
                "hotelName": None,
                "linkedHotelRowId": None,
            }
        )
    return normalized


def _batch_pages(pages: List[int], size: int) -> List[List[int]]:
    return [pages[i : i + size] for i in range(0, len(pages), size)]


def _process_batch_two_call(
    pdf_path: Path,
    batch: List[int],
    resolution: int,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """Two-call strategy:
       Call A — extract structural skeleton (rooms, periods, meals, child positions).
       Call B — feed skeleton back and demand exactly rooms × periods × meals
                rows with prices.
    Returns the same {result, raw, error, model, usage, batch} envelope as
    the single-call path.
    """
    try:
        png_list = [
            _render_pdf_page_to_png(pdf_path, p, resolution=resolution) for p in batch
        ]
    except Exception as e:  # noqa: BLE001
        return {
            "batch": batch,
            "result": None,
            "raw": "",
            "error": f"render failed: {type(e).__name__}: {e}",
            "model": "render-error",
            "usage": {},
        }

    labels = [f"Page {p}" for p in batch]

    # Call A: skeleton
    skel_user = (
        "Identify the SKELETON of the rate matrix on this contract page "
        "image. Do not produce rate rows — only describe rooms, periods, "
        "boards and child-policy positions."
    )
    skel_out = _call_vision_for_extraction(
        png_list,
        system_prompt=_load_skeleton_prompt(),
        user_context=skel_user,
        page_labels=labels,
    )
    if skel_out.get("error") or not skel_out.get("result"):
        return {
            "batch": batch,
            "result": None,
            "raw": "[skeleton]\n" + (skel_out.get("raw") or ""),
            "error": (skel_out.get("error") or "skeleton call returned no result"),
            "model": skel_out.get("model") or "unknown",
            "usage": skel_out.get("usage") or {},
        }

    skeleton = skel_out["result"]
    rooms = skeleton.get("roomTypes") or []
    periods = skeleton.get("periods") or []
    meals = skeleton.get("mealPlans") or []
    layout_pattern = skeleton.get("layoutPattern") or "unknown"
    # period_column layouts are per-room-per-night with a single meal plan
    # ("Room Only" implicit). Expected count is rooms × periods only.
    if layout_pattern == "period_column":
        expected = max(len(rooms) * len(periods), 0)
    else:
        expected = max(len(rooms) * len(periods) * max(len(meals), 1), 0)

    # Build a broadcast dict of hotel-level fields from the skeleton. We
    # apply this defensively after the fill call so missing hotel-level
    # fields are never blank when the skeleton found them.
    addr = skeleton.get("hotelAddress") or {}
    skeleton_broadcast: Dict[str, Any] = {
        "Hotel Name": skeleton.get("hotelName"),
        "Supplier": skeleton.get("supplier"),
        "Address Line 1": addr.get("addressLine1"),
        "Country Code ": addr.get("countryCode"),
        "State / Province / Region": addr.get("stateOrRegion"),
        "City / Area": addr.get("cityOrArea"),
        "Postal Code": addr.get("postalCode"),
        "Phone Number": addr.get("phone"),
        "Email Address": addr.get("email"),
        "Hotel Website": addr.get("website"),
        "Currency": skeleton.get("currency"),
        "Customer Price Currency": skeleton.get("currency"),
        "Rate Type": skeleton.get("rateType"),
    }
    # Per-room broadcast: Min/Max Adult, Max Pax
    room_broadcast_by_name: Dict[str, Dict[str, Any]] = {}
    for room in rooms:
        rname = room.get("name")
        if not rname:
            continue
        room_broadcast_by_name[rname] = {
            "Min Adult": room.get("minAdult"),
            "Max Adult": room.get("maxAdult"),
            "Max Pax": room.get("maxPax"),
        }

    # Per-room extra-bed literal (e.g. "-30%", "free", "n/a"). Used as a
    # defensive fill when the model forgets to populate "Extra Bed".
    extra_adult = skeleton.get("extraAdultPolicy") or {}
    extra_bed_literal_by_room: Dict[str, str] = {
        rname: (literal or "")
        for rname, literal in (extra_adult.get("perRoomLiteral") or {}).items()
    } if isinstance(extra_adult, dict) else {}

    # Call B: fill, with skeleton as a hard constraint
    template_hint = ""
    cached = options.get("supplierTemplate") if isinstance(options, dict) else None
    if cached:
        template_hint = (
            "\nSUPPLIER TEMPLATE (from previous successful extraction with "
            "this supplier — use as a strong hint for room names, currency, "
            "rate type, dynamic child columns; verify but DO NOT invent if "
            "the current contract differs):\n"
            + json.dumps(cached, ensure_ascii=False)
            + "\n"
        )

    defaults_line = (
        "Supplier default: "
        f"{options.get('supplierDefault') or 'unknown'}. Country code default: "
        f"{options.get('countryDefault') or 'unknown'}. City default: "
        f"{options.get('cityAreaDefault') or 'unknown'}. Currency default: "
        f"{options.get('currencyDefault') or 'unknown'}. Status default: "
        f"{options.get('statusDefault') or 'Open'}."
    )

    def _expansion_line(n_rooms: int) -> str:
        if layout_pattern == "period_column":
            return (
                f"Layout = period_column (per-room-per-night). Expected "
                f"hotelRows = rooms × periods = {n_rooms} × {len(periods)} "
                f"= {n_rooms * len(periods)}. For each (room, period) emit ONE "
                "row with the per-room price in DBL (and also TPL/QDP when "
                "maxPax permits)."
            )
        return (
            f"Expected number of hotelRows = rooms × periods × meals = "
            f"{n_rooms} × {len(periods)} × {max(len(meals), 1)} = "
            f"{n_rooms * len(periods) * max(len(meals), 1)}."
        )

    def _do_fill(skeleton_for_fill: Dict[str, Any], expansion_line: str) -> Dict[str, Any]:
        fill_user = (
            "Fill the rate matrix using the SKELETON below as a hard constraint. "
            f"{expansion_line}\n\n"
            f"{defaults_line}\n\n"
            f"SKELETON:\n{json.dumps(skeleton_for_fill, ensure_ascii=False)}\n"
            f"{template_hint}"
        )
        return _call_vision_for_extraction(
            png_list,
            system_prompt=_load_fill_prompt(),
            user_context=fill_user,
            page_labels=labels,
        )

    fill_out = _do_fill(skeleton, _expansion_line(len(rooms)))

    combined_usage: Dict[str, int] = {}

    def _accumulate_usage(usage: Optional[Dict[str, Any]]) -> None:
        for k, v in (usage or {}).items():
            if isinstance(v, (int, float)):
                combined_usage[k] = combined_usage.get(k, 0) + v

    _accumulate_usage(skel_out.get("usage"))
    _accumulate_usage(fill_out.get("usage"))
    raw_parts = ["[fill]\n" + (fill_out.get("raw") or "")]

    if fill_out.get("error") or not fill_out.get("result"):
        return {
            "batch": batch,
            "result": None,
            "raw": "[skeleton]\n" + (skel_out.get("raw") or "") + "\n" + "\n".join(raw_parts),
            "error": fill_out.get("error") or "fill call returned no result",
            "model": fill_out.get("model") or "unknown",
            "usage": combined_usage,
            "skeleton": skeleton,
        }

    result = fill_out["result"]
    all_rows: List[Dict[str, Any]] = [
        r for r in (result.get("hotelRows") or []) if isinstance(r, dict)
    ]

    # The fill call is often lazy on large grids — it returns the first room
    # only. Re-fill the rooms the skeleton listed but the fill omitted, in
    # small groups, until every room is covered (max 4 retries).
    room_names = [r.get("name") for r in rooms if r.get("name")]
    if room_names:
        for attempt in range(4):
            covered = {r.get("Room Name") for r in all_rows}
            missing = [
                r for r in rooms if r.get("name") and r.get("name") not in covered
            ]
            if not missing:
                break
            group = missing[:5]  # keep each retry small so the model finishes
            sub_skeleton = dict(skeleton)
            sub_skeleton["roomTypes"] = group
            retry_line = (
                f"ONLY emit rows for these {len(group)} room type(s) that are "
                f"still missing: {', '.join(m.get('name') for m in group)}. "
                + _expansion_line(len(group))
            )
            retry_out = _do_fill(sub_skeleton, retry_line)
            raw_parts.append(f"[fill retry {attempt + 1}]\n" + (retry_out.get("raw") or ""))
            _accumulate_usage(retry_out.get("usage"))
            if retry_out.get("error") or not retry_out.get("result"):
                break
            new_rows = [
                r for r in (retry_out["result"].get("hotelRows") or []) if isinstance(r, dict)
            ]
            if not new_rows:
                break
            all_rows.extend(new_rows)
            # Merge any new dynamic child columns the retry surfaced.
            for col in retry_out["result"].get("dynamicChildColumns") or []:
                existing_keys = {c.get("key") for c in result.get("dynamicChildColumns") or []}
                if col.get("key") not in existing_keys:
                    result.setdefault("dynamicChildColumns", []).append(col)

    result["hotelRows"] = all_rows
    combined_raw = "[skeleton]\n" + (skel_out.get("raw") or "") + "\n" + "\n".join(raw_parts)

    # Defensive broadcast: any row missing a hotel-level field that the
    # skeleton has gets it filled in. Same for per-room occupancy fields.
    for row in all_rows:
        if not isinstance(row, dict):
            continue
        for header, value in skeleton_broadcast.items():
            if value in (None, "") :
                continue
            if row.get(header) in (None, ""):
                row[header] = value
        rname = row.get("Room Name")
        rb = room_broadcast_by_name.get(rname) if rname else None
        if rb:
            for k, v in rb.items():
                if v in (None, "") :
                    continue
                if row.get(k) in (None, ""):
                    row[k] = v

        # Extra Bed: the skeleton's extraAdultPolicy.perRoomLiteral is the
        # source of truth. The fill call sometimes emits the raw percentage
        # ("30" for "-30%") instead of the computed amount, so we override
        # with the literal interpretation here and let the normalizer do
        # the math on each row using its own DBL.
        if rname and rname in extra_bed_literal_by_room:
            literal = extra_bed_literal_by_room[rname] or ""
            up = literal.strip().upper()
            if up in {"N/A", "NA", "-", ""}:
                row["Extra Bed"] = None
            elif up in {"FREE", "FOC", "INCLUDED"}:
                row["Extra Bed"] = 0
                row.setdefault("_cellMeta", {})["Extra Bed"] = {
                    "confidence": 0.85,
                    "sourceRef": "extraAdultPolicy.perRoomLiteral",
                }
            elif "%" in up:
                try:
                    pct = float(up.replace("%", "").lstrip("-").strip())
                    row["Extra Bed"] = pct
                    row["_extraBedIsPercentage"] = True
                    row.setdefault("_cellMeta", {})["Extra Bed"] = {
                        "confidence": 0.85,
                        "sourceRef": "extraAdultPolicy.perRoomLiteral",
                    }
                except ValueError:
                    pass
            else:
                # Bare amount in the literal (e.g. "25 EUR"). Use the
                # parsed number; the model's value is overridden so we
                # don't accept a stale guess.
                try:
                    import re as _re

                    m = _re.search(r"-?\d+(?:[.,]\d+)?", up)
                    if m:
                        row["Extra Bed"] = float(m.group(0).replace(",", "."))
                except Exception:  # noqa: BLE001
                    pass

    actual = len(result.get("hotelRows") or [])
    short_by = expected - actual

    # If the fill call still came up short of the expected count, add a soft
    # extraction note inside the result so it surfaces to reviewers.
    if expected > 0 and short_by > 0:
        result.setdefault("extractionNotes", []).append(
            {
                "Category": "Source ambiguity",
                "Note": (
                    f"Two-call extraction expected {expected} rows from the "
                    f"skeleton ({len(rooms)} rooms × {len(periods)} periods × "
                    f"{len(meals)} meal plans) but produced {actual}. "
                    f"{short_by} row(s) appear to be missing — check the source "
                    "preview and fill them in manually."
                ),
                "_confidence": 0.3,
            }
        )

    return {
        "batch": batch,
        "result": result,
        "raw": combined_raw,
        "error": None,
        "model": fill_out.get("model"),
        "usage": combined_usage,
        "skeleton": skeleton,
    }


def extract_pdf_directly(
    pdf_path: str | Path,
    *,
    pages: Optional[List[int]] = None,
    options: Optional[Dict[str, Any]] = None,
    max_workers: int = 2,
    resolution: int = 220,
    batch_size: int = _DEFAULT_BATCH_PAGES,
    use_two_call: bool = True,
    progress_cb=None,
) -> Dict[str, Any]:
    """Run direct vision extraction.

    Strategy:
    - For <= batch_size pages, send ALL pages in ONE multi-image vision call.
      The model sees the rate table together with the occupancy/cancellation
      pages and produces correctly merged rows.
    - For > batch_size pages, split into batches and process in parallel.
      Each batch is a single multi-image call. Results from each batch are
      merged using merge_chunk_results.

    `options` is the user upload options dict (supplier/currency defaults).
    """
    pdf_path = Path(pdf_path)
    source_file = pdf_path.name
    options = options or {}
    system_prompt = _load_prompt()

    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        all_page_numbers = list(range(1, len(pdf.pages) + 1))
    if pages is None:
        target_pages = all_page_numbers
    else:
        target_pages = [p for p in pages if p in all_page_numbers]
    if not target_pages:
        return {
            "result": None,
            "raw_response": "",
            "model": "none",
            "usage": {},
            "warnings": ["No pages requested for direct vision."],
            "errors": [],
            "pages": [],
        }

    user_context = (
        "Extract from these contract page image(s). The image(s) belong to the "
        "SAME contract — read them together and produce a single coherent "
        "result.\n\n"
        "Supplier default: "
        f"{options.get('supplierDefault') or 'unknown'}. Country code default: "
        f"{options.get('countryDefault') or 'unknown'}. City default: "
        f"{options.get('cityAreaDefault') or 'unknown'}. Currency default: "
        f"{options.get('currencyDefault') or 'unknown'}. Status default: "
        f"{options.get('statusDefault') or 'Open'}.\n"
        "Apply defaults only when the contract does not specify the field.\n\n"
        "IMPORTANT: Do NOT create skeleton rows from the occupancy or min-stay "
        "tables. Every Hotel row must have a Hotel Name AND at least one "
        "price field (SGL/DBL/TPL/QDP/Extra Bed) populated. If you cannot fill "
        "any price, write an extraction note instead of an empty row."
    )

    batches = _batch_pages(target_pages, batch_size)
    total = len(batches)
    done = 0

    def _process_batch(batch: List[int]) -> Dict[str, Any]:
        if use_two_call:
            return _process_batch_two_call(pdf_path, batch, resolution, options)
        try:
            png_list = [
                _render_pdf_page_to_png(pdf_path, p, resolution=resolution) for p in batch
            ]
        except Exception as e:  # noqa: BLE001
            return {
                "batch": batch,
                "result": None,
                "raw": "",
                "error": f"render failed: {type(e).__name__}: {e}",
                "model": "render-error",
                "usage": {},
            }
        labels = [f"Page {p}" for p in batch]
        out = _call_vision_for_extraction(
            png_list,
            system_prompt=system_prompt,
            user_context=user_context,
            page_labels=labels,
        )
        out["batch"] = batch
        return out

    per_batch_results: List[Dict[str, Any]] = []
    if total == 1:
        per_batch_results.append(_process_batch(batches[0]))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_process_batch, b): b for b in batches}
            for fut in as_completed(futures):
                out = fut.result()
                per_batch_results.append(out)
                done += 1
                if progress_cb:
                    try:
                        progress_cb(done, total)
                    except Exception:  # noqa: BLE001
                        pass

    raw_chunks: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []
    usage_total: Dict[str, int] = {}
    model_used = "unknown"

    chunk_results: List[Dict[str, Any]] = []
    for br in per_batch_results:
        batch = br["batch"]
        raw_chunks.append(
            f"=== batch pages {','.join(str(p) for p in batch)} ===\n{br.get('raw', '')}"
        )
        if br.get("error"):
            errors.append(
                f"Batch [{','.join(str(p) for p in batch)}]: {br['error']}"
            )
        if br.get("model"):
            model_used = br["model"]
        for k, v in (br.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                usage_total[k] = usage_total.get(k, 0) + v

        if not br.get("result"):
            continue

        # When all pages are in one batch we use "Page:N" if rows specify it,
        # else we synthesize an identifier covering the batch range.
        page_id = (
            f"Page:{batch[0]}"
            if len(batch) == 1
            else f"Pages:{batch[0]}-{batch[-1]}"
        )
        source_ref = (
            f"{source_file} | Page {batch[0]}"
            if len(batch) == 1
            else f"{source_file} | Pages {batch[0]}-{batch[-1]}"
        )
        chunk_results.append(
            _page_result_to_normalized(
                br["result"],
                source_file=source_file,
                source_ref=source_ref,
                page_id=page_id,
            )
        )

    if not chunk_results:
        return {
            "result": None,
            "raw_response": "\n\n".join(raw_chunks),
            "model": model_used,
            "usage": usage_total,
            "warnings": warnings,
            "errors": errors or ["Direct vision produced no result on any batch."],
            "pages": [
                {"page_number": p, "ok": False, "error": "no result"}
                for p in target_pages
            ],
        }

    merged = merge_chunk_results(chunk_results, source_file=source_file)
    merged = _filter_skeleton_rows(merged, source_file=source_file)

    failed_batches = [br for br in per_batch_results if not br.get("result")]
    if failed_batches:
        merged.setdefault("extractionNotes", []).append(
            {
                "id": f"note_{uuid.uuid4().hex[:8]}",
                "Source File": source_file,
                "Page": "—",
                "Category": "Source ambiguity",
                "Note": (
                    f"Direct vision extraction failed on {len(failed_batches)} "
                    "batch(es). Review those pages manually in Source Preview."
                ),
                "_sourceRefs": [],
                "_confidence": 0.2,
                "hotelName": None,
                "linkedHotelRowId": None,
            }
        )

    return {
        "result": merged,
        "raw_response": "\n\n".join(raw_chunks),
        "model": model_used,
        "usage": usage_total,
        "warnings": warnings,
        "errors": errors,
        "pages": [
            {
                "page_number": p,
                "ok": any(
                    p in br["batch"] and br.get("result") for br in per_batch_results
                ),
                "error": next(
                    (br.get("error") for br in per_batch_results if p in br["batch"] and br.get("error")),
                    None,
                ),
            }
            for p in target_pages
        ],
    }


def extract_image_directly(
    image_path: str | Path,
    *,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Single-image direct extraction. Same shape as extract_pdf_directly."""
    image_path = Path(image_path)
    source_file = image_path.name
    options = options or {}
    system_prompt = _load_prompt()
    user_context = (
        "Extract from this single contract image. Supplier default: "
        f"{options.get('supplierDefault') or 'unknown'}. Currency default: "
        f"{options.get('currencyDefault') or 'unknown'}."
    )
    png = _png_bytes_from_image_path(image_path)
    out = _call_vision_for_extraction(
        [png], system_prompt=system_prompt, user_context=user_context, page_labels=[source_file]
    )
    if out.get("error") or not out.get("result"):
        return {
            "result": None,
            "raw_response": out.get("raw") or "",
            "model": out.get("model") or "unknown",
            "usage": out.get("usage") or {},
            "warnings": [],
            "errors": [out.get("error") or "No result"],
            "pages": [{"page_number": 1, "ok": False, "error": out.get("error")}],
        }
    page_id = "Image:0"
    source_ref = f"{source_file} | full image"
    normalized = _page_result_to_normalized(
        out["result"],
        source_file=source_file,
        source_ref=source_ref,
        page_id=page_id,
    )
    return {
        "result": normalized,
        "raw_response": out.get("raw") or "",
        "model": out.get("model") or "unknown",
        "usage": out.get("usage") or {},
        "warnings": [],
        "errors": [],
        "pages": [{"page_number": 1, "ok": True, "error": None}],
    }
