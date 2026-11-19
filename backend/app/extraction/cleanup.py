"""Deterministic clean-up applied to every extraction before mapping.

Each step fixes a class of model mistake, never a specific contract:

* ``align_hotel_names``  – supplements/notes added by retry passes are often
  tagged with another spelling of the hotel (legal name, local-language
  name). Joins and duplicate detection are per hotel, so retag them to the
  ``HotelMetadata.name`` they belong to.
* ``expand_season_ranges`` – a season that covers several date ranges
  (same season next year, Low season either side of High) becomes one
  season per range, with its rates and supplements copied.
* ``fix_breakfast_meal_plans`` – breakfast codes (ABF, CBF, "Room +
  breakfast") read as the "American" (full-board) plan become "Bed and
  Breakfast".
* ``flag_overlapping_seasons`` – seasons that partly overlap for the same
  room and meal plan would clash on import; add a review note.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from .canonical import ContractExtraction, ExtractionNote, Season

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "hotel", "resort", "and", "co", "ltd", "company", "limited",
         "khach", "san", "spa", "by", "at", "of"}


def _tokens(name: Optional[str]) -> Set[str]:
    words = _WORD.findall((name or "").casefold())
    return {w for w in words if w not in _STOP} or set(words)


def _best_hotel(name: Optional[str], hotel_names: List[str]) -> Optional[str]:
    if not hotel_names:
        return None
    if len(hotel_names) == 1:
        return hotel_names[0]
    folded = (name or "").strip().casefold()
    for h in hotel_names:
        if h.strip().casefold() == folded:
            return h
    toks = _tokens(name)
    scored = []
    for h in hotel_names:
        ht = _tokens(h)
        if toks and ht:
            scored.append((len(toks & ht) / len(toks | ht), h))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def align_hotel_names(extraction: ContractExtraction) -> int:
    """Retag supplements and notes to an existing hotel name. Returns count changed."""
    hotel_names = [h.metadata.name for h in extraction.hotels if h.metadata.name]
    changed = 0
    items = list(extraction.supplements or []) + [
        n for n in (extraction.notes or []) if n.hotel_name  # skip contract-wide notes
    ]
    for item in items:
        current = item.hotel_name
        target = _best_hotel(current, hotel_names)
        if target and target != current:
            item.hotel_name = target
            changed += 1
    if changed:
        logger.info("retagged %d supplement/note hotel name(s)", changed)
    return changed


def _range_label(base: str, n: int) -> str:
    return f"{base} [{n}]"


def expand_season_ranges(extraction: ContractExtraction) -> int:
    """One Season per date range. Returns number of seasons added."""
    added = 0
    for hotel in extraction.hotels:
        name = hotel.metadata.name
        new_seasons: List[Season] = []
        for season in hotel.seasons:
            ranges = [
                r for r in (season.additional_ranges or [])
                if (r.start_date, r.end_date) != (season.start_date, season.end_date)
            ]
            season.additional_ranges = None
            new_seasons.append(season)
            for i, r in enumerate(ranges, start=2):
                label = _range_label(season.label, i)
                new_seasons.append(season.model_copy(update={
                    "label": label,
                    "start_date": r.start_date,
                    "end_date": r.end_date,
                    "additional_ranges": None,
                }))
                hotel.rates.extend(
                    rate.model_copy(update={"season_label": label})
                    for rate in list(hotel.rates)
                    if rate.season_label == season.label
                )
                extraction.supplements.extend(
                    s.model_copy(update={"season_label": label})
                    for s in list(extraction.supplements or [])
                    if s.season_label == season.label and s.hotel_name == name
                )
                added += 1
        hotel.seasons = new_seasons
    if added:
        logger.info("expanded %d extra season date range(s)", added)
    return added


_FULL_BOARD_HINTS = ("PLAN", "BOARD", "HB", "FB", "DINNER", "LUNCH", "AI", "INCLUSIVE")


def _is_breakfast_only(code: str) -> bool:
    c = code.upper()
    has_breakfast = ("BREAKFAST" in c or re.search(r"\b[AC]?BF\b", c) is not None
                     or re.search(r"\bB\s*&\s*B\b|\bBB\b", c) is not None)
    if not has_breakfast:
        return False
    return not any(re.search(rf"\b{h}\b", c) for h in _FULL_BOARD_HINTS)


def fix_breakfast_meal_plans(extraction: ContractExtraction) -> int:
    changed = 0
    for hotel in extraction.hotels:
        for mp in hotel.meal_plans:
            if mp.canonical in ("American", "Modified American") and _is_breakfast_only(mp.code):
                mp.canonical = "Bed and Breakfast"
                changed += 1
    if changed:
        logger.info("mapped %d breakfast code(s) to Bed and Breakfast", changed)
    return changed


def _d(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def flag_overlapping_seasons(extraction: ContractExtraction) -> int:
    """Add a review note for seasons that partly overlap on the same room/meal."""
    flagged = 0
    for hotel in extraction.hotels:
        priced: Dict[str, Set[Tuple[str, str]]] = {}
        for r in hotel.rates:
            priced.setdefault(r.season_label, set()).add((r.room_name, r.meal_code))
        spans = [(s.label, _d(s.start_date), _d(s.end_date)) for s in hotel.seasons]
        spans = [(l, a, b) for l, a, b in spans if a and b]
        pairs = []
        for i, (la, a1, a2) in enumerate(spans):
            for lb, b1, b2 in spans[i + 1:]:
                if (a1, a2) == (b1, b2):
                    continue  # identical ranges: market/version split
                if a1 <= b2 and b1 <= a2 and priced.get(la, set()) & priced.get(lb, set()):
                    pairs.append(f"'{la}' ({a1}–{a2}) and '{lb}' ({b1}–{b2})")
        if pairs:
            flagged += len(pairs)
            shown = "; ".join(pairs[:6]) + (" …" if len(pairs) > 6 else "")
            extraction.notes.append(ExtractionNote(
                category="Source ambiguity",
                hotel_name=hotel.metadata.name,
                note=(f"Overlapping seasons price the same rooms: {shown}. "
                      "Check the season dates against the contract before import."),
            ))
    return flagged


def _same_name(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = set(_WORD.findall((a or "").casefold())), set(_WORD.findall((b or "").casefold()))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def drop_undated_copies(extraction: ContractExtraction) -> int:
    """Retry passes often re-emit a supplement without its dates. Drop an
    undated supplement when a dated one for the same hotel has the same
    (near-)name, price and charge rules. An undated supplement with no
    dated twin (e.g. "dates to be announced") is kept."""
    def rule(s):
        cost = s.supplier_cost if s.supplier_cost is not None else s.customer_price
        return (s.hotel_name, s.kind, s.charge_type, s.calculation_method,
                s.traveler_type, s.ordinal, s.age_min, s.age_max, cost, s.cost_format)

    dated = [s for s in extraction.supplements if s.start_date or s.end_date]
    keep = []
    for s in extraction.supplements:
        if not (s.start_date or s.end_date) and any(
            rule(d) == rule(s) and _same_name(d.name, s.name) for d in dated
        ):
            continue
        keep.append(s)
    dropped = len(extraction.supplements) - len(keep)
    if dropped:
        logger.info("dropped %d undated duplicate supplement(s)", dropped)
    extraction.supplements = keep
    return dropped


def tidy_extraction(extraction: ContractExtraction) -> ContractExtraction:
    """Run every clean-up step except supplement de-duplication (done by the
    orchestrator right after, once hotel names agree)."""
    align_hotel_names(extraction)
    expand_season_ranges(extraction)
    fix_breakfast_meal_plans(extraction)
    return extraction
