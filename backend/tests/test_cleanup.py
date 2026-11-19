"""General post-extraction clean-up (cleanup.py + orchestrator._finalize)."""
from __future__ import annotations

from app.extraction.canonical import (
    ContractExtraction, DateRange, ExtractionNote, HotelExtraction,
    HotelMetadata, MealPlanEntry, Rate, RoomType, Season, Supplement,
)
from app.extraction.cleanup import (
    align_hotel_names, expand_season_ranges, fix_breakfast_meal_plans,
    flag_overlapping_seasons,
)
from app.extraction.moonstride_mapper import map_extraction
from app.extraction.orchestrator import _finalize


def _hotel(name="Sea View Resort", seasons=None, rates=None, meals=None):
    return HotelExtraction(
        metadata=HotelMetadata(name=name),
        rooms=[RoomType(name="DBL")], child_policy=[],
        meal_plans=meals or [MealPlanEntry(code="BB", canonical="Bed and Breakfast")],
        seasons=seasons or [Season(label="S1", start_date="2026-01-01", end_date="2026-03-31")],
        rates=rates or [Rate(room_name="DBL", season_label="S1", meal_code="BB", dbl=100)],
    )


def _supp(hotel, name="Gala dinner", cost=50.0, start="2026-12-24", end="2026-12-24", season=None):
    return Supplement(
        name=name, kind="gala_dinner", hotel_name=hotel,
        charge_type="Per Person Per Night", calculation_method="Standard",
        traveler_type="Adult", supplier_cost=cost, customer_price=cost,
        cost_format="amount", start_date=start, end_date=end, season_label=season,
    )


def _x(hotels, supplements=(), notes=()):
    return ContractExtraction(
        source_filename="c.pdf", is_multi_hotel=len(hotels) > 1,
        detected_rate_type="Per Room Per Night",
        hotels=list(hotels), supplements=list(supplements), notes=list(notes),
    )


def test_single_hotel_retags_other_spellings_and_dedups() -> None:
    x = _x([_hotel()], supplements=[
        _supp("Sea View Resort", name="Public holiday surcharge"),
        _supp("Sea View Resort Co., Ltd.", name="Public holiday surcharge - Christmas"),
    ], notes=[ExtractionNote(category="Other", note="n", hotel_name="SVR legal entity")])
    _finalize(x)
    assert len(x.supplements) == 1
    assert x.supplements[0].hotel_name == "Sea View Resort"
    assert x.supplements[0].name.endswith("Christmas")  # more specific name kept
    assert x.notes[0].hotel_name == "Sea View Resort"


def test_multi_hotel_alignment_is_by_closest_name() -> None:
    x = _x([_hotel("Alpha Beach Hotel"), _hotel("Beta Garden Resort")], supplements=[
        _supp("Alpha Beach"), _supp("Beta Garden"), _supp("Unrelated Inn"),
    ])
    align_hotel_names(x)
    assert [s.hotel_name for s in x.supplements] == [
        "Alpha Beach Hotel", "Beta Garden Resort", "Unrelated Inn",
    ]


def test_different_supplements_are_not_merged() -> None:
    x = _x([_hotel()], supplements=[
        _supp("Sea View Resort", name="Honeymoon offer", cost=0.0),
        _supp("Sea View Resort", name="Child breakfast", cost=5.0),
        _supp("Sea View Resort", name="Adult breakfast", cost=8.0),
    ])
    _finalize(x)
    assert len(x.supplements) == 3


def test_additional_ranges_become_seasons_with_rates_and_supplements() -> None:
    season = Season(
        label="Season 1", start_date="2025-11-01", end_date="2025-12-25",
        additional_ranges=[DateRange(start_date="2026-11-01", end_date="2026-12-25")],
    )
    rates = [Rate(room_name="DBL", season_label="Season 1", meal_code="BB", dbl=2100)]
    x = _x([_hotel(seasons=[season], rates=rates)],
           supplements=[_supp("Sea View Resort", season="Season 1", start=None, end=None)])
    assert expand_season_ranges(x) == 1
    h = x.hotels[0]
    assert [(s.label, s.start_date, s.end_date) for s in h.seasons] == [
        ("Season 1", "2025-11-01", "2025-12-25"),
        ("Season 1 [2]", "2026-11-01", "2026-12-25"),
    ]
    assert {(r.season_label, r.dbl) for r in h.rates} == {("Season 1", 2100), ("Season 1 [2]", 2100)}
    assert {s.season_label for s in x.supplements} == {"Season 1", "Season 1 [2]"}
    rows = map_extraction(x).hotel_rows
    assert sorted((r["Start Date"], r["End Date"]) for r in rows) == [
        ("2025-11-01", "2025-12-25"), ("2026-11-01", "2026-12-25"),
    ]


def test_breakfast_codes_never_map_to_american_plan() -> None:
    meals = [
        MealPlanEntry(code="ABF", canonical="American"),
        MealPlanEntry(code="Room + CBF", canonical="Modified American"),
        MealPlanEntry(code="AP", canonical="American"),
        MealPlanEntry(code="MAP (breakfast + dinner)", canonical="Modified American"),
    ]
    x = _x([_hotel(meals=meals)])
    assert fix_breakfast_meal_plans(x) == 2
    assert [m.canonical for m in x.hotels[0].meal_plans] == [
        "Bed and Breakfast", "Bed and Breakfast", "American", "Modified American",
    ]


def test_partly_overlapping_seasons_are_flagged_identical_are_not() -> None:
    seasons = [
        Season(label="S1", start_date="2025-11-01", end_date="2026-12-25"),
        Season(label="S2", start_date="2025-12-26", end_date="2026-01-10"),
        Season(label="S1 UK", start_date="2025-11-01", end_date="2026-12-25"),  # market split
    ]
    rates = [Rate(room_name="DBL", season_label=s.label, meal_code="BB", dbl=1) for s in seasons]
    x = _x([_hotel(seasons=seasons, rates=rates)])
    assert flag_overlapping_seasons(x) == 2  # S1/S2 and S2/S1 UK, not S1/S1 UK
    assert x.notes[-1].category == "Source ambiguity"
    assert "'S1'" in x.notes[-1].note and "'S2'" in x.notes[-1].note


def test_undated_retry_copy_is_dropped_but_unique_undated_kept() -> None:
    from app.extraction.cleanup import drop_undated_copies

    h = "Sea View Resort"
    x = _x([_hotel()], supplements=[
        _supp(h, name="Transfer charge - car", cost=1000.0, start="2025-11-01", end="2027-10-31"),
        _supp(h, name="Transfer charge - car", cost=1000.0, start=None, end=None),
        _supp(h, name="Holiday surcharge", cost=8.0, start="2026-01-01", end="2026-01-01"),
        _supp(h, name="Holiday surcharge - city fireworks festival (dates TBA)", cost=8.0, start=None, end=None),
    ])
    assert drop_undated_copies(x) == 1
    assert [s.name for s in x.supplements] == [
        "Transfer charge - car", "Holiday surcharge",
        "Holiday surcharge - city fireworks festival (dates TBA)",
    ]


def test_similar_but_different_hotel_is_not_retagged() -> None:
    x = _x([_hotel("Barcelo Sharm Resort"), _hotel("Jaz Mirabel Beach")], supplements=[
        _supp("Barcelo Tiran Sharm"), _supp("Barcelo Sharm Resort Co., Ltd."),
    ])
    align_hotel_names(x)
    assert [s.hotel_name for s in x.supplements] == [
        "Barcelo Tiran Sharm", "Barcelo Sharm Resort",
    ]


def test_season_copy_moves_season_dated_supplements_only() -> None:
    season = Season(
        label="S1", start_date="2025-11-01", end_date="2025-12-25",
        additional_ranges=[DateRange(start_date="2026-11-01", end_date="2026-12-25")],
    )
    h = "Sea View Resort"
    x = _x([_hotel(seasons=[season], rates=[Rate(room_name="DBL", season_label="S1", meal_code="BB", dbl=1)])],
           supplements=[
               _supp(h, name="Season supplement", start="2025-11-01", end="2025-12-25", season="S1"),
               _supp(h, name="Gala", start="2025-12-24", end="2025-12-24", season="S1"),
           ])
    expand_season_ranges(x)
    got = sorted((s.name, s.season_label, s.start_date) for s in x.supplements)
    assert got == [
        ("Gala", "S1", "2025-12-24"),
        ("Season supplement", "S1", "2025-11-01"),
        ("Season supplement", "S1 [2]", "2026-11-01"),
    ]


def test_undated_seasonal_supplement_is_kept() -> None:
    from app.extraction.cleanup import drop_undated_copies

    h = "Sea View Resort"
    x = _x([_hotel()], supplements=[
        _supp(h, name="Gala dinner", start="2026-12-31", end="2026-12-31"),
        _supp(h, name="Gala dinner", start=None, end=None, season="High"),
    ])
    assert drop_undated_copies(x) == 0


def test_supplement_additional_ranges_become_rows() -> None:
    from app.extraction.cleanup import expand_supplement_ranges

    s = _supp("Sea View Resort", name="AP20", start="2026-04-01", end="2026-12-31")
    s.additional_ranges = [DateRange(start_date="2027-01-01", end_date="2027-03-31")]
    x = _x([_hotel()], supplements=[s])
    assert expand_supplement_ranges(x) == 1
    assert [(s.start_date, s.end_date) for s in x.supplements] == [
        ("2026-04-01", "2026-12-31"), ("2027-01-01", "2027-03-31"),
    ]


def test_per_room_meal_upgrade_is_per_room_by_occupancy() -> None:
    meals = [MealPlanEntry(code="RO", canonical="Room only"),
             MealPlanEntry(code="BB", canonical="Bed and Breakfast")]
    rates = [
        Rate(room_name="DBL", season_label="S1", meal_code="RO", sgl=280, dbl=280),
        Rate(room_name="DBL", season_label="S1", meal_code="BB", sgl=320, dbl=320),
        Rate(room_name="FAM", season_label="S1", meal_code="RO", tpl=500, qdp=500),
        Rate(room_name="FAM", season_label="S1", meal_code="BB", tpl=590, qdp=620),
    ]
    h = _hotel(meals=meals, rates=rates)
    h.rooms = [RoomType(name="DBL"), RoomType(name="FAM")]
    rows = [r for r in map_extraction(_x([h])).supplement_rows
            if str(r.get("Supplement Code", "")).startswith("SUP-")]
    got = sorted((r["Rooms"], r["Charge Type"], r["Min Adult"], r["Max Adult"], r["Supplier Cost"]) for r in rows)
    assert got == [
        ("DBL", "Per Room Per Night", None, None, 40),
        ("FAM", "Per Room Per Night", 3, 3, 90),
        ("FAM", "Per Room Per Night", 4, 4, 120),
    ]


def test_same_dates_with_and_without_season_label_are_one_supplement() -> None:
    h = "Sea View Resort"
    x = _x([_hotel()], supplements=[
        _supp(h, name="Adult breakfast", start="2025-12-01", end="2027-03-31"),
        _supp(h, name="Adult breakfast", start="2025-12-01", end="2027-03-31", season="S1"),
    ])
    _finalize(x)
    assert len(x.supplements) == 1
