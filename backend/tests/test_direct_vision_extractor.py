"""Tests for the direct-vision extractor's transform layer.

The actual OpenAI call is not invoked here — we test the page-result
to-NormalizedExtractionResult shaping and the per-page merging.
"""
from __future__ import annotations

from app.services.direct_vision_extractor import _page_result_to_normalized
from app.services.llm_chunker import merge_chunk_results


def _sample_page_one() -> dict:
    return {
        "pageHotels": [
            {
                "hotelName": "Acrotel Lily Ann Village",
                "metadata": {"currency": "EUR", "rateType": "Per Person Per Day"},
                "rateBlocks": [],
                "roomTypes": [
                    {"name": "Double Room", "minAdult": 2, "maxAdult": 2},
                    {"name": "Superior Room", "minAdult": 2, "maxAdult": 3},
                    {"name": "Family Room", "minAdult": 2, "maxAdult": 4},
                ],
            }
        ],
        "dynamicChildColumns": [
            {
                "key": "CHD1(0.1-11.99)",
                "label": "CHD1(0.1-11.99)",
                "ageFrom": 0.1,
                "ageTo": 11.99,
                "ageLabel": None,
                "childPosition": "first_child",
                "valueType": "discount_percentage",
            }
        ],
        "hotelRows": [
            {
                "Hotel Name": "Acrotel Lily Ann Village",
                "Room Name": "Double Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Currency": "EUR",
                "Meal Plan": "Bed & Breakfast",
                "SGL": 62,
                "DBL": 34,
                "dynamicChildValues": {"CHD1(0.1-11.99)": 100},
            },
            {
                "Hotel Name": "Acrotel Lily Ann Village",
                "Room Name": "Superior Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Currency": "EUR",
                "Meal Plan": "Bed & Breakfast",
                "DBL": 43,
            },
        ],
        "extractionNotes": [
            {"Category": "Other", "Note": "Page 1 note"},
        ],
    }


def _sample_page_two() -> dict:
    return {
        "pageHotels": [
            {
                "hotelName": "Acrotel Lily Ann Village",
                "metadata": {"currency": "EUR"},
                "rateBlocks": [],
                "roomTypes": [],
            }
        ],
        "dynamicChildColumns": [
            {
                "key": "CHD2(2-11.99)",
                "label": "CHD2(2-11.99)",
                "ageFrom": 2,
                "ageTo": 11.99,
                "ageLabel": None,
                "childPosition": "second_child",
                "valueType": "discount_percentage",
            }
        ],
        "hotelRows": [
            {
                "Hotel Name": "Acrotel Lily Ann Village",
                "Room Name": "Family Room",
                "Start Date": "2026-06-14",
                "End Date": "2026-08-31",
                "Currency": "EUR",
                "Meal Plan": "Half Board",
                "DBL": 79,
                "dynamicChildValues": {"CHD2(2-11.99)": 50},
            }
        ],
        "extractionNotes": [
            {"Category": "Cancellation", "Note": "14 days 0% fees"},
        ],
    }


def test_page_result_to_normalized_shape() -> None:
    norm = _page_result_to_normalized(
        _sample_page_one(),
        source_file="acrotel.pdf",
        source_ref="acrotel.pdf | Page 1",
        page_id="Page:1",
    )
    assert norm["workbookSummary"]["hotelSheets"] == ["Page:1"]
    assert len(norm["hotelRows"]) == 2
    # ids and source refs populated
    for r in norm["hotelRows"]:
        assert r["id"]
        assert r["sourceSheetOrPage"] == "Page:1"
        assert "acrotel.pdf | Page 1" in r["_sourceRefs"]
    assert len(norm["extractionNotes"]) == 1
    assert norm["extractionNotes"][0]["Page"] == "Page:1"


def test_merge_across_pages_unions_child_columns_and_concatenates_rows() -> None:
    p1 = _page_result_to_normalized(_sample_page_one(), source_file="acrotel.pdf",
                                     source_ref="acrotel.pdf | Page 1", page_id="Page:1")
    p2 = _page_result_to_normalized(_sample_page_two(), source_file="acrotel.pdf",
                                     source_ref="acrotel.pdf | Page 2", page_id="Page:2")
    merged = merge_chunk_results([p1, p2], source_file="acrotel.pdf")

    # 3 rows total (2 + 1)
    assert len(merged["hotelRows"]) == 3
    # Child columns unioned by key
    keys = {c["key"] for c in merged["dynamicColumns"]["childColumns"]}
    assert "CHD1(0.1-11.99)" in keys
    assert "CHD2(2-11.99)" in keys
    # Hotel grouped by name
    assert len(merged["hotels"]) == 1
    assert merged["hotels"][0]["hotelName"] == "Acrotel Lily Ann Village"
    # Notes from both pages preserved
    cats = {n["Category"] for n in merged["extractionNotes"]}
    assert "Other" in cats
    assert "Cancellation" in cats
