"""Tests for the vision two-section parser and completeness check."""
from __future__ import annotations

from app.services.completeness import check_completeness, estimate_rate_dimensions
from app.services.parsers.pdf_vision import split_vision_sections


SAMPLE_VISION_OUTPUT = """\
## TEXT
ACROTEL SALES CONTRACT
Contract for Hotel: ACROTEL LILYANN VILLAGE
Year: 2026

## TABLES
```json
[
  {
    "title": "Price List",
    "columns": ["Period", "Board", "Double for Single", "Double", "Superior", "Family"],
    "rows": [
      {"Period": "01.04.2026 - 13.06.2026 & 15.09.2026 - 31.10.2026", "Board": "BB", "Double for Single": "€62,00", "Double": "€34,00", "Superior": "€43,00", "Family": "€54,00"},
      {"Period": "01.04.2026 - 13.06.2026 & 15.09.2026 - 31.10.2026", "Board": "HB", "Double for Single": "€78,00", "Double": "€50,00", "Superior": "€59,00", "Family": "€70,00"},
      {"Period": "01.09.2026 - 14.09.2026", "Board": "BB", "Double for Single": "€91,00", "Double": "€52,00", "Superior": "€65,00", "Family": "€82,00"},
      {"Period": "01.09.2026 - 14.09.2026", "Board": "HB", "Double for Single": "€107,00", "Double": "€68,00", "Superior": "€81,00", "Family": "€98,00"},
      {"Period": "14.06.2026 - 31.08.2026", "Board": "BB", "Double for Single": "€130,00", "Double": "€63,00", "Superior": "€79,00", "Family": "€99,00"},
      {"Period": "14.06.2026 - 31.08.2026", "Board": "HB", "Double for Single": "€146,00", "Double": "€79,00", "Superior": "€95,00", "Family": "€115,00"}
    ]
  }
]
```
"""


def test_split_vision_sections_extracts_text_and_tables() -> None:
    text, tables = split_vision_sections(SAMPLE_VISION_OUTPUT)
    assert "ACROTEL SALES CONTRACT" in text
    assert "## TABLES" not in text
    assert len(tables) == 1
    assert tables[0]["title"] == "Price List"
    assert "Double for Single" in tables[0]["columns"]
    assert len(tables[0]["rows"]) == 6


def test_estimate_rate_dimensions_from_vision_table() -> None:
    _, tables = split_vision_sections(SAMPLE_VISION_OUTPUT)
    rooms, periods, boards = estimate_rate_dimensions(tables[0])
    # 4 room columns, 3 distinct period values, 2 boards
    assert rooms == 4
    assert periods == 3
    assert boards == 2


def test_completeness_check_flags_under_extraction() -> None:
    _, tables = split_vision_sections(SAMPLE_VISION_OUTPUT)
    ir = {
        "source_file": "x.pdf",
        "input_format": "pdf",
        "documents": [
            {
                "id": "Page:1",
                "classification": "hotel_contract",
                "source_ref": "x.pdf | Page 1",
                "tables": [{**tables[0], "source": "vision"}],
            }
        ],
    }
    # LLM only produced 2 rows for that page (way short of 4×3×2 = 24)
    result = {
        "workbookSummary": {"sourceFile": "x.pdf"},
        "hotelRows": [
            {"id": "r1", "sourceSheetOrPage": "Page:1"},
            {"id": "r2", "sourceSheetOrPage": "Page:1"},
        ],
        "extractionNotes": [],
    }
    notes, warnings = check_completeness(ir, result)
    assert warnings, "should warn about under-extraction"
    assert any("24 Hotel rows" in w or "up to 24" in w for w in warnings)
    assert notes and notes[0]["Category"] == "Source ambiguity"


def test_completeness_check_silent_when_extraction_is_complete() -> None:
    _, tables = split_vision_sections(SAMPLE_VISION_OUTPUT)
    ir = {
        "source_file": "x.pdf",
        "input_format": "pdf",
        "documents": [
            {
                "id": "Page:1",
                "classification": "hotel_contract",
                "tables": [{**tables[0], "source": "vision"}],
            }
        ],
    }
    rows = [{"id": f"r{i}", "sourceSheetOrPage": "Page:1"} for i in range(20)]
    result = {"workbookSummary": {"sourceFile": "x.pdf"}, "hotelRows": rows, "extractionNotes": []}
    notes, warnings = check_completeness(ir, result)
    assert notes == []
    assert warnings == []
