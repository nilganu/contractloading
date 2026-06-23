"""Unit tests for Phase 3 deterministic validators."""
from __future__ import annotations

from app.extraction.canonical import (
    HotelExtraction, HotelMetadata, MealPlanEntry, Rate, RoomType, Season,
)
from app.extraction.validators import validate_hotel


def _hotel(rooms, seasons, meals, rates):
    return HotelExtraction(
        metadata=HotelMetadata(name="Test", currency="EUR"),
        rooms=[RoomType(name=r, max_pax=2) for r in rooms],
        seasons=[
            Season(label=s, start_date="2025-05-01", end_date="2025-09-30")
            for s in seasons
        ],
        meal_plans=[MealPlanEntry(code=m, canonical="Bed and Breakfast") for m in meals],
        rates=rates,
        child_policy=[],
    )


def test_validate_hotel_no_issues_when_fully_covered():
    rates = [
        Rate(room_name="Standard", season_label="Summer", meal_code="BB", dbl=100),
        Rate(room_name="Standard", season_label="Winter", meal_code="BB", dbl=80),
    ]
    issues = validate_hotel(_hotel(["Standard"], ["Summer", "Winter"], ["BB"], rates))
    assert issues == []


def test_validate_hotel_flags_missing_combinations():
    # Expected = 2 rooms × 2 seasons × 1 meal = 4 combos; we provide 1.
    rates = [Rate(room_name="A", season_label="S1", meal_code="BB", dbl=100)]
    issues = validate_hotel(_hotel(["A", "B"], ["S1", "S2"], ["BB"], rates))
    assert len(issues) == 1
    assert issues[0].code == "MISSING_RATES"
    assert issues[0].severity == "error"  # 1/4 = 25%
    missing = set(map(tuple, issues[0].missing_combinations))
    assert ("A", "S1", "BB") not in missing
    assert ("A", "S2", "BB") in missing
    assert ("B", "S1", "BB") in missing
    assert ("B", "S2", "BB") in missing


def test_validate_hotel_warning_severity_when_partial_coverage():
    # 3/4 priced = 75% → warning, not error
    rates = [
        Rate(room_name="A", season_label="S1", meal_code="BB", dbl=100),
        Rate(room_name="A", season_label="S2", meal_code="BB", dbl=110),
        Rate(room_name="B", season_label="S1", meal_code="BB", dbl=120),
    ]
    issues = validate_hotel(_hotel(["A", "B"], ["S1", "S2"], ["BB"], rates))
    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_validate_hotel_treats_null_rate_row_as_missing():
    # Emitted row but all-null prices → counts as missing, not filled.
    rates = [
        Rate(room_name="A", season_label="S1", meal_code="BB"),  # all-null
        Rate(room_name="A", season_label="S2", meal_code="BB", dbl=100),
    ]
    issues = validate_hotel(_hotel(["A"], ["S1", "S2"], ["BB"], rates))
    assert len(issues) == 1
    missing = set(map(tuple, issues[0].missing_combinations))
    assert ("A", "S1", "BB") in missing


def test_validate_hotel_skips_check_when_lists_empty():
    # No rooms / seasons / meals → not a rate-matrix issue.
    issues = validate_hotel(_hotel([], ["S1"], ["BB"], []))
    assert issues == []
    issues = validate_hotel(_hotel(["A"], [], ["BB"], []))
    assert issues == []
    issues = validate_hotel(_hotel(["A"], ["S1"], [], []))
    assert issues == []
