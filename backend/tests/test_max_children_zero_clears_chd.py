"""When the occupancy table says Max Children = 0 for a room, every CHD
column on that row's hotel-row MUST be null — even if the rate-table
block carries a child policy that applies to other rooms.
"""
from __future__ import annotations

from app.services.structured_excel_extractor import _apply_occupancy


def test_max_children_zero_clears_all_chd() -> None:
    row = {
        "Room Name": "JUN Suite GV / Couple Only",
        "Min Adult": None, "Max Adult": None, "Max Pax": None,
        "dynamicChildValues": {
            "CHD1(0-5.99)": 70,
            "CHD2(0-5.99)": 35,
            "CHD1(6-10.99)": 35,
            "CHD2(6-10.99)": 52.5,
        },
    }
    occupancy = [
        {
            "room_name": "JUN SUITE GV (Couple Only)",
            "min_adult": 2, "max_adult": 2, "max_pax": 2, "max_child": 0,
        },
    ]
    _apply_occupancy(row, "JUN Suite GV / Couple Only", occupancy)

    assert row["Min Adult"] == 2
    assert row["Max Adult"] == 2
    assert row["Max Pax"] == 2
    # Every CHD value cleared
    assert all(v is None for v in row["dynamicChildValues"].values())
    # Warning recorded so reviewers see why
    assert any("Max Children = 0" in w for w in row["_warnings"])


def test_max_children_nonzero_preserves_chd() -> None:
    row = {
        "Room Name": "SUPERIOR GV",
        "Min Adult": None, "Max Adult": None, "Max Pax": None,
        "dynamicChildValues": {"CHD1(0-5.99)": 40, "CHD2(6-10.99)": 30},
    }
    occupancy = [
        {"room_name": "SUP GV", "min_adult": 1, "max_adult": 3, "max_pax": 3, "max_child": 2},
    ]
    _apply_occupancy(row, "SUPERIOR GV", occupancy)
    # CHD values intact
    assert row["dynamicChildValues"]["CHD1(0-5.99)"] == 40
    assert row["dynamicChildValues"]["CHD2(6-10.99)"] == 30


def test_max_children_missing_preserves_chd() -> None:
    """If the occupancy entry has no max_child key, leave CHD values alone."""
    row = {
        "Room Name": "Room",
        "Min Adult": None, "Max Adult": None, "Max Pax": None,
        "dynamicChildValues": {"CHD1(0-5.99)": 40},
    }
    occupancy = [{"room_name": "Room", "min_adult": 1, "max_adult": 3, "max_pax": 3}]
    _apply_occupancy(row, "Room", occupancy)
    assert row["dynamicChildValues"]["CHD1(0-5.99)"] == 40
