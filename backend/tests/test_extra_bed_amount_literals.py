"""Tests that the Extra Bed pipeline handles bare-amount contracts (not just
percentages) correctly. Mirrors the broadcast logic in
direct_vision_extractor._process_batch_two_call.
"""
from __future__ import annotations

import re

from app.services.normalizer import normalize_result


def _apply_broadcast(row: dict, literal: str) -> None:
    """Mirror the broadcast logic so we can test it in isolation."""
    up = (literal or "").strip().upper()
    if up in {"N/A", "NA", "-", ""}:
        row["Extra Bed"] = None
    elif up in {"FREE", "FOC", "INCLUDED"}:
        row["Extra Bed"] = 0
    elif "%" in up:
        try:
            pct = float(up.replace("%", "").lstrip("-").strip())
            row["Extra Bed"] = pct
            row["_extraBedIsPercentage"] = True
        except ValueError:
            pass
    else:
        m = re.search(r"-?\d+(?:[.,]\d+)?", up)
        if m:
            row["Extra Bed"] = float(m.group(0).replace(",", "."))


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
        "workbookSummary": {"sourceFile": "x.pdf", "inputFormat": "pdf"},
        "dynamicColumns": {"childColumns": []},
        "hotelRows": rows,
        "extractionNotes": [],
    }


def test_bare_amount_literal_preserved_no_multiplication() -> None:
    """When contract uses 'Extra Bed: 25 EUR', the export must show 25,
    not 25 × DBL."""
    row = {
        "id": "r1",
        "Hotel Name": "Sample Hotel",
        "Room Name": "Superior Room",
        "Start Date": "2026-04-01",
        "End Date": "2026-06-13",
        "Meal Plan": "Bed & Breakfast",
        "Currency": "EUR",
        "DBL": 60,
        "dynamicChildValues": {},
    }
    _apply_broadcast(row, "25 EUR")
    assert row["Extra Bed"] == 25
    assert "_extraBedIsPercentage" not in row
    norm = normalize_result(_wrap([row]), _opts(), "x.pdf")
    assert norm["hotelRows"][0]["Extra Bed"] == 25  # untouched


def test_amount_with_euro_symbol_preserved() -> None:
    row = {
        "id": "r1", "Hotel Name": "X", "Room Name": "Family", "Start Date": "2026-04-01",
        "End Date": "2026-06-13", "Meal Plan": "Half Board", "Currency": "EUR",
        "DBL": 70, "dynamicChildValues": {},
    }
    _apply_broadcast(row, "€20")
    assert row["Extra Bed"] == 20
    norm = normalize_result(_wrap([row]), _opts(), "x.pdf")
    assert norm["hotelRows"][0]["Extra Bed"] == 20


def test_comma_decimal_amount_preserved() -> None:
    row = {
        "id": "r1", "Hotel Name": "X", "Room Name": "Family", "Start Date": "2026-04-01",
        "End Date": "2026-06-13", "Meal Plan": "All Inclusive", "Currency": "EUR",
        "DBL": 100, "dynamicChildValues": {},
    }
    _apply_broadcast(row, "12,50 EUR")
    assert row["Extra Bed"] == 12.5
    norm = normalize_result(_wrap([row]), _opts(), "x.pdf")
    assert norm["hotelRows"][0]["Extra Bed"] == 12.5


def test_mixed_literal_per_room_handled_independently() -> None:
    """One room gets a percentage literal, another gets a bare amount."""
    superior = {
        "id": "r1", "Hotel Name": "X", "Room Name": "Superior Room",
        "Start Date": "2026-04-01", "End Date": "2026-06-13",
        "Meal Plan": "Bed & Breakfast", "Currency": "EUR",
        "DBL": 60, "dynamicChildValues": {},
    }
    family = {
        "id": "r2", "Hotel Name": "X", "Room Name": "Family Room",
        "Start Date": "2026-04-01", "End Date": "2026-06-13",
        "Meal Plan": "Bed & Breakfast", "Currency": "EUR",
        "DBL": 80, "dynamicChildValues": {},
    }
    _apply_broadcast(superior, "-30%")
    _apply_broadcast(family, "20 EUR")
    norm = normalize_result(_wrap([superior, family]), _opts(), "x.pdf")
    # Superior: 60 * 0.7 = 42
    assert norm["hotelRows"][0]["Extra Bed"] == 42.0
    # Family: bare amount, unchanged
    assert norm["hotelRows"][1]["Extra Bed"] == 20


def test_free_literal_maps_to_zero() -> None:
    row = {
        "id": "r1", "Hotel Name": "X", "Room Name": "Superior",
        "Start Date": "2026-04-01", "End Date": "2026-06-13",
        "Meal Plan": "Bed & Breakfast", "Currency": "EUR",
        "DBL": 60, "dynamicChildValues": {},
    }
    _apply_broadcast(row, "free")
    assert row["Extra Bed"] == 0
    norm = normalize_result(_wrap([row]), _opts(), "x.pdf")
    assert norm["hotelRows"][0]["Extra Bed"] == 0
