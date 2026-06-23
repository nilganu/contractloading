"""Per-hotel sheets should drop CHD columns the hotel doesn't actually use,
while the combined Hotel sheet keeps the full union."""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from app.services.exporter import export_workbook


def test_per_hotel_sheet_drops_unused_chd_columns(tmp_path: Path) -> None:
    result = {
        "workbookSummary": {"sourceFile": "multi.xlsx", "inputFormat": "xlsx"},
        "dynamicColumns": {
            "childColumns": [
                # Hotel A uses these two
                {"key": "CHD1(0-5.99)", "label": "CHD1(0-5.99)", "ageFrom": 0, "ageTo": 5.99,
                 "childPosition": "first_child", "valueType": "amount"},
                {"key": "CHD2(6-10.99)", "label": "CHD2(6-10.99)", "ageFrom": 6, "ageTo": 10.99,
                 "childPosition": "second_child", "valueType": "amount"},
                # Hotel B uses these two
                {"key": "CHD1(0-11.99)", "label": "CHD1(0-11.99)", "ageFrom": 0, "ageTo": 11.99,
                 "childPosition": "first_child", "valueType": "amount"},
                {"key": "CHD3(0-11.99)", "label": "CHD3(0-11.99)", "ageFrom": 0, "ageTo": 11.99,
                 "childPosition": "third_child", "valueType": "amount"},
            ],
        },
        "hotels": [],
        "hotelRows": [
            {
                "id": "r1", "Hotel Name": "Hotel A", "Room Name": "Standard",
                "Start Date": "2026-04-01", "End Date": "2026-06-13",
                "Meal Plan": "Bed & Breakfast", "Currency": "EUR", "DBL": 40,
                "dynamicChildValues": {
                    "CHD1(0-5.99)": 40, "CHD2(6-10.99)": 20,
                    "CHD1(0-11.99)": None, "CHD3(0-11.99)": None,
                },
            },
            {
                "id": "r2", "Hotel Name": "Hotel B", "Room Name": "Standard",
                "Start Date": "2026-04-01", "End Date": "2026-06-13",
                "Meal Plan": "Half Board", "Currency": "EUR", "DBL": 50,
                "dynamicChildValues": {
                    "CHD1(0-5.99)": None, "CHD2(6-10.99)": None,
                    "CHD1(0-11.99)": 50, "CHD3(0-11.99)": 25,
                },
            },
        ],
        "extractionNotes": [],
        "validationIssues": [],
    }
    out = tmp_path / "multi.xlsx"
    export_workbook(result, output_path=out, mode="dynamic_export")
    wb = load_workbook(out, data_only=True)

    # Combined "Hotel" sheet — keeps ALL 4 CHD columns
    combined = wb["Hotel"]
    headers = [c.value for c in combined[1]]
    chd_in_combined = [h for h in headers if isinstance(h, str) and h.startswith("CHD")]
    assert set(chd_in_combined) == {"CHD1(0-5.99)", "CHD2(6-10.99)", "CHD1(0-11.99)", "CHD3(0-11.99)"}

    # Hotel A sheet — only its own 2 CHD columns
    a = wb["Hotel A"]
    a_headers = [c.value for c in a[1]]
    a_chd = [h for h in a_headers if isinstance(h, str) and h.startswith("CHD")]
    assert set(a_chd) == {"CHD1(0-5.99)", "CHD2(6-10.99)"}

    # Hotel B sheet — only its own 2 CHD columns
    b = wb["Hotel B"]
    b_headers = [c.value for c in b[1]]
    b_chd = [h for h in b_headers if isinstance(h, str) and h.startswith("CHD")]
    assert set(b_chd) == {"CHD1(0-11.99)", "CHD3(0-11.99)"}
