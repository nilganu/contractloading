"""Tests for the End-Date-year auto-correction in the normalizer."""
from __future__ import annotations

from app.services.normalizer import normalize_result


def _opts() -> dict:
    return {
        "supplierDefault": "X",
        "currencyDefault": "EUR",
        "childColumnMode": "dynamic_review",
        "preserveChildPositions": True,
        "extractionMode": "text_only",
    }


def _wrap(rows: list[dict]) -> dict:
    return {
        "workbookSummary": {"sourceFile": "x.xlsx", "inputFormat": "xlsx"},
        "dynamicColumns": {"childColumns": []},
        "hotelRows": rows,
        "extractionNotes": [],
    }


def test_end_year_typo_bumped_up() -> None:
    """Contract has Start 2026-04-10 End 2025-05-03 -> bump End year to 2026."""
    raw = _wrap([
        {"id": "r1", "Hotel Name": "Test", "Room Name": "X",
         "Start Date": "2026-04-10", "End Date": "2025-05-03", "DBL": 40,
         "dynamicChildValues": {}}
    ])
    norm = normalize_result(raw, _opts(), "x.xlsx")
    row = norm["hotelRows"][0]
    assert row["End Date"] == "2026-05-03"
    # Days is now a Moonstride weekday mask (default all-week), not a night count.
    assert row["Days"] == "1234567"
    # Warning recorded
    assert any("auto-corrected" in w for w in row.get("_warnings") or [])


def test_normal_dates_untouched() -> None:
    raw = _wrap([
        {"id": "r1", "Hotel Name": "Test", "Room Name": "X",
         "Start Date": "2026-04-10", "End Date": "2026-05-03", "DBL": 40,
         "dynamicChildValues": {}}
    ])
    norm = normalize_result(raw, _opts(), "x.xlsx")
    row = norm["hotelRows"][0]
    assert row["End Date"] == "2026-05-03"
    assert not any("auto-corrected" in w for w in row.get("_warnings") or [])


def test_no_autofix_when_bump_does_not_fix_ordering() -> None:
    """If End is in a year FAR before Start (eg 5 years earlier and the same
    month/day is still earlier after a 1-year bump — shouldn't actually
    happen given the +1 logic but verify defensiveness)."""
    raw = _wrap([
        {"id": "r1", "Hotel Name": "Test", "Room Name": "X",
         "Start Date": "2026-04-10", "End Date": "2026-04-09",  # End before Start by 1 day
         "DBL": 40, "dynamicChildValues": {}}
    ])
    norm = normalize_result(raw, _opts(), "x.xlsx")
    row = norm["hotelRows"][0]
    # End year is same as Start year — autofix should NOT touch
    assert row["End Date"] == "2026-04-09"
