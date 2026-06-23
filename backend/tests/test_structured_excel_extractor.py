"""Tests for the deterministic structured Excel extractor.

The LLM call (column-map) is mocked. The Python row-expansion logic is
fully exercised — it's the part that has to be correct.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.structured_excel_extractor import (
    _compute_sgl,
    _compute_tpl,
    _expand_block,
)


def _cell(v: Any) -> Dict[str, Any]:
    return {"value": v, "row": 0, "col": 0, "type": None, "style": None}


def _row(*vals: Any) -> List[Dict[str, Any]]:
    return [_cell(v) for v in vals]


def test_sgl_supplement_as_multiplier() -> None:
    """0 < supp < 1 means decimal multiplier (+supp×100% of base)."""
    assert _compute_sgl(40, 0.7) == 68.0      # 40 * 1.7
    assert _compute_sgl(50, 0.5) == 75.0      # 50 * 1.5


def test_sgl_supplement_as_amount() -> None:
    """supp >= 1 means EUR amount added directly (typical when the
    contract uses bare currency, eg "+25 EUR / night")."""
    assert _compute_sgl(40, 10) == 50.0
    assert _compute_sgl(100, 25.5) == 125.5
    assert _compute_sgl(40, 2) == 42.0  # 2 EUR amount (boundary)
    assert _compute_sgl(100, 1.0) == 101.0  # 1 = amount, +1 EUR


def test_sgl_supplement_none_returns_none() -> None:
    assert _compute_sgl(40, None) is None


def test_tpl_reduction_as_amount() -> None:
    """Most Volonline-style contracts: reduction is bare EUR amount.
    Result must be base − reduction (per-person)."""
    assert _compute_tpl(40, 2) == 38.0
    assert _compute_tpl(80, 10) == 70.0


def test_tpl_reduction_as_multiplier() -> None:
    """0 < reduct < 5 -> decimal multiplier (1 - reduct)."""
    assert _compute_tpl(100, 0.1) == 90.0


def test_expand_block_iterates_every_date_row_and_every_upgrade() -> None:
    """The whole point of the deterministic extractor — produce 1 + N rows
    per date row where N is the number of upgrade columns with values."""
    # Build a 4-date-row block with 1 base column + 2 upgrade columns.
    rows: List[List[Dict[str, Any]]] = []
    # row 0 — header (won't be touched since first_data_row_idx is 1)
    rows.append(_row("FROM", "TO", "release", "SUPERIOR GV", "SGL Supp", "TPL Red", "1st child", "SUP PV", "Beach Front"))
    # 4 data rows
    rows.append(_row("2025-11-01", "2025-11-14", 5, 40, 0.7, 2, 0.5, 3, 10))
    rows.append(_row("2025-11-15", "2025-12-20", 7, 38, 0.7, 2, 0.5, 3, 10))
    rows.append(_row("2025-12-21", "2025-12-27", 10, 40, 0.7, 2, 0.5, 3, 10))
    rows.append(_row("2025-12-28", "2026-01-03", 5, 50, 0.7, 2, 0.5, 3, 10))

    block = {
        "title": "Booking Window 18.07-31.10",
        "header_row_idx": 0,
        "first_data_row_idx": 1,
        "last_data_row_idx": 4,
        "columns": {
            "date_from": 0, "date_to": 1, "release": 2,
            "base_room": 3, "base_room_label": "SUPERIOR GV",
            "sgl_supp": 4, "tpl_reduct": 5,
            "qdp_reduct": None, "extra_bed": None,
            "child_cols": [
                {"col_idx": 6, "position": "first_child", "age_from": 0, "age_to": 5.99,
                 "value_type": "percentage_of_adult"},
            ],
            "upgrade_cols": [
                {"col_idx": 7, "label": "SUP PV"},
                {"col_idx": 8, "label": "Beach Front"},
            ],
            "meal_upgrade_cols": [],
            "note_cols": [],
        },
    }
    meta = {"name": "Test Hotel", "currency": "EUR", "basic_treatment": "All Inclusive"}
    occupancy = []
    options = {"statusDefault": "Open"}

    hotel_rows, dynamic_cols = _expand_block(
        rows, block, meta, occupancy, options, "Sheet1", "test.xlsx"
    )

    # 4 date rows × 3 rooms (1 base + 2 upgrades) = 12 rows
    assert len(hotel_rows) == 12, [r["Room Name"] + " " + str(r["Start Date"]) for r in hotel_rows]

    # Check distinct date pairs
    date_pairs = sorted({(r["Start Date"], r["End Date"]) for r in hotel_rows})
    assert date_pairs == [
        ("2025-11-01", "2025-11-14"),
        ("2025-11-15", "2025-12-20"),
        ("2025-12-21", "2025-12-27"),
        ("2025-12-28", "2026-01-03"),
    ]

    # First date row, base room
    r0 = next(r for r in hotel_rows if r["Room Name"] == "SUPERIOR GV" and r["Start Date"] == "2025-11-01")
    assert r0["DBL"] == 40
    assert r0["SGL"] == 68.0  # 40 * 1.7
    assert r0["TPL"] == 38.0  # 40 - 2
    assert r0["Days"] == "1234567"  # Moonstride weekday mask, all days
    assert r0["Rate Plan"] == "Booking Window 18.07-31.10"
    assert r0["Meal Plan"] == "All Inclusive"
    assert r0["Hotel Name"] == "Test Hotel"
    assert r0["Currency"] == "EUR"

    # First date row, SUP PV upgrade
    r_sup = next(r for r in hotel_rows if r["Room Name"] == "SUP PV" and r["Start Date"] == "2025-11-01")
    assert r_sup["DBL"] == 43  # 40 + 3
    assert r_sup["SGL"] == 73.1  # 43 * 1.7

    # Beach Front upgrade
    r_bf = next(r for r in hotel_rows if r["Room Name"] == "Beach Front" and r["Start Date"] == "2025-11-01")
    assert r_bf["DBL"] == 50  # 40 + 10
    assert r_bf["SGL"] == 85.0  # 50 * 1.7

    # Different date row should use that row's base price
    r3 = next(r for r in hotel_rows if r["Room Name"] == "SUPERIOR GV" and r["Start Date"] == "2025-12-28")
    assert r3["DBL"] == 50  # 4th data row's base
    assert r3["SGL"] == 85.0  # 50 * 1.7

    # Dynamic CHD column emitted
    assert dynamic_cols
    assert dynamic_cols[0]["key"] == "CHD1(0-5.99)"
    assert dynamic_cols[0]["valueType"] == "percentage_of_adult"

    # Each row's dynamicChildValues populated with the cell value
    for r in hotel_rows:
        assert r["dynamicChildValues"]["CHD1(0-5.99)"] == 0.5


def test_expand_block_skips_blank_or_missing_data_rows() -> None:
    rows: List[List[Dict[str, Any]]] = []
    rows.append(_row("FROM", "TO", "SUPERIOR GV"))
    rows.append(_row("2025-11-01", "2025-11-14", 40))
    rows.append(_row(None, None, None))           # blank — should be skipped
    rows.append(_row("2025-12-21", "2025-12-27", 50))
    block = {
        "title": "Block",
        "header_row_idx": 0, "first_data_row_idx": 1, "last_data_row_idx": 3,
        "columns": {
            "date_from": 0, "date_to": 1, "base_room": 2,
            "base_room_label": "SUPERIOR GV",
            "child_cols": [], "upgrade_cols": [],
            "meal_upgrade_cols": [], "note_cols": [],
        },
    }
    hotel_rows, _ = _expand_block(rows, block, {"name": "X"}, [], {}, "S", "f.xlsx")
    assert len(hotel_rows) == 2  # blank skipped


def test_expand_block_applies_occupancy_match() -> None:
    rows = [
        _row("FROM", "TO", "SUPERIOR GV"),
        _row("2025-11-01", "2025-11-14", 40),
    ]
    block = {
        "title": "Block",
        "header_row_idx": 0, "first_data_row_idx": 1, "last_data_row_idx": 1,
        "columns": {
            "date_from": 0, "date_to": 1, "base_room": 2,
            "base_room_label": "SUPERIOR GV",
            "child_cols": [], "upgrade_cols": [{"col_idx": 2, "label": "SUP PV"}],
            "meal_upgrade_cols": [], "note_cols": [],
        },
    }
    occupancy = [
        {"room_name": "SUPERIOR GV", "min_pax": 1, "max_pax": 3, "min_adult": 1, "max_adult": 3, "max_child": 2},
        {"room_name": "SUP PV", "min_pax": 1, "max_pax": 3, "min_adult": 1, "max_adult": 3, "max_child": 2},
    ]
    hotel_rows, _ = _expand_block(rows, block, {"name": "X"}, occupancy, {}, "S", "f.xlsx")
    # base + upgrade both matched
    for r in hotel_rows:
        assert r["Min Adult"] == 1
        assert r["Max Adult"] == 3
        assert r["Max Pax"] == 3
