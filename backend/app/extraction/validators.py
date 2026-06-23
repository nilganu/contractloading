"""Phase 3 — deterministic cross-validation of a single HotelExtraction.

Each validator returns a list of ``ValidationIssue`` records. The
orchestrator inspects these and, for issues whose ``code`` is
``MISSING_RATES``, builds a targeted retry prompt to re-fetch the
specific (room, season, meal_code) combinations the LLM missed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .canonical import HotelExtraction


@dataclass
class ValidationIssue:
    code: str
    severity: str
    message: str
    missing_combinations: List[Tuple[str, str, str]] = field(default_factory=list)


def validate_hotel(hotel: HotelExtraction) -> List[ValidationIssue]:
    """Run all hotel-level validators; return all issues found."""
    issues: List[ValidationIssue] = []
    issues.extend(_check_rate_matrix_coverage(hotel))
    return issues


def _check_rate_matrix_coverage(hotel: HotelExtraction) -> List[ValidationIssue]:
    """Compare expected (room × season × meal_plan) combinations with
    what's in ``hotel.rates``. Flag the missing triples so the
    orchestrator can retarget the LLM at exactly the cells it dropped.

    Skips the check when any of rooms / seasons / meal_plans is empty —
    those are different failures, not rate-matrix gaps.
    """
    rooms = [r.name for r in (hotel.rooms or []) if r.name]
    seasons = [s.label for s in (hotel.seasons or []) if s.label]
    meals = [m.code for m in (hotel.meal_plans or []) if m.code]
    if not rooms or not seasons or not meals:
        return []

    present = {
        (r.room_name, r.season_label, r.meal_code)
        for r in (hotel.rates or [])
        if r.room_name and r.season_label and r.meal_code
    }
    # A rate is "filled" only if it has at least one numeric occupancy
    # price — an emitted row with all-null cells is just as missing as
    # one that wasn't emitted at all.
    filled = {
        (r.room_name, r.season_label, r.meal_code)
        for r in (hotel.rates or [])
        if any(
            getattr(r, k, None) is not None
            for k in ("sgl", "dbl", "tpl", "qdp")
        )
    }

    expected = [(room, season, meal) for room in rooms for season in seasons for meal in meals]
    missing = [t for t in expected if t not in filled]
    if not missing:
        return []

    ratio = len(filled) / max(len(expected), 1)
    severity = "error" if ratio < 0.5 else "warning"
    msg = (
        f"Rate matrix coverage for hotel {hotel.metadata.name!r}: "
        f"{len(filled)}/{len(expected)} priced ({ratio:.0%}). "
        f"{len(missing)} (room, season, meal) combinations are missing rates."
    )
    return [
        ValidationIssue(
            code="MISSING_RATES",
            severity=severity,
            message=msg,
            missing_combinations=missing,
        )
    ]
