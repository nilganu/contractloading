"""Tests for the Extra Bed (extra adult) field flow.

Extra Bed for the Acrotel-style contract reads "-30%" → meaning the
extra adult pays 70% of the per-person adult DBL. After normalization the
Extra Bed cell should hold a real currency amount, not a percentage. For
rooms with no extra-adult support ("n/a"), Extra Bed stays null.
"""
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


def test_extra_bed_percentage_becomes_amount() -> None:
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {"childColumns": []},
        "hotelRows": [
            {
                "id": "r1",
                "Hotel Name": "Acrotel",
                "Room Name": "Superior Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Meal Plan": "Bed & Breakfast",
                "Currency": "EUR",
                "DBL": 43,
                "Extra Bed": 30,           # 30% discount
                "_extraBedIsPercentage": True,
                "dynamicChildValues": {},
            }
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    # 43 * (1 - 30/100) = 30.1
    assert norm["hotelRows"][0]["Extra Bed"] == 30.1
    # Flag is removed after conversion
    assert "_extraBedIsPercentage" not in norm["hotelRows"][0]


def test_extra_bed_null_stays_null() -> None:
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {"childColumns": []},
        "hotelRows": [
            {
                "id": "r1",
                "Hotel Name": "Acrotel",
                "Room Name": "Double Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Meal Plan": "Bed & Breakfast",
                "Currency": "EUR",
                "DBL": 34,
                "Extra Bed": None,         # n/a
                "dynamicChildValues": {},
            }
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    assert norm["hotelRows"][0]["Extra Bed"] is None


def test_extra_bed_amount_stays_amount_when_not_flagged() -> None:
    """An Extra Bed value of 25 with no _extraBedIsPercentage flag is
    treated as a real currency amount and not multiplied by DBL."""
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {"childColumns": []},
        "hotelRows": [
            {
                "id": "r1",
                "Hotel Name": "Acrotel",
                "Room Name": "Superior Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Meal Plan": "Bed & Breakfast",
                "Currency": "EUR",
                "DBL": 43,
                "Extra Bed": 25,
                "dynamicChildValues": {},
            }
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    assert norm["hotelRows"][0]["Extra Bed"] == 25
