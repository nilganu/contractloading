"""Tests that the normalizer auto-detects percentage_of_adult columns by
value range and converts them even when the LLM column-map left them as
'amount' or 'unknown'."""
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


def _wrap(cols: list[dict], rows: list[dict]) -> dict:
    return {
        "workbookSummary": {"sourceFile": "x.xlsx", "inputFormat": "xlsx"},
        "dynamicColumns": {"childColumns": cols},
        "hotelRows": rows,
        "extractionNotes": [],
    }


def test_all_decimal_values_reclassified_as_percentage_of_adult() -> None:
    """A column with only decimals in [0, 1] is auto-detected as
    percentage_of_adult and converted to EUR amounts."""
    cols = [
        {"key": "CHD1(0-5.99)", "label": "CHD1(0-5.99)", "ageFrom": 0, "ageTo": 5.99,
         "childPosition": "first_child", "valueType": "unknown"},
    ]
    rows = [
        {"id": "r1", "Hotel Name": "T", "Room Name": "Sup", "Start Date": "2026-04-01",
         "End Date": "2026-05-01", "DBL": 40,
         "dynamicChildValues": {"CHD1(0-5.99)": 1}},
        {"id": "r2", "Hotel Name": "T", "Room Name": "Sup", "Start Date": "2026-05-01",
         "End Date": "2026-06-01", "DBL": 60,
         "dynamicChildValues": {"CHD1(0-5.99)": 0.5}},
    ]
    norm = normalize_result(_wrap(cols, rows), _opts(), "x.xlsx")
    assert norm["hotelRows"][0]["dynamicChildValues"]["CHD1(0-5.99)"] == 40   # 40 * 1
    assert norm["hotelRows"][1]["dynamicChildValues"]["CHD1(0-5.99)"] == 30   # 60 * 0.5
    # Column is now amount-typed
    assert norm["dynamicColumns"]["childColumns"][0]["valueType"] == "amount"


def test_column_with_value_above_one_not_reclassified() -> None:
    """If any value is > 1 (eg 20 or 50 EUR), don't auto-reclassify;
    treat the values as already-amounts."""
    cols = [
        {"key": "CHD2(6-10.99)", "label": "CHD2(6-10.99)", "ageFrom": 6, "ageTo": 10.99,
         "childPosition": "second_child", "valueType": "amount"},
    ]
    rows = [
        {"id": "r1", "Hotel Name": "T", "Room Name": "Sup", "Start Date": "2026-04-01",
         "End Date": "2026-05-01", "DBL": 40,
         "dynamicChildValues": {"CHD2(6-10.99)": 25}},
        {"id": "r2", "Hotel Name": "T", "Room Name": "Sup", "Start Date": "2026-05-01",
         "End Date": "2026-06-01", "DBL": 60,
         "dynamicChildValues": {"CHD2(6-10.99)": 30}},
    ]
    norm = normalize_result(_wrap(cols, rows), _opts(), "x.xlsx")
    # No conversion — values stay as-is (already euros)
    assert norm["hotelRows"][0]["dynamicChildValues"]["CHD2(6-10.99)"] == 25
    assert norm["hotelRows"][1]["dynamicChildValues"]["CHD2(6-10.99)"] == 30
