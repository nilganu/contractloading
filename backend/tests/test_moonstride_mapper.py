"""Unit tests for the deterministic Moonstride mapper.

All conditional rules (Standard/Count/Index blanking, Days mask, forced
Yes / blank fields, child-position columns, FareType Name derivation,
DD-MM-YYYY date formatting) are testable here with zero LLM involvement.
"""
from __future__ import annotations

from typing import List

from app.extraction.canonical import (
    ChildAgeBand, ContractExtraction, HotelExtraction, HotelMetadata,
    MealPlanEntry, Rate, RoomType, Season, Supplement,
)
from app.extraction.moonstride_mapper import (
    _compute_band_price, _format_cost, _format_dd_mm_yyyy,
    _generate_hotel_code, _resolve_fare_type_name,
    _resolve_standard_count_index, build_hotel_rows, build_supplement_rows,
    map_extraction,
)


def _minimal_hotel(name: str = "Test Hotel") -> HotelExtraction:
    return HotelExtraction(
        metadata=HotelMetadata(
            name=name, country_code="GR", city_area="Athens", currency="EUR",
            supplier="Test Supplier", code="TEST01",
        ),
        rooms=[RoomType(name="Standard Room", max_pax=2, max_adult=2, min_adult=1)],
        seasons=[Season(label="Summer", start_date="2025-05-01", end_date="2025-09-30")],
        meal_plans=[MealPlanEntry(code="BB", canonical="Bed and Breakfast")],
        rates=[Rate(
            room_name="Standard Room", season_label="Summer", meal_code="BB",
            sgl=100.0, dbl=160.0,
        )],
        child_policy=[],
    )


def _contract(hotels: List[HotelExtraction], supplements: List[Supplement] = None,
              rate_type: str = "Per Person Per Night") -> ContractExtraction:
    return ContractExtraction(
        source_filename="test.pdf", is_multi_hotel=len(hotels) > 1,
        detected_rate_type=rate_type, hotels=hotels,
        supplements=supplements or [], notes=[],
    )


# --- DD-MM-YYYY formatting ----------------------------------------------------

def test_format_dd_mm_yyyy_basic() -> None:
    assert _format_dd_mm_yyyy("2025-05-01") == "01-05-2025"
    assert _format_dd_mm_yyyy("2025-12-31") == "31-12-2025"


def test_format_dd_mm_yyyy_handles_none_and_garbage() -> None:
    assert _format_dd_mm_yyyy(None) is None
    assert _format_dd_mm_yyyy("") is None
    assert _format_dd_mm_yyyy("not-a-date") == "not-a-date"


# --- Standard/Count/Index blank-vs-value rule --------------------------------

def _supp(**kwargs):
    base = dict(
        name="Supp", hotel_name="Test Hotel", kind="meal_upgrade",
        charge_type="Per Person Per Night", calculation_method="Standard",
        traveler_type="Adult",
    )
    base.update(kwargs)
    return Supplement(**base)


def test_standard_count_index_blank_for_standard_and_ppn() -> None:
    s = _supp(calculation_method="Standard", charge_type="Per Person Per Night")
    assert _resolve_standard_count_index(s) is None


def test_standard_count_index_returns_ordinal_for_pax_count() -> None:
    s = _supp(calculation_method="Pax Count", ordinal=2)
    assert _resolve_standard_count_index(s) == 2


def test_standard_count_index_returns_ordinal_for_pax_index() -> None:
    s = _supp(calculation_method="Pax Index", ordinal=3)
    assert _resolve_standard_count_index(s) == 3


def test_standard_count_index_zero_for_pax_count_extra() -> None:
    s = _supp(calculation_method="Pax Count", ordinal=0)
    assert _resolve_standard_count_index(s) == 0


def test_standard_count_index_keeps_value_for_standard_non_ppn() -> None:
    # User rule: blank ONLY when Standard + Per Person Per Night.
    # Other Standard combinations keep their ordinal (typically null).
    s = _supp(calculation_method="Standard", charge_type="Per Room Per Night", ordinal=None)
    assert _resolve_standard_count_index(s) is None


# --- FareType Name derivation -------------------------------------------------

def test_fare_type_name_standard_adult() -> None:
    s = _supp(calculation_method="Standard", traveler_type="Adult")
    assert _resolve_fare_type_name(s) == "Per Adult"


def test_fare_type_name_standard_child() -> None:
    s = _supp(calculation_method="Standard", traveler_type="Child")
    assert _resolve_fare_type_name(s) == "Per Child"


def test_fare_type_name_standard_infant() -> None:
    s = _supp(calculation_method="Standard", traveler_type="Infant")
    assert _resolve_fare_type_name(s) == "Per Infant"


def test_fare_type_name_pax_count_uses_contract_label() -> None:
    s = _supp(calculation_method="Pax Count", fare_type_name="ABC Adult", ordinal=2)
    assert _resolve_fare_type_name(s) == "ABC Adult"


def test_fare_type_name_pax_index_uses_contract_label() -> None:
    s = _supp(calculation_method="Pax Index", fare_type_name="2nd Adult", ordinal=2)
    assert _resolve_fare_type_name(s) == "2nd Adult"


# --- Hotel row construction --------------------------------------------------

def test_build_hotel_rows_picks_ppn_template() -> None:
    template_id, rows = build_hotel_rows(_contract([_minimal_hotel()]))
    assert template_id == "moonstride_ppn"
    assert len(rows) == 1
    r = rows[0]
    assert r["Hotel Name"] == "Test Hotel"
    assert r["Room Name"] == "Standard Room"
    assert r["Adult 1 (SGL)"] == 100.0
    assert r["Adult 2 (DBL)"] == 160.0
    assert r["Days"] == "1234567"
    assert r["Status"] == "Open"
    assert r["Rate Type"] == "Per Person Per Night"
    assert r["Meal Plan"] == "Bed and Breakfast"
    assert r["Currency"] == "EUR"


def test_build_hotel_rows_per_room_picks_prn_ac() -> None:
    template_id, _ = build_hotel_rows(
        _contract([_minimal_hotel()], rate_type="Per Room Per Night")
    )
    assert template_id == "moonstride_prn_ac"


def test_build_hotel_rows_per_room_pax_count_picks_prn_pax() -> None:
    template_id, rows = build_hotel_rows(
        _contract([_minimal_hotel()], rate_type="Per Room Per Night (Pax Count)")
    )
    assert template_id == "moonstride_prn_pax"
    r = rows[0]
    # Pax layout emits 1 Pax / 2 Pax / ... columns instead of Adult 1-4.
    assert r["1 Pax"] == 100.0
    assert r["2 Pax"] == 160.0


def test_hotel_rows_omit_child_policy_columns() -> None:
    """Per Jun 2026 user rule: child policy lives in the supplement file
    as per-room "Child policy" rows, not in the hotel rate file. The
    hotel-row dicts must NOT carry the per-row Baby / Child / Teen
    band columns or the 1st/2nd/3rd Child Price/Age columns — those
    keys are absent so the Excel writer leaves the cells blank."""
    h = _minimal_hotel()
    h.rooms = [RoomType(name="Superior", max_pax=4)]
    h.seasons = [Season(label="High", start_date="2026-06-14", end_date="2026-08-31")]
    h.meal_plans = [MealPlanEntry(code="BB", canonical="Bed and Breakfast")]
    h.rates = [Rate(
        room_name="Superior", season_label="High", meal_code="BB",
        sgl=130, dbl=79,
    )]
    h.child_policy = [
        ChildAgeBand(position="first_child",  age_from=0.1, age_to=11.99,
                     value_type="discount_percentage", value=100),
        ChildAgeBand(position="second_child", age_from=2.0, age_to=11.99,
                     value_type="discount_percentage", value=50),
    ]
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    for forbidden in (
        "Baby 1 (0-1)", "Child 1 (2-12)", "Teen 1 (12-17)",
        "Multi Infant (0-1)", "Extra Child (2-12)", "Extra Teen (12-17)",
        "1st Child Price", "1st Child Age Min", "1st Child Age Max",
        "2nd Child Price", "2nd Child Age Min", "2nd Child Age Max",
        "3rd Child Price", "3rd Child Age Min", "3rd Child Age Max",
    ):
        assert forbidden not in r, f"hotel row leaked child column {forbidden!r}"


def test_extra_adult_discount_percentage_computed_from_row_adult_rate() -> None:
    """Extra Adult -30% on a row with per-person rate 43 -> 30.1 EUR."""
    h = _minimal_hotel()
    h.rates = [Rate(
        room_name="Standard Room", season_label="Summer", meal_code="BB",
        sgl=62, dbl=43,
        extra_bed_adult=30, extra_bed_adult_kind="discount_percentage",
    )]
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    assert r["Extra Adult"] == 30.1   # 43 * 0.7


def test_extra_adult_amount_kind_used_as_is() -> None:
    h = _minimal_hotel()
    h.rates = [Rate(
        room_name="Standard Room", season_label="Summer", meal_code="BB",
        sgl=100, dbl=160,
        extra_bed_adult=25, extra_bed_adult_kind="amount",
    )]
    _, rows = build_hotel_rows(_contract([h]))
    assert rows[0]["Extra Adult"] == 25


def test_child_policy_supplement_uses_cheapest_per_room_dbl() -> None:
    """Per Jun 2026 user rule: child policy is emitted as supplement
    rows tagged with a specific room name, not "ALL". The Supplier
    Cost on each row reflects that room's cheapest dbl rate; common
    name "Child policy"; type "Compulsory"."""
    h = _minimal_hotel()
    h.rooms = [
        RoomType(name="Standard", max_pax=4),
        RoomType(name="Deluxe", max_pax=4),
    ]
    h.seasons = [
        Season(label="Low", start_date="2026-04-01", end_date="2026-06-13"),
        Season(label="High", start_date="2026-06-14", end_date="2026-08-31"),
    ]
    h.rates = [
        Rate(room_name="Standard", season_label="Low",  meal_code="BB", dbl=43),
        Rate(room_name="Standard", season_label="High", meal_code="BB", dbl=79),
        Rate(room_name="Deluxe",   season_label="Low",  meal_code="BB", dbl=60),
        Rate(room_name="Deluxe",   season_label="High", meal_code="BB", dbl=100),
    ]
    h.child_policy = [
        ChildAgeBand(position="second_child", age_from=2, age_to=11.99,
                     value_type="discount_percentage", value=50),
    ]
    result = map_extraction(_contract([h]))
    child_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("CHILD-")
    ]
    by_room = {r["Rooms"]: r for r in child_rows}
    assert set(by_room) == {"Standard", "Deluxe"}
    # Standard's cheapest dbl=43 -> 50% discount = 21.5
    # Deluxe's   cheapest dbl=60 -> 50% discount = 30.0
    assert by_room["Standard"]["Supplier Cost"] == 21.5
    assert by_room["Deluxe"]["Supplier Cost"] == 30.0
    # Common name + Compulsory enforced
    for r in child_rows:
        assert r["Supplement Name"] == "Child policy"
        assert r["Supplement Type"] == "Compulsory"


def test_meal_plan_upgrade_supplements_derived_from_rates() -> None:
    """Acrotel-style scenario: BB + HB as alternate per-person prices.
    The mapper derives a Half-Board upgrade supplement for each
    (room, season) with delta = HB - BB."""
    h = _minimal_hotel()
    h.rooms = [RoomType(name="Superior", max_pax=4)]
    h.seasons = [Season(label="01.04-13.06", start_date="2026-04-01", end_date="2026-06-13")]
    h.meal_plans = [
        MealPlanEntry(code="BB", canonical="Bed and Breakfast"),
        MealPlanEntry(code="HB", canonical="Half board"),
    ]
    h.rates = [
        Rate(room_name="Superior", season_label="01.04-13.06", meal_code="BB", dbl=43),
        Rate(room_name="Superior", season_label="01.04-13.06", meal_code="HB", dbl=59),
    ]
    h.child_policy = [
        ChildAgeBand(age_from=2, age_to=11.99,
                     value_type="discount_percentage", value=50),
    ]
    result = map_extraction(_contract([h]))
    # Find the meal-plan-upgrade supplement(s) by Supplement Code prefix
    # (Supplement Type is now the Moonstride enum).
    derived = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("SUP-")
    ]
    # Adult row should exist with delta = 59 - 43 = 16.
    adult = [r for r in derived if r["Traveler Type"] == "Adult"]
    assert len(adult) == 1
    assert adult[0]["Supplier Cost"] == 16
    assert adult[0]["Customer Price"] == 16
    assert adult[0]["FareType Name"] == "Per Adult"
    assert adult[0]["Calculation Method"] == "Standard"
    assert adult[0]["Charge Type"] == "Per Person Per Night"
    assert adult[0]["Standard / Count / Index"] is None  # blanked for Std+PPN
    assert adult[0]["Display on Customer Documentation"] == "Yes"
    assert adult[0]["Display on Supplier Notification"] == "Yes"
    assert adult[0]["Season Name"] == "01.04-13.06"
    assert adult[0]["Rooms"] == "Superior"
    # Per Jun 2026 rule: meal-upgrade rows are Adult-only. No fabricated
    # Child row even though the hotel has a -50% child band — the
    # contract's child policy discounts the BASE rate, not the
    # meal-plan delta. Per-supplement child rules (e.g. gala dinner's
    # explicit child %) come from the LLM directly, not from this
    # derivation.
    child = [r for r in derived if r["Traveler Type"] == "Child"]
    assert child == []


def test_child_policy_supplements_charmillion_sea_life_scenario() -> None:
    """Charmillion Sea Life pattern: three child bands including two
    sub-bands at the 'second_child' position (free 0-5.99 + 50% 6-12.99).
    All three should appear as supplement rows with Pax Index, distinct
    Supplement Codes (so the importer can tell them apart), and computed
    costs based on the cheapest adult rate."""
    h = _minimal_hotel()
    h.rooms = [RoomType(name="Standard", max_pax=4)]
    h.seasons = [Season(label="Low", start_date="2026-04-01", end_date="2026-06-30")]
    h.meal_plans = [MealPlanEntry(code="AI", canonical="All inclusive")]
    h.rates = [Rate(room_name="Standard", season_label="Low", meal_code="AI", dbl=40)]
    h.child_policy = [
        ChildAgeBand(position="first_child",  age_from=0,   age_to=12.99,
                     value_type="discount_percentage", value=100),
        ChildAgeBand(position="second_child", age_from=0,   age_to=5.99,
                     value_type="discount_percentage", value=100),
        ChildAgeBand(position="second_child", age_from=6,   age_to=12.99,
                     value_type="discount_percentage", value=50),
    ]
    result = map_extraction(_contract([h]))
    child_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("CHILD-")
    ]
    assert len(child_rows) == 3, "should emit one row per child band"
    by_code = {r["Supplement Code"]: r for r in child_rows}
    # 1st child 0-12.99 free → cost 0
    r1 = by_code["CHILD-1-0-12.99"]
    assert r1["Standard / Count / Index"] == 1
    assert r1["Calculation Method"] == "Pax Index"
    assert r1["Charge Type"] == "Per Person Per Night"
    assert r1["Min Age"] == 0 and r1["Max Age"] == 12.99
    assert r1["Supplier Cost"] == 0
    assert r1["Traveler Type"] == "Child"
    # 2nd child 0-5.99 free → cost 0; counts as Infant (age_to <= 2 is the
    # rule; 5.99 > 2 so it stays as Child here — confirm the boundary).
    r2 = by_code["CHILD-2-0-5.99"]
    assert r2["Standard / Count / Index"] == 2
    assert r2["Supplier Cost"] == 0
    assert r2["Traveler Type"] == "Child"
    # 2nd child 6-12.99 -50% → cost = 40 * 0.5 = 20
    r3 = by_code["CHILD-2-6-12.99"]
    assert r3["Standard / Count / Index"] == 2  # same position index
    assert r3["Supplier Cost"] == 20
    # All three have the forced Yes/blank rules.
    for r in child_rows:
        assert r["Display on Customer Documentation"] == "Yes"
        assert r["Display on Supplier Notification"] == "Yes"
        assert r["Meal Plan"] is None
        assert r["Required Supplement"] is None
        assert r["Restricted Supplement"] is None
        assert r["Display As Separate Room"] == "No"


def test_meal_plan_upgrade_skipped_when_only_one_meal_plan() -> None:
    h = _minimal_hotel()  # only BB
    result = map_extraction(_contract([h]))
    derived = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("SUP-")
    ]
    assert derived == []


def test_build_hotel_rows_emits_min_stay_and_release_period() -> None:
    h = _minimal_hotel()
    h.seasons = [Season(
        label="Peak", start_date="2025-12-23", end_date="2026-01-05",
        min_stay=4, release_period=60,
    )]
    h.rates = [Rate(
        room_name="Standard Room", season_label="Peak", meal_code="BB",
        sgl=200, dbl=320,
    )]
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    assert r["Min Stay"] == 4
    assert r["Release Period"] == 60


def test_build_hotel_rows_emits_room_x_season_x_meal_combinations() -> None:
    h = _minimal_hotel()
    h.rooms = [RoomType(name="Room A", max_pax=2), RoomType(name="Room B", max_pax=3)]
    h.seasons = [
        Season(label="Low", start_date="2025-05-01", end_date="2025-06-30"),
        Season(label="High", start_date="2025-07-01", end_date="2025-08-31"),
    ]
    h.meal_plans = [
        MealPlanEntry(code="BB", canonical="Bed and Breakfast"),
        MealPlanEntry(code="HB", canonical="Half board"),
    ]
    h.rates = [
        Rate(room_name="Room A", season_label="Low", meal_code="BB", sgl=80, dbl=120),
    ]
    _, rows = build_hotel_rows(_contract([h]))
    # 2 rooms × 2 seasons × 2 meals = 8 rows.
    assert len(rows) == 8
    # Only one cell has prices; the rest are null on the rate columns.
    priced = [r for r in rows if r.get("Adult 2 (DBL)") == 120]
    assert len(priced) == 1
    null_priced = [r for r in rows if r.get("Adult 2 (DBL)") is None]
    assert len(null_priced) == 7


def test_build_hotel_rows_does_not_emit_per_position_child_columns() -> None:
    """Per Jun 2026 rule: child policy lives in the supplement file.
    Hotel rows must not populate per-position child columns."""
    h = _minimal_hotel()
    h.child_policy = [
        ChildAgeBand(
            position="first_child", label="1st Child", age_from=0, age_to=1.99,
            value_type="amount", value=0,
        ),
        ChildAgeBand(
            position="second_child", label="2nd Child", age_from=2, age_to=11.99,
            value_type="amount", value=30,
        ),
    ]
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    for forbidden in (
        "1st Child Price", "1st Child Age Min", "1st Child Age Max",
        "2nd Child Price", "2nd Child Age Min", "2nd Child Age Max",
        "3rd Child Price", "3rd Child Age Min", "3rd Child Age Max",
    ):
        assert forbidden not in r


def test_build_hotel_rows_does_not_emit_band_classified_rate_columns() -> None:
    """Per Jun 2026 rule: hotel rows omit Baby/Child/Teen and extras."""
    h = _minimal_hotel()
    h.child_policy = [
        ChildAgeBand(age_from=0, age_to=1.99, value_type="amount", value=0),
        ChildAgeBand(age_from=2, age_to=11.99, value_type="amount", value=25),
        ChildAgeBand(age_from=12, age_to=17.99, value_type="amount", value=60),
    ]
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    for forbidden in (
        "Baby 1 (0-1)", "Child 1 (2-12)", "Teen 1 (12-17)",
        "Multi Infant (0-1)", "Extra Child (2-12)", "Extra Teen (12-17)",
    ):
        assert forbidden not in r


def test_build_hotel_rows_multi_hotel() -> None:
    h1 = _minimal_hotel(name="Alpha Resort")
    h2 = _minimal_hotel(name="Beta Resort")
    _, rows = build_hotel_rows(_contract([h1, h2]))
    assert len(rows) == 2
    names = {r["Hotel Name"] for r in rows}
    assert names == {"Alpha Resort", "Beta Resort"}


# --- Supplement row construction --------------------------------------------

def test_build_supplement_rows_force_yes_values() -> None:
    h = _minimal_hotel()
    s = _supp()
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    assert len(rows) == 1
    r = rows[0]
    assert r["Display on Customer Documentation"] == "Yes"
    assert r["Display on Supplier Notification"] == "Yes"


def test_build_supplement_rows_force_blank_values() -> None:
    h = _minimal_hotel()
    s = _supp()
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    r = rows[0]
    assert r["Meal Plan"] is None
    assert r["Required Supplement"] is None
    assert r["Restricted Supplement"] is None


def test_build_supplement_rows_default_no_for_display_as_separate_room() -> None:
    h = _minimal_hotel()
    s = _supp()
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    assert rows[0]["Display As Separate Room"] == "No"


def test_build_supplement_rows_date_formatting() -> None:
    h = _minimal_hotel()
    s = _supp(start_date="2025-12-23", end_date="2026-01-05")
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    r = rows[0]
    assert r["Start Date (DD-MM-YYYY)"] == "23-12-2025"
    assert r["End Date (DD-MM-YYYY)"] == "05-01-2026"


def test_build_supplement_rows_hotel_name_lookup() -> None:
    """Supplements pull supplier/currency/code from the matching hotel."""
    h = _minimal_hotel(name="Lookup Hotel")
    h.metadata.supplier = "Travel Co"
    h.metadata.code = "LUH99"
    h.metadata.currency = "USD"
    s = _supp(hotel_name="Lookup Hotel")
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    r = rows[0]
    assert r["Hotel Code"] == "LUH99"
    assert r["Supplier"] == "Travel Co"
    assert r["Currency"] == "USD"


def test_build_supplement_rows_customer_price_defaults_to_supplier_cost() -> None:
    h = _minimal_hotel()
    s = _supp(supplier_cost=42.0, customer_price=None)
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    assert rows[0]["Customer Price"] == 42.0


# --- _compute_band_price safety net ------------------------------------------

def test_compute_band_price_discount_percentage_free() -> None:
    """100% off (free) renders price 0 regardless of adult rate."""
    b = ChildAgeBand(age_from=0, age_to=12.99, value_type="discount_percentage", value=100)
    assert _compute_band_price(b, adult_rate=41.0) == 0
    assert _compute_band_price(b, adult_rate=None) == 0


def test_compute_band_price_discount_percentage_half() -> None:
    b = ChildAgeBand(age_from=6, age_to=12.99, value_type="discount_percentage", value=50)
    assert _compute_band_price(b, adult_rate=41.0) == 20.5


def test_compute_band_price_percentage_of_adult_normal() -> None:
    """percentage_of_adult=50 means child pays 50% of adult — same math as
    discount_percentage=50 here, but conceptually different."""
    b = ChildAgeBand(age_from=3, age_to=12.99, value_type="percentage_of_adult", value=50)
    assert _compute_band_price(b, adult_rate=41.0) == 20.5


def test_compute_band_price_percentage_of_adult_100_treated_as_free() -> None:
    """Regression: the LLM has been misreading the contract convention
    'value=1 means 100% free' as percentage_of_adult=100. That would
    literally mean the child pays the full adult rate, which is never
    what a child policy says. The mapper now treats >=100 as free."""
    b = ChildAgeBand(age_from=0, age_to=12.99, value_type="percentage_of_adult", value=100)
    assert _compute_band_price(b, adult_rate=41.0) == 0


def test_compute_band_price_not_applicable_returns_none() -> None:
    b = ChildAgeBand(age_from=0, age_to=12.99, value_type="not_applicable", value=None)
    assert _compute_band_price(b, adult_rate=41.0) is None


# --- Hotel code generation ---


def test_generate_hotel_code_returns_six_alphanumeric_uppercase() -> None:
    code = _generate_hotel_code("Barceló Tiran Sharm Resort")
    assert len(code) == 6
    assert code.isalnum()
    assert code == code.upper(), "code must be uppercase"
    valid = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    assert all(c in valid for c in code), f"code uses invalid char: {code!r}"


def test_generate_hotel_code_is_deterministic() -> None:
    """Same name → same code across runs and trims/case variants
    normalised the same way."""
    a = _generate_hotel_code("Charmillion Garden Resort")
    b = _generate_hotel_code("Charmillion Garden Resort")
    c = _generate_hotel_code("  charmillion garden resort  ")
    assert a == b == c


def test_generate_hotel_code_different_names_differ() -> None:
    a = _generate_hotel_code("Hotel Alpha")
    b = _generate_hotel_code("Hotel Beta")
    assert a != b


def test_generate_hotel_code_handles_empty_name() -> None:
    assert _generate_hotel_code(None) == "000000"
    assert _generate_hotel_code("") == "000000"
    assert _generate_hotel_code("   ") == "000000"


def test_hotel_rows_get_generated_code_when_metadata_code_is_null() -> None:
    h = _minimal_hotel(name="Mövenpick Resort Sharm El Sheikh")
    h.metadata.code = None
    _, rows = build_hotel_rows(_contract([h]))
    assert rows
    code = rows[0]["Hotel Code"]
    assert isinstance(code, str) and len(code) == 6 and code.isalnum() and code == code.upper()


def test_hotel_rows_keep_explicit_metadata_code() -> None:
    h = _minimal_hotel()
    h.metadata.code = "ABC123"
    _, rows = build_hotel_rows(_contract([h]))
    assert rows[0]["Hotel Code"] == "ABC123"


# --- AI-fill marker stripping ---


def test_ai_prefix_stripped_from_metadata_value_and_recorded() -> None:
    """LLM emits '[AI] Naama Bay, Sharm' — mapper strips the prefix
    and records 'Address Line 1' in the row's _ai_fields side-channel
    so the writer can recolour the cell."""
    h = _minimal_hotel()
    h.metadata.address_line_1 = "[AI] Naama Bay, Sharm El Sheikh"
    h.metadata.phone = "[AI] +20 69 360 0100"
    h.metadata.city_area = "Sharm El Sheikh"  # contract-derived, no prefix
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    assert r["Address Line 1"] == "Naama Bay, Sharm El Sheikh"  # prefix gone
    assert r["Phone Number"] == "+20 69 360 0100"
    assert r["City / Area"] == "Sharm El Sheikh"  # unchanged
    assert r["_ai_fields"] == {"Address Line 1", "Phone Number"}


def test_ai_prefix_absent_when_no_metadata_was_ai_filled() -> None:
    h = _minimal_hotel()
    h.metadata.address_line_1 = "Plain Street 7"  # contract-given, no prefix
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    assert r["Address Line 1"] == "Plain Street 7"
    assert r["_ai_fields"] == set()


def test_lat_long_auto_flagged_as_ai_when_populated() -> None:
    """Numeric fields can't carry the [AI] prefix. Any non-null
    latitude/longitude is treated as AI-derived (contracts effectively
    never list geo-coords)."""
    h = _minimal_hotel()
    h.metadata.latitude = 27.913
    h.metadata.longitude = 34.327
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    assert r["Latitude"] == 27.913
    assert r["Longitude"] == 34.327
    assert "Latitude" in r["_ai_fields"]
    assert "Longitude" in r["_ai_fields"]


def test_lat_long_not_flagged_when_null() -> None:
    h = _minimal_hotel()
    h.metadata.latitude = None
    h.metadata.longitude = None
    _, rows = build_hotel_rows(_contract([h]))
    r = rows[0]
    assert "Latitude" not in r["_ai_fields"]
    assert "Longitude" not in r["_ai_fields"]


def test_supplement_rows_carry_room_occupancy_fields() -> None:
    """Per Jun 2026 user rule: supplement rows include Min Adult /
    Max Adult / Max Child, populated from the matching room's
    occupancy limits when the supplement is scoped to a specific
    room (e.g. a per-room view supplement or per-room child policy)."""
    h = _minimal_hotel()
    h.rooms = [
        RoomType(name="Family Suite", min_adult=2, max_adult=4,
                 max_pax=6, max_children=3),
        RoomType(name="Standard Room", min_adult=1, max_adult=2,
                 max_pax=2, max_children=1),
    ]
    h.rates = [
        Rate(room_name="Family Suite", season_label="Summer",
             meal_code="BB", dbl=60),
        Rate(room_name="Standard Room", season_label="Summer",
             meal_code="BB", dbl=40),
    ]
    h.child_policy = [
        ChildAgeBand(position="first_child", age_from=2, age_to=11.99,
                     value_type="discount_percentage", value=50),
    ]
    # Use a non-view-supplement name + kind so the new room-view
    # heuristic doesn't drop the row.
    s = Supplement(
        name="Family Suite minibar pack", hotel_name="Test Hotel",
        kind="other", charge_type="Per Person Per Night",
        calculation_method="Standard", traveler_type="Adult",
        rooms="Family Suite", supplier_cost=14,
    )
    result = map_extraction(_contract([h], supplements=[s]))
    by_room: dict = {}
    for r in result.supplement_rows:
        by_room.setdefault(r.get("Rooms"), []).append(r)
    # The LLM-emitted Family Suite supplement carries Family Suite's
    # occupancy limits.
    fam = [r for r in by_room["Family Suite"]
           if str(r.get("Supplement Code") or "") == ""][0]
    assert fam["Min Adult"] == 2
    assert fam["Max Adult"] == 4
    assert fam["Max Child"] == 3
    # The derived per-room child-policy rows inherit each room's
    # own occupancy limits.
    fam_child = next(r for r in by_room["Family Suite"]
                     if str(r.get("Supplement Code") or "").startswith("CHILD-"))
    std_child = next(r for r in by_room["Standard Room"]
                     if str(r.get("Supplement Code") or "").startswith("CHILD-"))
    assert fam_child["Min Adult"] == 2 and fam_child["Max Child"] == 3
    assert std_child["Min Adult"] == 1 and std_child["Max Child"] == 1


def test_format_cost_percentage_renders_as_string() -> None:
    assert _format_cost(50, "percentage") == "50%"
    assert _format_cost(15.0, "percentage") == "15%"  # integer-valued float
    assert _format_cost(12.5, "percentage") == "12.5%"
    assert _format_cost(None, "percentage") is None


def test_format_cost_amount_passes_through() -> None:
    assert _format_cost(50, "amount") == 50
    assert _format_cost(12.5, "amount") == 12.5
    assert _format_cost(None, "amount") is None


def test_supplement_row_renders_percentage_cost_as_string() -> None:
    """Single Room Supplement at 50% must reach the Excel as '50%',
    not as the numeric 50 (which loses the % meaning)."""
    h = _minimal_hotel()
    s = Supplement(
        name="Single Room Supplement", hotel_name="Test Hotel",
        kind="single_room", charge_type="Per Person Per Night",
        calculation_method="Standard", traveler_type="Adult",
        supplier_cost=50, cost_format="percentage",
    )
    rows = build_supplement_rows(_contract([h], supplements=[s]))
    assert rows[0]["Supplier Cost"] == "50%"
    assert rows[0]["Customer Price"] == "50%"


def test_room_view_supplement_omitted_from_supplement_file() -> None:
    """Per Jun 2026 user rule: kind='room_view' supplements live on
    the hotel side only. They must not appear in the supplement file."""
    h = _minimal_hotel()
    rv = Supplement(
        name="FAM PV Supp.", hotel_name="Test Hotel",
        kind="room_view", charge_type="Per Person Per Night",
        calculation_method="Standard", traveler_type="Adult",
        supplier_cost=9,
    )
    gala = Supplement(
        name="X-Mass Gala", hotel_name="Test Hotel",
        kind="gala_dinner", charge_type="Per Person Per Night",
        calculation_method="Standard", traveler_type="Adult",
        supplier_cost=50,
    )
    rows = build_supplement_rows(_contract([h], supplements=[rv, gala]))
    names = [r["Supplement Name"] for r in rows]
    assert "X-Mass Gala" in names
    assert "FAM PV Supp." not in names


def test_view_supplement_heuristic_catches_other_kind() -> None:
    """Safety net: when the LLM emits a view supplement with the
    generic kind='other', the name pattern still catches it."""
    h = _minimal_hotel()
    rows = build_supplement_rows(_contract([h], supplements=[
        Supplement(
            name="FAM Suite GV Supp.", hotel_name="Test Hotel",
            kind="other", charge_type="Per Person Per Night",
            calculation_method="Standard", traveler_type="Adult",
            supplier_cost=13,
        ),
        Supplement(
            name="Pool View Supp.", hotel_name="Test Hotel",
            kind="other", charge_type="Per Person Per Night",
            calculation_method="Standard", traveler_type="Adult",
            supplier_cost=3,
        ),
        Supplement(
            name="Single Room Supplement", hotel_name="Test Hotel",
            kind="single_room", charge_type="Per Person Per Night",
            calculation_method="Standard", traveler_type="Adult",
            supplier_cost=50, cost_format="percentage",
        ),
    ]))
    names = [r["Supplement Name"] for r in rows]
    assert "Single Room Supplement" in names  # genuine extra, kept
    assert "FAM Suite GV Supp." not in names  # view, dropped
    assert "Pool View Supp." not in names      # view, dropped


def test_meal_plan_upgrade_does_not_fabricate_child_or_infant_rows() -> None:
    """Per Jun 2026 user rule: meal-plan upgrade supplements emit ONLY
    Adult rows. Don't fabricate a Child row by applying the hotel's
    general child policy to the upgrade delta — the contract's child
    policy discounts the BASE rate, not the meal-plan delta."""
    h = _minimal_hotel()
    h.rooms = [RoomType(name="Standard", max_pax=4)]
    h.seasons = [Season(label="High", start_date="2026-06-14", end_date="2026-08-31")]
    h.meal_plans = [
        MealPlanEntry(code="BB", canonical="Bed and Breakfast"),
        MealPlanEntry(code="HB", canonical="Half board"),
    ]
    h.rates = [
        Rate(room_name="Standard", season_label="High", meal_code="BB", dbl=40),
        Rate(room_name="Standard", season_label="High", meal_code="HB", dbl=56),
    ]
    h.child_policy = [
        ChildAgeBand(position="first_child", age_from=2, age_to=11.99,
                     value_type="discount_percentage", value=50),
    ]
    result = map_extraction(_contract([h]))
    meal_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("SUP-")
    ]
    travelers = {r["Traveler Type"] for r in meal_rows}
    assert travelers == {"Adult"}, (
        f"meal-upgrade rows must be Adult-only; saw {travelers}"
    )
    assert all(r["Supplier Cost"] == 16 for r in meal_rows)


def test_child_policy_applies_to_rooms_filters_per_band() -> None:
    """Acrotel-style: contract gives 1st child free + 2nd child -50%
    for Superior + Family but n/a for Double. The band carries
    ``applies_to_rooms=['Superior Room', 'Family Room']`` and the
    mapper emits no Child policy row for Double Room."""
    h = _minimal_hotel()
    h.rooms = [
        RoomType(name="Double Room", max_pax=2),
        RoomType(name="Superior Room", max_pax=4),
        RoomType(name="Family Room", max_pax=4),
    ]
    h.rates = [
        Rate(room_name="Double Room",   season_label="Summer", meal_code="BB", dbl=34),
        Rate(room_name="Superior Room", season_label="Summer", meal_code="BB", dbl=43),
        Rate(room_name="Family Room",   season_label="Summer", meal_code="BB", dbl=54),
    ]
    h.child_policy = [
        ChildAgeBand(
            position="first_child", age_from=0.1, age_to=11.99,
            value_type="discount_percentage", value=100,
            applies_to_rooms=["Superior Room", "Family Room"],
        ),
        ChildAgeBand(
            position="second_child", age_from=2, age_to=11.99,
            value_type="discount_percentage", value=50,
            applies_to_rooms=["Superior Room", "Family Room"],
        ),
    ]
    result = map_extraction(_contract([h]))
    child_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("CHILD-")
    ]
    rooms_with_rows = {r["Rooms"] for r in child_rows}
    assert "Double Room" not in rooms_with_rows
    assert rooms_with_rows == {"Superior Room", "Family Room"}
    # Costs reflect each room's own rate, both bands at 50% (or 100% for free).
    sup_first = next(r for r in child_rows
                     if r["Rooms"] == "Superior Room" and r["Supplement Code"] == "CHILD-1-0.1-11.99")
    sup_second = next(r for r in child_rows
                      if r["Rooms"] == "Superior Room" and r["Supplement Code"] == "CHILD-2-2-11.99")
    assert sup_first["Supplier Cost"] == 0       # free
    assert sup_second["Supplier Cost"] == 21.5   # 50% of 43


def test_child_policy_applies_to_rooms_falls_back_to_all_when_no_match() -> None:
    """If the LLM typo'd a room name, don't silently drop the band —
    fall back to applying it to all rooms."""
    h = _minimal_hotel()
    h.rooms = [RoomType(name="Standard Room", max_pax=2)]
    h.rates = [
        Rate(room_name="Standard Room", season_label="Summer",
             meal_code="BB", dbl=40),
    ]
    h.child_policy = [
        ChildAgeBand(
            position="first_child", age_from=2, age_to=11.99,
            value_type="discount_percentage", value=50,
            applies_to_rooms=["WrongName"],  # typo
        ),
    ]
    result = map_extraction(_contract([h]))
    child_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("CHILD-")
    ]
    assert len(child_rows) == 1
    assert child_rows[0]["Rooms"] == "Standard Room"


def test_child_policy_not_applicable_band_produces_no_supplement_rows() -> None:
    """Bands the LLM emits as ``value_type="not_applicable"`` MUST NOT
    produce supplement rows — they would just be empty-cost junk.
    Acrotel pattern: 3rd child 2-11.99 = n/a for all rooms; that band
    should be silently dropped."""
    h = _minimal_hotel()
    h.rooms = [
        RoomType(name="Double", max_pax=2),
        RoomType(name="Superior", max_pax=4),
    ]
    h.rates = [
        Rate(room_name="Double", season_label="Summer", meal_code="BB", dbl=34),
        Rate(room_name="Superior", season_label="Summer", meal_code="BB", dbl=43),
    ]
    h.child_policy = [
        ChildAgeBand(position="first_child", age_from=0.1, age_to=11.99,
                     value_type="discount_percentage", value=100),  # free
        ChildAgeBand(position="third_child", age_from=2, age_to=11.99,
                     value_type="not_applicable"),                    # n/a
    ]
    result = map_extraction(_contract([h]))
    child_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("CHILD-")
    ]
    # 1st child band × 2 rooms = 2 rows; 3rd-child n/a band drops entirely.
    assert len(child_rows) == 2
    codes = {r["Supplement Code"] for r in child_rows}
    assert codes == {"CHILD-1-0.1-11.99"}


def test_child_policy_overrides_misclassified_view_room_rate() -> None:
    """Volonline-style bug: LLM treats a view-supplement column as a
    separate room with dbl = 3 EUR. Child policy at 50% should not
    emit 1.5 EUR — the safety net substitutes the hotel-wide max so
    the cost reflects a real accommodation price."""
    h = _minimal_hotel()
    h.rooms = [
        RoomType(name="SUP GV", max_pax=2),
        RoomType(name="SUP PV", max_pax=2),   # actually a view supplement
        RoomType(name="SUP SSV", max_pax=2),  # ditto
    ]
    h.seasons = [Season(label="Winter", start_date="2025-11-01", end_date="2026-04-30")]
    h.rates = [
        Rate(room_name="SUP GV",  season_label="Winter", meal_code="BB", dbl=40),
        Rate(room_name="SUP PV",  season_label="Winter", meal_code="BB", dbl=3),  # bogus
        Rate(room_name="SUP SSV", season_label="Winter", meal_code="BB", dbl=5),  # bogus
    ]
    h.child_policy = [
        ChildAgeBand(position="first_child", age_from=6, age_to=10.99,
                     value_type="discount_percentage", value=50),
    ]
    result = map_extraction(_contract([h]))
    child_rows = [
        r for r in result.supplement_rows
        if str(r.get("Supplement Code") or "").startswith("CHILD-")
    ]
    by_room = {r["Rooms"]: r for r in child_rows}
    # SUP GV stays at its own rate × 50%
    assert by_room["SUP GV"]["Supplier Cost"] == 20
    # Misclassified rooms inherit the hotel-wide max (40) instead of their
    # own bogus low rate.
    assert by_room["SUP PV"]["Supplier Cost"] == 20
    assert by_room["SUP SSV"]["Supplier Cost"] == 20


# --- End-to-end ---

def test_map_extraction_returns_both_arrays() -> None:
    h = _minimal_hotel()
    h.child_policy = [
        ChildAgeBand(age_from=2, age_to=11.99, value_type="amount", value=25),
    ]
    s = _supp(calculation_method="Pax Count", ordinal=1, fare_type_name="1 Adult",
              supplier_cost=10)
    result = map_extraction(_contract([h], supplements=[s]))
    assert result.template_id == "moonstride_ppn"
    assert len(result.hotel_rows) == 1
    # LLM-extracted supplements vs derived ones (distinguished by code).
    llm_supps = [
        r for r in result.supplement_rows
        if not str(r.get("Supplement Code") or "").startswith(("SUP-", "CHILD-"))
    ]
    assert len(llm_supps) == 1
    assert llm_supps[0]["Standard / Count / Index"] == 1
    assert llm_supps[0]["FareType Name"] == "1 Adult"
