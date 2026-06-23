"""Deterministic mapper: canonical ContractExtraction -> Moonstride rows.

All conditional rules live here, not in any prompt:

- ``Days = "1234567"`` default (unless restricted in canonical).
- ``Status = "Open"`` default.
- Per-position child columns (1st/2nd/3rd Child Price / Age Min / Age Max).
- Supplement ``Standard/Count/Index`` blanking rule
  (blank when ``calculation_method == "Standard"`` AND
  ``charge_type == "Per Person Per Night"``).
- Supplement ``FareType Name`` derivation
  (Standard mode → ``"Per Adult"`` etc.).
- Supplement forced values
  (``Display on customer Documentation`` / ``Display on Supplier Notification``
  always ``"Yes"``; ``Meal Plan`` / ``Required Supplement`` /
  ``Restricted Supplement`` always blank; ``Display As Separate Room``
  defaults to ``"No"``).
- Supplement dates formatted ``DD-MM-YYYY`` (template requirement);
  hotel rates remain ISO ``YYYY-MM-DD``.

All of these are unit-testable in isolation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .canonical import (
    ContractExtraction,
    HotelExtraction,
    Rate,
    RateTypeCanonical,
    Supplement,
)

# --------------------------------------------------------------------------
# Template selection
# --------------------------------------------------------------------------

_RATE_TYPE_TO_TEMPLATE: Dict[RateTypeCanonical, str] = {
    "Per Person Per Night": "moonstride_ppn",
    "Per Person Per Day": "moonstride_ppn",
    "Per Person Per Stay": "moonstride_ppn",
    "Per Room Per Night": "moonstride_prn_ac",
    "Per Room Per Night (Pax Count)": "moonstride_prn_pax",
    "Per Room Per Stay": "moonstride_prn_ac",
}

_TEMPLATE_RATE_TYPE_STRING: Dict[str, str] = {
    "moonstride_ppn": "Per Person Per Night",
    "moonstride_prn_ac": "Per Room Per Night (Adult / Child count)",
    "moonstride_prn_pax": "Per Room Per Night (Pax count)",
}

# Per-position child header set (mirrors moonstride_templates._CHILD_POSITION_HEADERS).
_CHILD_POSITIONS = [(1, "1st"), (2, "2nd"), (3, "3rd")]


def _classify_band(age_from: float, age_to: float) -> str:
    """Decide which Moonstride rate column band a contract child age range
    belongs to: baby (0-1), child (2-12), teen (12-17)."""
    if age_to <= 2:
        return "baby"
    if age_from >= 12:
        return "teen"
    return "child"


def _compute_band_price(band, adult_rate: Optional[float]) -> Optional[float]:
    """The per-row EUR amount for a child age band.

    Follows the rule established earlier in the project:
    - ``amount``                       -> the literal value
    - ``discount_percentage``, free    -> 0  (100% off accommodation)
    - ``discount_percentage``, other   -> adult_rate * (100 - value) / 100
    - ``percentage_of_adult``          -> adult_rate * value / 100
    - ``not_applicable`` / null value  -> None (NEVER 0; n/a stays blank)

    Adult-rate-dependent cases need a row's ``adult_rate``; if that's null
    we return None rather than guess.
    """
    if band is None:
        return None
    vt = band.value_type
    v = band.value
    if vt == "amount":
        return v
    if vt == "discount_percentage":
        if v is None:
            return None
        if v >= 100:
            return 0
        if adult_rate is None:
            return None
        return round(adult_rate * (100 - v) / 100, 2)
    if vt == "percentage_of_adult":
        if v is None or adult_rate is None:
            return None
        # Defensive: ``percentage_of_adult >= 100`` means "child pays at
        # least full adult rate", which is not a child policy. The
        # contract convention "1 = 100% free" is almost always misread
        # into this value_type; treat as free rather than emit a
        # nonsensical adult-priced child row. The prompt now also pushes
        # the model toward ``discount_percentage`` for fraction columns.
        if v >= 100:
            return 0
        return round(adult_rate * v / 100, 2)
    return None


def _row_adult_rate(rate: Optional[Rate]) -> Optional[float]:
    """Best per-adult rate available on a row, used to convert child-band %
    discounts into EUR amounts. Prefer DBL (per-person at standard double
    occupancy on a per-person grid; per-room rate on a per-room grid),
    fall back to SGL when the row only has single-occupancy."""
    if rate is None:
        return None
    return rate.dbl if rate.dbl is not None else rate.sgl


@dataclass
class MappingResult:
    template_id: str
    hotel_rows: List[Dict[str, Any]]
    supplement_rows: List[Dict[str, Any]]


# --------------------------------------------------------------------------
# Hotel rows
# --------------------------------------------------------------------------

def _pick_template_id(rate_type: RateTypeCanonical) -> str:
    return _RATE_TYPE_TO_TEMPLATE.get(rate_type, "moonstride_ppn")


def _rate_columns_adult_child(rate: Optional[Rate]) -> Dict[str, Any]:
    if rate is None:
        return {
            "Adult 1 (SGL)": None, "Adult 2 (DBL)": None,
            "Adult 3 (TPL)": None, "Adult 4 (QUD)": None,
            "Extra Adult": None,
        }
    return {
        "Adult 1 (SGL)": rate.sgl,
        "Adult 2 (DBL)": rate.dbl,
        "Adult 3 (TPL)": rate.tpl,
        "Adult 4 (QUD)": rate.qdp,
        "Extra Adult": rate.extra_bed_adult,
    }


def _rate_columns_pax(rate: Optional[Rate]) -> Dict[str, Any]:
    if rate is None:
        return {
            "1 Pax": None, "2 Pax": None, "3 Pax": None,
            "4 Pax": None, "5 Pax": None, "Extra Adult": None,
        }
    return {
        "1 Pax": rate.sgl, "2 Pax": rate.dbl, "3 Pax": rate.tpl,
        "4 Pax": rate.qdp, "5 Pax": None, "Extra Adult": rate.extra_bed_adult,
    }


def _child_band_columns(
    hotel: HotelExtraction, adult_rate: Optional[float]
) -> Dict[str, Any]:
    """Fill the legacy Moonstride band-based rate columns per row:
    Baby 1 (0-1), Child 1 (2-12), Teen 1 (12-17),
    Multi Infant (0-1), Extra Child (2-12), Extra Teen (12-17).

    Prices are computed from this rate row's ``adult_rate`` when the
    contract expresses the child as a discount %. Bands are classified by
    age range; within a band the FIRST fills the primary slot, the SECOND
    fills the Multi/Extra slot."""
    by_band: Dict[str, List[Any]] = {"baby": [], "child": [], "teen": []}
    for b in hotel.child_policy:
        slot = _classify_band(b.age_from, b.age_to)
        by_band[slot].append(b)

    def first(b: str) -> Any:
        return by_band[b][0] if by_band[b] else None

    def second(b: str) -> Any:
        return by_band[b][1] if len(by_band[b]) > 1 else None

    return {
        "Baby 1 (0-1)": _compute_band_price(first("baby"), adult_rate),
        "Child 1 (2-12)": _compute_band_price(first("child"), adult_rate),
        "Teen 1 (12-17)": _compute_band_price(first("teen"), adult_rate),
        "Multi Infant (0-1)": _compute_band_price(second("baby"), adult_rate),
        "Extra Child (2-12)": _compute_band_price(second("child"), adult_rate),
        "Extra Teen (12-17)": _compute_band_price(second("teen"), adult_rate),
    }


def _child_position_columns(
    hotel: HotelExtraction, adult_rate: Optional[float]
) -> Dict[str, Any]:
    """Build the 9 per-position child columns from this hotel's child_policy.

    Bands with a ``position`` set are assigned to that ordinal. Bands
    without a position fill positions 1..3 in contract order. Anything
    beyond position 3 is dropped (template only carries three slots).
    """
    out: Dict[str, Any] = {}
    # Group by explicit position
    by_position: Dict[int, Any] = {}
    unassigned: List[Any] = []
    pos_map = {"first_child": 1, "second_child": 2, "third_child": 3}
    for band in hotel.child_policy:
        if band.position is not None:
            slot = pos_map[band.position]
            by_position.setdefault(slot, band)
        else:
            unassigned.append(band)

    next_slot = 1
    for band in unassigned:
        while next_slot in by_position and next_slot <= 3:
            next_slot += 1
        if next_slot > 3:
            break
        by_position[next_slot] = band
        next_slot += 1

    for slot, label in _CHILD_POSITIONS:
        band = by_position.get(slot)
        out[f"{label} Child Price"] = _compute_band_price(band, adult_rate)
        out[f"{label} Child Age Min"] = band.age_from if band is not None else None
        out[f"{label} Child Age Max"] = band.age_to if band is not None else None
    return out


_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# View-supplement name patterns. When a supplement row's name matches
# any of these AND the kind is generic ("other"), treat it as a
# room-view supplement and skip it from the supplement file (it
# belongs in the hotel rate file instead — the room rate already
# includes the view delta).
_ROOM_VIEW_NAME_PATTERNS = (
    "supp.",          # "FAM PV Supp.", "SUP PV Supp."
    "view supp",
    "pool view",
    "sea view",
    "sea side view",
    "garden view",
    "beach front",
    "swim up",
    "swim-up",
)


def _looks_like_room_view_supplement(name: Optional[str]) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(p in n for p in _ROOM_VIEW_NAME_PATTERNS)

# AI-prefix carried in the LLM output for metadata values populated
# from training knowledge (vs. from the contract). Stripped from the
# visible value here; the row dict's "_ai_fields" side-channel tells
# the writer which cells to recolour after the standard colour-strip.
_AI_PREFIX = "[AI] "


def _split_ai(value: Optional[str]) -> Tuple[Optional[str], bool]:
    """Return (cleaned_value, is_ai_filled). Strips the leading
    ``"[AI] "`` marker the LLM emits to signal training-derived data."""
    if isinstance(value, str) and value.startswith(_AI_PREFIX):
        return value[len(_AI_PREFIX):], True
    return value, False


def _generate_hotel_code(name: Optional[str]) -> str:
    """Stable 6-character alphanumeric hotel code derived from the name.

    Same name → same code across runs (case- and whitespace-insensitive
    on input). Uses MD5 → first 32 bits → base36 → 6 uppercase
    alphanumeric characters (0-9, A-Z). Falls back to ``"000000"``
    only if name is empty/None."""
    if not name or not name.strip():
        return "000000"
    digest = hashlib.md5(name.strip().lower().encode("utf-8")).hexdigest()
    n = int(digest[:8], 16) % (36 ** 6)
    out = []
    for _ in range(6):
        out.append(_BASE36[n % 36])
        n //= 36
    return "".join(reversed(out))


def _hotel_base(hotel: HotelExtraction, template_rate_type: str) -> Dict[str, Any]:
    """Hotel-level columns that repeat on every rate row for this hotel.

    Metadata fields the LLM populated from training knowledge arrive
    with a leading ``"[AI] "`` marker. We strip it from the visible
    value here and record the header in the row's ``_ai_fields``
    side-channel so the writer can render those cells in a distinct
    font colour."""
    m = hotel.metadata
    code = m.code or _generate_hotel_code(m.name)
    ai_fields: set = set()

    def take(header: str, raw: Any) -> Any:
        if isinstance(raw, str):
            cleaned, is_ai = _split_ai(raw)
            if is_ai:
                ai_fields.add(header)
            return cleaned
        return raw

    out = {
        "Hotel Name": m.name,
        "Hotel Code": code,
        "Sell Channel": m.sell_channel,
        "Supplier": m.supplier,
        "Star Rating": m.star_rating,
        "Short Description": m.short_description,
        "Address Line 1": take("Address Line 1", m.address_line_1),
        "Address Line 2": take("Address Line 2", m.address_line_2),
        "Address Line 3": take("Address Line 3", m.address_line_3),
        "Address Line 4": take("Address Line 4", m.address_line_4),
        "Postal Code": take("Postal Code", m.postal_code),
        "Country Code": m.country_code,
        "County / State / Province": take(
            "County / State / Province", m.county_state_province,
        ),
        "City / Area": take("City / Area", m.city_area),
        "Phone Number": take("Phone Number", m.phone),
        "Email Address": take("Email Address", m.email),
        "Hotel Website": take("Hotel Website", m.website),
        # Lat / Long are numeric so they cannot carry the [AI] string
        # prefix. The contract effectively never lists geo-coords, so
        # any non-null value must have come from the model's training
        # knowledge — flag both as AI-derived when populated.
        "Latitude": m.latitude,
        "Longitude": m.longitude,
        "Check-In": m.check_in or "00:00",
        "Check-Out": m.check_out or "00:00",
        "Currency": m.currency or "EUR",
        "Customer Price Currency": m.currency or "EUR",
        "Rate Type": template_rate_type,
        "Status": "Open",
        "Days": "1234567",
        "Rate Plan": "Contract",
        "Add Charge Type": "Fixed",
        "Charge": "Mark Up",
    }
    if m.latitude is not None:
        ai_fields.add("Latitude")
    if m.longitude is not None:
        ai_fields.add("Longitude")
    out["_ai_fields"] = ai_fields
    return out


def build_hotel_rows(
    extraction: ContractExtraction,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Produce (template_id, hotel rows) keyed by Moonstride header names.

    Iterates ``(hotel × room × season × meal_plan)`` and joins to rates
    by string equality on ``room_name`` / ``season_label`` / ``meal_code``.
    Combinations without a Rate get one row with null rate cells (a
    Moonstride importer will reject these rows; including them makes
    coverage gaps visible to the reviewer).
    """
    template_id = _pick_template_id(extraction.detected_rate_type)
    template_rate_type = _TEMPLATE_RATE_TYPE_STRING[template_id]
    use_pax = template_id == "moonstride_prn_pax"

    out: List[Dict[str, Any]] = []
    for hotel in extraction.hotels:
        base = _hotel_base(hotel, template_rate_type)
        # Index rates by (room, season, meal_code) for O(1) lookup.
        rate_index: Dict[Tuple[str, str, str], Rate] = {}
        for r in hotel.rates:
            rate_index[(r.room_name, r.season_label, r.meal_code)] = r

        meal_canonical_by_code = {m.code: m.canonical for m in hotel.meal_plans}

        # Multi-loop emission.
        seasons = hotel.seasons or []
        rooms = hotel.rooms or []
        meals = hotel.meal_plans or []

        for room in rooms:
            for season in seasons:
                for meal in meals:
                    rate = rate_index.get((room.name, season.label, meal.code))
                    row: Dict[str, Any] = dict(base)
                    row["Room Name"] = room.name
                    row["Bed Type"] = room.bed_type
                    row["Max Rollaways"] = room.max_rollaways
                    row["Max Cribs (Cots)"] = room.max_cribs
                    row["Min Adult"] = room.min_adult
                    row["Max Adult"] = room.max_adult
                    row["Max Pax"] = room.max_pax
                    row["Season"] = season.label
                    row["Start Date"] = season.start_date
                    row["End Date"] = season.end_date
                    row["Min Stay"] = season.min_stay
                    row["Release Period"] = season.release_period
                    row["Meal Plan"] = (
                        meal_canonical_by_code.get(meal.code) or meal.canonical
                    )
                    # Rate columns
                    if use_pax:
                        row.update(_rate_columns_pax(rate))
                    else:
                        row.update(_rate_columns_adult_child(rate))
                    # Per-row computation: Extra Adult % uses this row's
                    # adult rate. Child policy columns are NO LONGER
                    # populated on the hotel sheet (per Jun 2026 user
                    # rule — child policy lives in the supplement file
                    # as per-room "Child policy" rows). The Baby /
                    # Child / Teen / 1st-3rd Child Price / Age Min /
                    # Age Max columns therefore stay blank.
                    adult_rate = _row_adult_rate(rate)
                    # If the contract gave Extra Adult as a discount % (e.g.
                    # "-30%"), compute the EUR amount for this row's adult
                    # rate and overwrite the Extra Adult column.
                    eb = getattr(rate, "extra_bed_adult", None) if rate else None
                    eb_kind = getattr(rate, "extra_bed_adult_kind", None) if rate else None
                    if (
                        adult_rate is not None
                        and eb_kind == "discount_percentage"
                        and eb is not None
                    ):
                        row["Extra Adult"] = round(
                            adult_rate * (100 - eb) / 100, 2
                        )
                    out.append(row)

    return template_id, out


# --------------------------------------------------------------------------
# Supplement rows
# --------------------------------------------------------------------------


def _format_cost(value: Optional[float], cost_format: str) -> Any:
    """Render a supplement cost cell. For ``cost_format="percentage"``
    return a ``"N%"`` string so the contract's percent semantics
    survive to the Excel — e.g. a "Single supplement 50%" line shows
    ``50%`` in the cell instead of being silently converted to a
    EUR figure. For the default ``"amount"`` format pass the numeric
    value through unchanged."""
    if value is None:
        return None
    if cost_format == "percentage":
        # Trim trailing .0 on integers so "50.0" becomes "50%".
        if isinstance(value, (int, float)) and float(value).is_integer():
            return f"{int(value)}%"
        return f"{value:g}%"
    return value


def _format_dd_mm_yyyy(iso_date: Optional[str]) -> Optional[str]:
    """ISO 'YYYY-MM-DD' -> 'DD-MM-YYYY'. Returns None on bad input."""
    if not iso_date or not isinstance(iso_date, str):
        return None
    parts = iso_date.split("-")
    if len(parts) != 3:
        return iso_date  # leave as-is; downstream importer will catch it
    y, m, d = parts
    if len(y) != 4 or len(m) != 2 or len(d) != 2:
        return iso_date
    return f"{d}-{m}-{y}"


def _resolve_fare_type_name(s: Supplement) -> Optional[str]:
    """Standard mode → 'Per Adult'/'Per Child'/'Per Infant';
    Pax Count / Pax Index → contract-supplied label."""
    if s.calculation_method == "Standard":
        return {
            "Adult": "Per Adult",
            "Child": "Per Child",
            "Infant": "Per Infant",
            "Traveller": "Per Traveller",
        }.get(s.traveler_type)
    return s.fare_type_name


def _resolve_standard_count_index(s: Supplement) -> Optional[int]:
    """User's rule: blank when Standard + Per Person Per Night;
    otherwise the canonical ``ordinal``."""
    if (
        s.calculation_method == "Standard"
        and s.charge_type == "Per Person Per Night"
    ):
        return None
    return s.ordinal


def _hotel_lookup(
    extraction: ContractExtraction,
) -> Dict[str, Tuple[Optional[str], Optional[str], Optional[str], bool]]:
    """name -> (code, supplier_clean, currency, supplier_is_ai).

    The ``supplier_is_ai`` flag travels with the row so the supplement
    writer can re-paint the Supplier cell in the AI font, mirroring the
    hotel-file behaviour. Strips the ``[AI] `` prefix from the
    supplier value before storing."""
    out: Dict[str, Tuple[Optional[str], Optional[str], Optional[str], bool]] = {}
    for hotel in extraction.hotels:
        m = hotel.metadata
        supplier, supplier_is_ai = _split_ai(m.supplier)
        out[m.name] = (
            m.code or _generate_hotel_code(m.name),
            supplier,
            m.currency,
            supplier_is_ai,
        )
    return out


def _room_occupancy_lookup(
    extraction: ContractExtraction,
) -> Dict[Tuple[str, str], Tuple[Optional[int], Optional[int], Optional[int]]]:
    """(hotel_name, room_name) -> (min_adult, max_adult, max_children).

    The supplement file's ``Min Adult`` / ``Max Adult`` / ``Max Child``
    columns mirror the hotel's room-occupancy limits when the supplement
    is scoped to a specific room (e.g. a per-room view supplement or a
    per-room child policy row). For supplements tagged ``Rooms = "ALL"``
    or ``"All Rooms"``, no per-room lookup is possible — the columns
    stay null and the Moonstride importer can use the hotel-wide
    defaults."""
    out: Dict[Tuple[str, str], Tuple[Optional[int], Optional[int], Optional[int]]] = {}
    for hotel in extraction.hotels:
        for room in hotel.rooms or []:
            if not room.name:
                continue
            out[(hotel.metadata.name, room.name)] = (
                room.min_adult, room.max_adult, room.max_children,
            )
    return out


def build_supplement_rows(
    extraction: ContractExtraction,
) -> List[Dict[str, Any]]:
    """Produce supplement rows keyed by the supplement template's
    headers."""
    hotel_lookup = _hotel_lookup(extraction)
    room_lookup = _room_occupancy_lookup(extraction)
    out: List[Dict[str, Any]] = []

    for s in extraction.supplements:
        # Per Jun 2026 user rule: room-view / room-supplement entries
        # (FAM PV Supp., SUP SSV, Pool View Supp., Beach Front Supp.,
        # etc.) belong inside the HOTEL rate file — each room already
        # carries the base+view rate. They MUST NOT also appear in the
        # supplement file, which is reserved for genuine extras (gala
        # dinners, meal upgrades, single supplement, taxes …) and
        # child policy rows.
        if s.kind == "room_view":
            continue
        # Heuristic safety net: catch view supplements emitted with the
        # generic kind="other" by recognising the name pattern.
        if s.kind == "other" and _looks_like_room_view_supplement(s.name):
            continue
        code, supplier, currency, supplier_is_ai = hotel_lookup.get(
            s.hotel_name, (None, None, None, False)
        )
        min_adult, max_adult, max_child = room_lookup.get(
            (s.hotel_name or "", s.rooms or ""), (None, None, None),
        )
        row: Dict[str, Any] = {
            "Hotel Name": s.hotel_name,
            "Hotel Code": code,
            "Supplement Code": s.code,
            "Supplement Name": s.name,
            "Rooms": s.rooms or "ALL",
            "Rate Plans": s.rate_plans,
            "Min Stay": s.min_stay,
            "Max Stay": s.max_stay,
            "Supplement Type": _canonical_supplement_type(
                s.kind, s.name, s.description
            ),
            "Display As Separate Room": s.display_as_separate_room or "No",
            # User rule: leave these three blank.
            "Meal Plan": None,
            "Required Supplement": None,
            "Restricted Supplement": None,
            # User rule: always Yes.
            "Display on Customer Documentation": "Yes",
            "Display on Supplier Notification": "Yes",
            "Description": s.description,
            "Contract Period": s.contract_period,
            "Season Name": s.season_label,
            "Start Date (DD-MM-YYYY)": _format_dd_mm_yyyy(s.start_date),
            "End Date (DD-MM-YYYY)": _format_dd_mm_yyyy(s.end_date),
            "Supplier": supplier,
            "Currency": currency or "EUR",
            "Charge Type": s.charge_type,
            "Calculation Method": s.calculation_method,
            "Traveler Type": s.traveler_type,
            "FareType Name": _resolve_fare_type_name(s),
            "Standard / Count / Index": _resolve_standard_count_index(s),
            "Min Age": s.age_min,
            "Max Age": s.age_max,
            "Min Adult": min_adult,
            "Max Adult": max_adult,
            "Max Child": max_child,
            "Supplier Cost": _format_cost(s.supplier_cost, s.cost_format),
            "Customer Price": _format_cost(
                s.customer_price if s.customer_price is not None else s.supplier_cost,
                s.cost_format,
            ),
        }
        if supplier_is_ai and supplier:
            row["_ai_fields"] = {"Supplier"}
        out.append(row)
    return out


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


_POS_TO_LABEL = {
    "first_child": "1st Child",
    "second_child": "2nd Child",
    "third_child": "3rd Child",
}
_POS_TO_INDEX = {
    "first_child": 1,
    "second_child": 2,
    "third_child": 3,
}


# Supplement Type is a Moonstride dropdown — the AI sample only uses
# these three values. Canonical "kind" maps to the enum value; raw LLM
# strings get normalised here too.
_COMPULSORY_KINDS = {"gala_dinner", "festive_period", "tax", "city_fee"}


def _canonical_supplement_type(
    kind: Optional[str], name: Optional[str], description: Optional[str]
) -> str:
    """Resolve the contract's free-form supplement type to the Moonstride
    dropdown enum: Exclusive / Compulsory / Inclusive."""
    if kind in _COMPULSORY_KINDS:
        return "Compulsory"
    text = " ".join(
        s for s in (name or "", description or "") if s
    ).lower()
    if any(w in text for w in ("obligatory", "compulsory", "mandatory")):
        return "Compulsory"
    if "inclusive" in text and "exclusive" not in text:
        return "Inclusive"
    return "Exclusive"


def _derive_child_policy_supplements(
    extraction: ContractExtraction,
) -> List[Dict[str, Any]]:
    """For each hotel × room × age band, emit one Pax-Index supplement row.

    Per user rule (Jun 2026): the hotel-import file no longer carries
    child band columns; the supplement file owns child policy. Each
    band gets a row PER ROOM (not "ALL"), the common Supplement Name
    "Child policy", Supplement Type "Compulsory", and a per-room cost
    computed from that room's own cheapest dbl rate.

    Hotels with no child policy bands emit nothing.
    """
    out: List[Dict[str, Any]] = []
    for hotel in extraction.hotels:
        # Drop bands the contract explicitly marked as not_applicable —
        # the band exists in the canonical model so the LLM doesn't
        # forget about it, but it produces no Moonstride supplement row.
        bands = [
            b for b in (hotel.child_policy or [])
            if b.value_type != "not_applicable"
        ]
        if not bands:
            continue
        # Per-room representative adult rate. Falls back to hotel-wide
        # cheapest dbl when a room has no priced rates yet (so the row
        # still emits — Moonstride can flag null cost for review).
        per_room_rate: Dict[str, Optional[float]] = {}
        for room in hotel.rooms or []:
            dbls = [
                r.dbl for r in hotel.rates
                if r.room_name == room.name and r.dbl is not None
            ]
            per_room_rate[room.name] = min(dbls) if dbls else None
        hotel_wide_dbls = [r.dbl for r in hotel.rates if r.dbl is not None]
        fallback_rate: Optional[float] = (
            min(hotel_wide_dbls) if hotel_wide_dbls else None
        )
        # Safety net: when a "room" has a suspiciously low rate (single
        # digits / low double digits) compared to the hotel-wide max,
        # it's almost certainly a view-supplement column the LLM
        # misclassified as a room. Use the hotel-wide MAX dbl instead
        # of the room's own low rate so the child-policy cost reflects
        # a real accommodation price. Threshold: if room rate <= 50% of
        # the hotel-wide max AND <= 30 EUR absolute, override.
        hotel_wide_max = max(hotel_wide_dbls) if hotel_wide_dbls else None
        if hotel_wide_max:
            for name, rate in list(per_room_rate.items()):
                if rate is None:
                    continue
                if rate <= 30 and rate <= 0.5 * hotel_wide_max:
                    per_room_rate[name] = hotel_wide_max

        hotel_code = hotel.metadata.code or _generate_hotel_code(hotel.metadata.name)
        supplier, supplier_is_ai = _split_ai(hotel.metadata.supplier)
        currency = hotel.metadata.currency or "EUR"
        room_names = [r.name for r in (hotel.rooms or []) if r.name]
        # Per-room occupancy limits for Min Adult / Max Adult / Max
        # Child columns on each emitted child-policy supplement row.
        room_occupancy: Dict[str, Tuple[Optional[int], Optional[int], Optional[int]]] = {
            r.name: (r.min_adult, r.max_adult, r.max_children)
            for r in (hotel.rooms or []) if r.name
        }
        if not room_names:
            # No rooms in canonical — still emit a single fallback row
            # so the policy doesn't silently disappear.
            room_names = ["ALL"]

        for idx, band in enumerate(bands):
            position_label = _POS_TO_LABEL.get(band.position or "", "Child")
            position_index = _POS_TO_INDEX.get(band.position or "", idx + 1)
            is_infant = band.age_to is not None and band.age_to <= 2
            traveler_type = "Infant" if is_infant else "Child"
            fare = band.label or (
                f"{position_label} ({band.age_from:g}-{band.age_to:g})"
            )
            # Per Jun 2026 user rule: a band populated with
            # ``applies_to_rooms`` only emits rows for THOSE rooms.
            # An empty/None list means "applies to all rooms" (legacy
            # behaviour, used when the contract has a single
            # hotel-wide child policy).
            if band.applies_to_rooms:
                applicable = {
                    name.strip().lower() for name in band.applies_to_rooms
                }
                targeted_rooms = [
                    rn for rn in room_names
                    if rn.strip().lower() in applicable
                ]
                # If the band's room names don't match ANY canonical
                # room (LLM typo'd), fall back to all rooms — the
                # alternative is silently losing the band, which is
                # worse for review.
                rooms_for_band = targeted_rooms or room_names
            else:
                rooms_for_band = room_names
            for room_name in rooms_for_band:
                room_rate = per_room_rate.get(room_name) or fallback_rate
                cost = _compute_band_price(band, room_rate)
                band_code = (
                    f"CHILD-{position_index}-{band.age_from:g}-{band.age_to:g}"
                )
                row: Dict[str, Any] = {
                    "Hotel Name": hotel.metadata.name,
                    "Hotel Code": hotel_code,
                    "Supplement Code": band_code,
                    "Supplement Name": "Child policy",
                    "Rooms": room_name,
                    "Rate Plans": None,
                    "Min Stay": None,
                    "Max Stay": None,
                    "Supplement Type": "Compulsory",
                    "Display As Separate Room": "No",
                    "Meal Plan": None,
                    "Required Supplement": None,
                    "Restricted Supplement": None,
                    "Display on Customer Documentation": "Yes",
                    "Display on Supplier Notification": "Yes",
                    "Description": (
                        f"{position_label} age band {band.age_from:g}-{band.age_to:g}; "
                        f"{band.value_type}"
                        + (f"={band.value:g}" if band.value is not None else "")
                    ),
                    "Contract Period": None,
                    "Season Name": None,
                    "Start Date (DD-MM-YYYY)": None,
                    "End Date (DD-MM-YYYY)": None,
                    "Supplier": supplier,
                    "Currency": currency,
                    "Charge Type": "Per Person Per Night",
                    "Calculation Method": "Pax Index",
                    "Traveler Type": traveler_type,
                    "FareType Name": fare,
                    "Standard / Count / Index": position_index,
                    "Min Age": band.age_from,
                    "Max Age": band.age_to,
                    "Supplier Cost": cost,
                    "Customer Price": cost,
                }
                room_min_adult, room_max_adult, room_max_child = (
                    room_occupancy.get(room_name, (None, None, None))
                )
                row["Min Adult"] = room_min_adult
                row["Max Adult"] = room_max_adult
                row["Max Child"] = room_max_child
                if supplier_is_ai and supplier:
                    row["_ai_fields"] = {"Supplier"}
                out.append(row)
    return out


def _derive_meal_plan_supplements(
    extraction: ContractExtraction,
) -> List[Dict[str, Any]]:
    """For each hotel × room × season with more than one meal plan, pick the
    cheapest as the base and emit one supplement row per non-base meal × per
    traveler type carrying the per-night delta.

    Moonstride's data model treats meal plans this way: BB is the base in
    the hotel sheet, HB / FB / AI appear as supplements over BB. Contracts
    that list BB / HB as side-by-side per-person columns (e.g. Acrotel)
    contain the data, but it has to be derived — the LLM doesn't compute
    it directly.
    """
    out: List[Dict[str, Any]] = []
    for hotel in extraction.hotels:
        meals = hotel.meal_plans or []
        if len(meals) < 2:
            continue
        m_code_to_canonical = {m.code: m.canonical for m in meals}
        hotel_supplier, hotel_supplier_is_ai = _split_ai(hotel.metadata.supplier)
        hotel_currency = hotel.metadata.currency or "EUR"
        hotel_code = hotel.metadata.code or _generate_hotel_code(hotel.metadata.name)
        # Per-room occupancy limits for Min/Max Adult & Max Child.
        meal_room_occupancy: Dict[str, Tuple[Optional[int], Optional[int], Optional[int]]] = {
            r.name: (r.min_adult, r.max_adult, r.max_children)
            for r in (hotel.rooms or []) if r.name
        }

        # Index rates by (room, season) -> { meal_code: rate }.
        by_room_season: Dict[Tuple[str, str], Dict[str, Rate]] = {}
        for r in hotel.rates:
            by_room_season.setdefault((r.room_name, r.season_label), {})[r.meal_code] = r

        # Child age bands by classification (for child supplement rows).
        child_bands_by_age: Dict[str, Any] = {"baby": None, "child": None}
        for b in hotel.child_policy:
            slot = _classify_band(b.age_from, b.age_to)
            if slot in child_bands_by_age and child_bands_by_age[slot] is None:
                child_bands_by_age[slot] = b

        season_by_label = {s.label: s for s in hotel.seasons}

        for (room_name, season_label), meal_rates in by_room_season.items():
            if len(meal_rates) < 2:
                continue
            # Pick the cheapest meal-plan rate as the base (use dbl/sgl).
            def _base_rate(r: Rate) -> Optional[float]:
                return r.dbl if r.dbl is not None else r.sgl
            scored = sorted(
                meal_rates.items(),
                key=lambda kv: (_base_rate(kv[1]) is None, _base_rate(kv[1]) or 0),
            )
            base_code, base_rate_obj = scored[0]
            base_amount = _base_rate(base_rate_obj)
            if base_amount is None:
                continue
            season = season_by_label.get(season_label)

            for meal_code, rate in meal_rates.items():
                if meal_code == base_code:
                    continue
                amount = _base_rate(rate)
                if amount is None or amount <= base_amount:
                    continue
                delta = round(amount - base_amount, 2)
                canonical_name = m_code_to_canonical.get(meal_code) or meal_code
                # Adult row: Standard + Per Person Per Night
                # Per the user rule, Standard/Count/Index column stays blank;
                # the writer fills "Per Adult" deterministically below.
                base_row = {
                    "Hotel Name": hotel.metadata.name,
                    "Hotel Code": hotel_code,
                    "Supplement Code": f"SUP-{meal_code}",
                    "Supplement Name": f"{canonical_name} upgrade",
                    "Rooms": room_name,
                    "Rate Plans": None,
                    "Min Stay": season.min_stay if season else None,
                    "Max Stay": None,
                    "Supplement Type": "Exclusive",
                    "Display As Separate Room": "No",
                    "Meal Plan": None,
                    "Required Supplement": None,
                    "Restricted Supplement": None,
                    "Display on Customer Documentation": "Yes",
                    "Display on Supplier Notification": "Yes",
                    "Description": (
                        f"{canonical_name} supplement over {m_code_to_canonical.get(base_code, base_code)}"
                    ),
                    "Contract Period": None,
                    "Season Name": season_label,
                    "Start Date (DD-MM-YYYY)": _format_dd_mm_yyyy(season.start_date) if season else None,
                    "End Date (DD-MM-YYYY)": _format_dd_mm_yyyy(season.end_date) if season else None,
                    "Supplier": hotel_supplier,
                    "Currency": hotel_currency,
                    "Charge Type": "Per Person Per Night",
                    "Calculation Method": "Standard",
                    "Standard / Count / Index": None,  # rule: blank for Standard + PPN
                    "Min Age": None,
                    "Max Age": None,
                }
                room_mn, room_mx, room_mxc = meal_room_occupancy.get(
                    room_name, (None, None, None)
                )
                base_row["Min Adult"] = room_mn
                base_row["Max Adult"] = room_mx
                base_row["Max Child"] = room_mxc
                if hotel_supplier_is_ai and hotel_supplier:
                    base_row["_ai_fields"] = {"Supplier"}
                # Per Jun 2026 user rule: do NOT fabricate Child / Infant
                # rows for meal-plan upgrades by applying the hotel's
                # general child policy to the upgrade delta. The
                # contract's child policy is a discount on the BASE
                # accommodation rate, not on meal-plan deltas — those
                # two concerns must not be conflated. Only emit Adult.
                # Per-supplement child rules (e.g. "Gala dinner:
                # Children 6-12.99 charged 50%") still produce their
                # own Child rows because the LLM emits them directly
                # in build_supplement_rows.
                adult_row = dict(base_row)
                adult_row.update({
                    "Traveler Type": "Adult",
                    "FareType Name": "Per Adult",
                    "Supplier Cost": delta,
                    "Customer Price": delta,
                })
                out.append(adult_row)
    return out


def map_extraction(extraction: ContractExtraction) -> MappingResult:
    template_id, hotel_rows = build_hotel_rows(extraction)
    supplement_rows = build_supplement_rows(extraction)
    # Derive meal-plan-upgrade supplements from the rate matrix (BB → HB
    # delta etc.) — fix for contracts like Acrotel that list multiple
    # meal plans as parallel per-person columns rather than named
    # supplement clauses.
    supplement_rows.extend(_derive_meal_plan_supplements(extraction))
    # Derive child-policy supplement rows so the supplement file carries
    # the contract's child age bands too (1st/2nd/3rd Child as Pax Index
    # rows with computed cost per band).
    supplement_rows.extend(_derive_child_policy_supplements(extraction))
    return MappingResult(
        template_id=template_id,
        hotel_rows=hotel_rows,
        supplement_rows=supplement_rows,
    )
