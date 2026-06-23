"""Tests for the defensive cell audit."""
from __future__ import annotations

from app.services.cell_audit import _parse_cell_number, audit_cells


def test_parse_cell_number_handles_common_shapes() -> None:
    assert _parse_cell_number(62) == 62
    assert _parse_cell_number(62.0) == 62.0
    assert _parse_cell_number("62") == 62
    assert _parse_cell_number("€62,00") == 62
    assert _parse_cell_number("62.00 EUR") == 62
    assert _parse_cell_number("130,00") == 130
    # Drop non-numbers
    assert _parse_cell_number(None) is None
    assert _parse_cell_number("") is None
    assert _parse_cell_number("n/a") is None
    assert _parse_cell_number("free") is None
    assert _parse_cell_number("-50%") is None
    assert _parse_cell_number("FOC") is None
    # Drop implausible numbers
    assert _parse_cell_number("1") is None  # too small
    assert _parse_cell_number("999999") is None  # phone-number-ish
    # Drop non-rate cells that pdfplumber commonly reports from PDF tables
    assert _parse_cell_number("14/06-31/08") is None
    assert _parse_cell_number("3 | 10") is None
    assert _parse_cell_number("ACROTEL SALES CONTRACT tax reference number 094447608 Page 1 of 3") is None


def test_audit_flags_unmapped_source_cells() -> None:
    ir = {
        "source_file": "x.pdf",
        "input_format": "pdf",
        "documents": [
            {
                "id": "Page:1",
                "classification": "hotel_contract",
                "source_ref": "x.pdf | Page 1",
                "tables": [
                    {
                        "source": "vision",
                        "columns": ["Period", "Board", "Double for Single", "Double", "Superior", "Family"],
                        "rows": [
                            {"Period": "01.04-13.06", "Board": "BB", "Double for Single": "€62", "Double": "€34", "Superior": "€43", "Family": "€54"},
                            {"Period": "01.04-13.06", "Board": "HB", "Double for Single": "€78", "Double": "€50", "Superior": "€59", "Family": "€70"},
                        ],
                    }
                ],
            }
        ],
    }
    # The LLM only managed to record Double Room prices — Superior & Family
    # cells (43, 54, 59, 70) should be flagged as unmapped.
    result = {
        "workbookSummary": {"sourceFile": "x.pdf"},
        "hotelRows": [
            {"id": "r1", "Room Name": "Double Room", "Start Date": "2026-04-01", "End Date": "2026-06-13", "Meal Plan": "Bed & Breakfast", "SGL": 62, "DBL": 34},
            {"id": "r2", "Room Name": "Double Room", "Start Date": "2026-04-01", "End Date": "2026-06-13", "Meal Plan": "Half Board", "SGL": 78, "DBL": 50},
        ],
        "extractionNotes": [],
    }
    audit = audit_cells(ir, result)
    assert audit["stats"]["unmapped_cells"] == 4
    # Should produce at least one note describing the missing cells
    assert audit["notes"], "expected an extraction note for unmapped cells"
    # Note text should mention Superior or Family
    blob = " ".join(n["Note"] for n in audit["notes"])
    assert "Superior" in blob or "Family" in blob


def test_audit_silent_when_all_cells_mapped() -> None:
    ir = {
        "source_file": "x.pdf",
        "input_format": "pdf",
        "documents": [
            {
                "id": "Page:1",
                "classification": "hotel_contract",
                "source_ref": "x.pdf | Page 1",
                "tables": [
                    {
                        "source": "vision",
                        "columns": ["Period", "Board", "Double"],
                        "rows": [
                            {"Period": "01.04-13.06", "Board": "BB", "Double": "€34"},
                        ],
                    }
                ],
            }
        ],
    }
    result = {
        "workbookSummary": {"sourceFile": "x.pdf"},
        "hotelRows": [
            {"id": "r1", "Room Name": "Double Room", "Start Date": "2026-04-01", "End Date": "2026-06-13", "Meal Plan": "Bed & Breakfast", "DBL": 34},
        ],
        "extractionNotes": [],
    }
    audit = audit_cells(ir, result)
    assert audit["stats"]["unmapped_cells"] == 0
    assert audit["notes"] == []


def test_audit_counts_rows_without_prices() -> None:
    ir = {"source_file": "x.pdf", "input_format": "pdf", "documents": []}
    result = {
        "workbookSummary": {"sourceFile": "x.pdf"},
        "hotelRows": [
            {"id": "r1", "Room Name": "Double Room", "DBL": 34},
            {"id": "r2", "Room Name": "Family Room"},  # no prices
            {"id": "r3", "Room Name": "Superior Room"},  # no prices
        ],
        "extractionNotes": [],
    }
    audit = audit_cells(ir, result)
    assert audit["stats"]["rows_without_prices"] == 2


def test_audit_treats_dynamic_child_amounts_as_mapped() -> None:
    ir = {
        "source_file": "x.xlsx",
        "input_format": "xlsx",
        "documents": [
            {
                "id": "Sheet:1",
                "classification": "hotel_contract",
                "tables": [
                    {
                        "source": "vision",
                        "columns": ["Room", "CHD"],
                        "rows": [{"Room": "Family", "CHD": "25 EUR"}],
                    }
                ],
            }
        ],
    }
    result = {
        "workbookSummary": {"sourceFile": "x.xlsx"},
        "hotelRows": [
            {
                "id": "r1",
                "Room Name": "Family Room",
                "DBL": 100,
                "dynamicChildValues": {"CHD(2-11.99)": 25},
            },
        ],
    }
    audit = audit_cells(ir, result)
    assert audit["stats"]["unmapped_cells"] == 0
