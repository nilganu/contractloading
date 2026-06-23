"""Tests for GPT hotel metadata enrichment (LLM call mocked)."""
from __future__ import annotations

from types import SimpleNamespace

from app.services import hotel_enrichment as he


def _row(**over) -> dict:
    base = {
        "id": "r1",
        "sourceSheetOrPage": "S",
        "Hotel Name": "Acrotel Lily Ann Village",
        "Room Name": "Standard",
        "Country Code ": "GR",
        "City / Area": "Nikiti",
        "Address Line 1": None,
        "Postal Code": None,
        "Latitude": None,
        "Longitude": None,
        "_warnings": [],
    }
    base.update(over)
    return base


def _result(rows) -> dict:
    return {
        "workbookSummary": {"sourceFile": "x", "inputFormat": "xlsx"},
        "dynamicColumns": {"childColumns": []},
        "hotelRows": rows,
        "extractionNotes": [],
    }


def _patch_llm(monkeypatch, fields: dict) -> None:
    monkeypatch.setattr(
        he, "get_settings", lambda: SimpleNamespace(openai_api_key="x", openai_model="gpt-4o")
    )
    monkeypatch.setattr(he, "_call_openai_json", lambda messages: {"fields": fields})


def test_fills_only_empty_fields(monkeypatch) -> None:
    _patch_llm(
        monkeypatch,
        {
            "addressLine1": "Sithonia Peninsula",
            "postalCode": "63088",
            "countryCode": "DE",  # should be ignored — already 'GR'
            "cityOrArea": "Thessaloniki",  # already 'Nikiti' — must not overwrite
            "latitude": 40.123,
            "longitude": 23.987,
        },
    )
    rows = [_row(), _row(id="r2")]  # two rows, same hotel
    res = _result(rows)
    summary = he.enrich_result(res)

    assert summary["hotelsProcessed"] == 1
    r = res["hotelRows"][0]
    # empty fields filled
    assert r["Address Line 1"] == "Sithonia Peninsula"
    assert r["Postal Code"] == "63088"
    assert r["Latitude"] == 40.123
    assert r["Longitude"] == 23.987
    # existing contract values preserved (never overwritten)
    assert r["Country Code "] == "GR"
    assert r["City / Area"] == "Nikiti"
    # applied to every row of the hotel
    assert res["hotelRows"][1]["Address Line 1"] == "Sithonia Peninsula"


def test_filled_values_marked_ai_inferred(monkeypatch) -> None:
    _patch_llm(monkeypatch, {"addressLine1": "Some Street 1"})
    res = _result([_row()])
    he.enrich_result(res)
    r = res["hotelRows"][0]
    assert any("AI-inferred" in w for w in r["_warnings"])
    assert r["_cellMeta"]["Address Line 1"]["aiInferred"] is True
    assert r["_cellMeta"]["Address Line 1"]["confidence"] == 0.3


def test_null_values_are_not_applied(monkeypatch) -> None:
    _patch_llm(monkeypatch, {"addressLine1": None, "postalCode": ""})
    res = _result([_row()])
    summary = he.enrich_result(res)
    r = res["hotelRows"][0]
    assert r["Address Line 1"] is None
    assert r["Postal Code"] is None
    assert summary["fieldsFilled"] == 0


def test_skips_when_no_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        he, "get_settings", lambda: SimpleNamespace(openai_api_key="", openai_model="gpt-4o")
    )
    res = _result([_row()])
    summary = he.enrich_result(res)
    assert summary["skipped"] is True
    assert summary["fieldsFilled"] == 0
    assert res["hotelRows"][0]["Address Line 1"] is None


def test_country_code_normalized_to_iso2(monkeypatch) -> None:
    _patch_llm(monkeypatch, {"countryCode": "grc"})
    res = _result([_row(**{"Country Code ": None})])
    he.enrich_result(res)
    assert res["hotelRows"][0]["Country Code "] == "GR"
