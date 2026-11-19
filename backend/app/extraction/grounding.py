"""Deterministic check that extracted amounts exist in the source.

LLMs can misread, transpose or invent numbers. After extraction, every
price the model returned (room rates, extra beds, child amounts,
supplement costs) is looked up in the set of numbers the reader found in
the source. Anything not found becomes a "Source ambiguity" note for
the reviewer; nothing is changed or dropped automatically, because some
values are legitimately derived (e.g. a per-room price computed from a
per-person one).
"""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Set, Tuple

from .canonical import ContractExtraction, ExtractionNote
from .reader import SourceView

logger = logging.getLogger(__name__)

_MAX_LISTED = 15  # values listed per note; the rest are counted


def _found(value: float, numbers: Set[float]) -> bool:
    if value is None:
        return True
    v = round(float(value), 4)
    if v == 0:
        return True  # "free" is usually written as text, not 0
    for cand in (v, round(v / 100, 4), round(v * 100, 4)):  # 50 <-> 0.5 (50%)
        if cand in numbers:
            return True
    # tolerate rounding of displayed values (e.g. 33.33 vs 33.333)
    return any(abs(n - v) <= 0.011 for n in numbers if abs(n - v) < 1)


def _amounts(extraction: ContractExtraction) -> Iterable[Tuple[str, str, float]]:
    """(hotel, where, value) for every amount the model extracted."""
    for h in extraction.hotels:
        hotel = h.metadata.name
        for r in h.rates:
            where = f"{r.room_name} / {r.season_label} / {r.meal_code}"
            for fld in ("sgl", "dbl", "tpl", "qdp", "extra_bed_adult", "extra_bed_child"):
                v = getattr(r, fld, None)
                if v is not None:
                    yield hotel, f"{where} {fld}", v
        for b in h.child_policy:
            if b.value is not None:
                yield hotel, f"child {b.label or f'{b.age_from}-{b.age_to}'}", b.value
    for s in extraction.supplements or []:
        for fld in ("supplier_cost", "customer_price"):
            v = getattr(s, fld, None)
            if v is not None:
                yield s.hotel_name, f"supplement '{s.name}' {fld}", v


def ungrounded_amounts(
    extraction: ContractExtraction, view: Optional[SourceView]
) -> List[Tuple[str, str, float]]:
    if view is None or not view.numbers:
        return []
    return [
        (hotel, where, v)
        for hotel, where, v in _amounts(extraction)
        if not _found(v, view.numbers)
    ]


def add_grounding_notes(
    extraction: ContractExtraction, view: Optional[SourceView]
) -> int:
    """Append one review note per hotel listing amounts not found in the
    source, plus the reader's own warnings. Returns the number of
    ungrounded amounts."""
    if view is None:
        return 0
    misses = ungrounded_amounts(extraction, view)
    by_hotel: dict = {}
    for hotel, where, v in misses:
        by_hotel.setdefault(hotel, []).append(f"{where} = {v:g}")
    for hotel, items in by_hotel.items():
        listed = "; ".join(items[:_MAX_LISTED])
        more = f" (+{len(items) - _MAX_LISTED} more)" if len(items) > _MAX_LISTED else ""
        extraction.notes.append(
            ExtractionNote(
                category="Source ambiguity",
                hotel_name=hotel,
                note=(
                    f"{len(items)} extracted amount(s) not found in the source "
                    f"document — check before import: {listed}{more}"
                ),
            )
        )
    hotel_name = extraction.hotels[0].metadata.name if extraction.hotels else None
    for w in view.warnings:
        if w.startswith("Hidden sheet"):
            continue  # expected; logged by the reader
        extraction.notes.append(
            ExtractionNote(category="Other", hotel_name=hotel_name, note=f"Reader: {w}")
        )
    if misses:
        logger.info("grounding: %d amount(s) not found in source", len(misses))
    return len(misses)
