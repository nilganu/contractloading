"""Tests for fuzzy room-name matching against the occupancy table."""
from __future__ import annotations

from app.services.structured_excel_extractor import _apply_occupancy, _room_tokens


def test_tokens_normalize_abbreviations() -> None:
    assert _room_tokens("SUP GV") == {"superior", "gardenview"}
    assert _room_tokens("SUPERIOR GV") == {"superior", "gardenview"}
    assert _room_tokens("Fam SSV") == {"family", "seasideview"}
    assert _room_tokens("DLX SWIM UP") == {"deluxe", "swim", "up"}
    assert _room_tokens("JUN Suite GV / Couple Only") >= {"junior", "suite", "gardenview"}


def test_apply_occupancy_matches_abbreviation_to_long_form() -> None:
    occupancy = [
        {"room_name": "SUP GV", "min_adult": 1, "max_adult": 3, "max_pax": 3},
        {"room_name": "SUP PV", "min_adult": 1, "max_adult": 3, "max_pax": 3},
        {"room_name": "FAM SSV", "min_adult": 2, "max_adult": 4, "max_pax": 4},
    ]
    row = {"Min Adult": None, "Max Adult": None, "Max Pax": None}
    _apply_occupancy(row, "SUPERIOR GV", occupancy)
    assert row["Min Adult"] == 1
    assert row["Max Adult"] == 3
    assert row["Max Pax"] == 3


def test_apply_occupancy_matches_long_form_to_abbreviation() -> None:
    occupancy = [
        {"room_name": "Superior Garden View", "min_adult": 1, "max_adult": 3, "max_pax": 3},
    ]
    row = {"Min Adult": None, "Max Adult": None, "Max Pax": None}
    _apply_occupancy(row, "SUP GV", occupancy)
    assert row["Max Adult"] == 3


def test_apply_occupancy_does_not_overwrite_existing_values() -> None:
    occupancy = [{"room_name": "Sup GV", "min_adult": 1, "max_adult": 3, "max_pax": 3}]
    row = {"Min Adult": 2, "Max Adult": None, "Max Pax": None}
    _apply_occupancy(row, "SUPERIOR GV", occupancy)
    assert row["Min Adult"] == 2  # untouched
    assert row["Max Adult"] == 3  # filled


def test_apply_occupancy_no_match_leaves_blanks() -> None:
    occupancy = [{"room_name": "Garden View", "min_adult": 1, "max_adult": 3, "max_pax": 3}]
    row = {"Min Adult": None, "Max Adult": None, "Max Pax": None}
    _apply_occupancy(row, "Beach Front", occupancy)
    assert row["Min Adult"] is None
    assert row["Max Adult"] is None
