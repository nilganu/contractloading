"""Tests for the discount-percentage → currency-amount conversion in the
normalizer."""
from __future__ import annotations

from app.services.normalizer import normalize_result


def _opts() -> dict:
    return {
        "supplierDefault": "X",
        "countryDefault": "GR",
        "currencyDefault": "EUR",
        "statusDefault": "Open",
        "childColumnMode": "dynamic_review",
        "preserveChildPositions": True,
        "extractionMode": "text_only",
    }


def test_50_percent_discount_becomes_half_of_dbl() -> None:
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {
            "childColumns": [
                {
                    "key": "CHD2(2-11.99)",
                    "label": "CHD2(2-11.99)",
                    "ageFrom": 2,
                    "ageTo": 11.99,
                    "ageLabel": None,
                    "childPosition": "second_child",
                    "valueType": "discount_percentage",
                }
            ]
        },
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
                "dynamicChildValues": {"CHD2(2-11.99)": 50},
            }
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    # 43 * (1 - 50/100) = 21.5
    assert norm["hotelRows"][0]["dynamicChildValues"]["CHD2(2-11.99)"] == 21.5
    # Column valueType upgraded to amount, label dropped suffix
    col = norm["dynamicColumns"]["childColumns"][0]
    assert col["valueType"] == "amount"
    assert col["label"] == "CHD2(2-11.99)"


def test_100_percent_discount_becomes_zero() -> None:
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {
            "childColumns": [
                {"key": "CHD1(0.1-11.99)", "label": "CHD1(0.1-11.99)", "ageFrom": 0.1, "ageTo": 11.99,
                 "ageLabel": None, "childPosition": "first_child", "valueType": "discount_percentage"}
            ]
        },
        "hotelRows": [
            {
                "id": "r1",
                "Hotel Name": "Acrotel",
                "Room Name": "Superior Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Meal Plan": "Half Board",
                "Currency": "EUR",
                "DBL": 59,
                "dynamicChildValues": {"CHD1(0.1-11.99)": 100},
            }
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    assert norm["hotelRows"][0]["dynamicChildValues"]["CHD1(0.1-11.99)"] == 0


def test_null_stays_null_for_rooms_with_no_children() -> None:
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {
            "childColumns": [
                {"key": "CHD3(2-11.99)", "label": "CHD3(2-11.99)", "ageFrom": 2, "ageTo": 11.99,
                 "ageLabel": None, "childPosition": "third_child", "valueType": "discount_percentage"}
            ]
        },
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
                "dynamicChildValues": {"CHD3(2-11.99)": None},
            }
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    assert norm["hotelRows"][0]["dynamicChildValues"]["CHD3(2-11.99)"] is None


def test_per_row_dbl_drives_per_row_amount() -> None:
    raw = {
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {
            "childColumns": [
                {"key": "CHD2(2-11.99)", "label": "CHD2(2-11.99)", "ageFrom": 2, "ageTo": 11.99,
                 "ageLabel": None, "childPosition": "second_child", "valueType": "discount_percentage"}
            ]
        },
        "hotelRows": [
            # Same room, three different seasons -> three different DBLs
            {"id": "r1", "Hotel Name": "Acrotel", "Room Name": "Superior Room",
             "Start Date": "2026-04-01", "End Date": "2026-06-13", "Meal Plan": "Bed & Breakfast",
             "Currency": "EUR", "DBL": 43, "dynamicChildValues": {"CHD2(2-11.99)": 50}},
            {"id": "r2", "Hotel Name": "Acrotel", "Room Name": "Superior Room",
             "Start Date": "2026-09-01", "End Date": "2026-09-14", "Meal Plan": "Bed & Breakfast",
             "Currency": "EUR", "DBL": 65, "dynamicChildValues": {"CHD2(2-11.99)": 50}},
            {"id": "r3", "Hotel Name": "Acrotel", "Room Name": "Superior Room",
             "Start Date": "2026-06-14", "End Date": "2026-08-31", "Meal Plan": "Bed & Breakfast",
             "Currency": "EUR", "DBL": 79, "dynamicChildValues": {"CHD2(2-11.99)": 50}},
        ],
        "extractionNotes": [],
    }
    norm = normalize_result(raw, _opts(), "x.pdf")
    chd_values = [r["dynamicChildValues"]["CHD2(2-11.99)"] for r in norm["hotelRows"]]
    assert chd_values == [21.5, 32.5, 39.5]
