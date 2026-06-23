"""Tests for the per-supplier template cache."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.supplier_templates import (
    _slugify,
    load_template,
    save_template,
    template_path_for,
)


def test_slugify_handles_unicode_and_spaces() -> None:
    assert _slugify("FLY 4 YOU SRL") == "fly-4-you-srl"
    assert _slugify("Mövenpick Resort") == "m-venpick-resort"
    assert _slugify("") == "unknown-supplier"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    os.environ["STORAGE_DIR"] = str(tmp_path)
    from app.config import get_settings

    get_settings.cache_clear()

    result = {
        "hotelRows": [
            {
                "Hotel Name": "Acrotel",
                "Room Name": "Double Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Meal Plan": "Bed & Breakfast",
                "Currency": "EUR",
                "Rate Type": "Per Person Per Day",
            },
            {
                "Hotel Name": "Acrotel",
                "Room Name": "Superior Room",
                "Start Date": "2026-04-01",
                "End Date": "2026-06-13",
                "Meal Plan": "Half Board",
                "Currency": "EUR",
                "Rate Type": "Per Person Per Day",
            },
        ],
        "dynamicColumns": {
            "childColumns": [
                {"key": "CHD1(0-11.99)", "label": "CHD1(0-11.99) (% off)", "ageFrom": 0, "ageTo": 11.99}
            ]
        },
    }

    saved = save_template("FLY 4 YOU SRL", result)
    assert saved is not None and saved.exists()

    cached = load_template("FLY 4 YOU SRL")
    assert cached is not None
    assert "Double Room" in cached["rooms"]
    assert "Superior Room" in cached["rooms"]
    assert cached["mealPlans"] == ["Bed & Breakfast", "Half Board"]
    assert cached["currency"] == "EUR"
    assert cached["rateType"] == "Per Person Per Day"
    assert cached["dynamicChildColumns"][0]["key"] == "CHD1(0-11.99)"


def test_load_missing_supplier_returns_none(tmp_path: Path) -> None:
    os.environ["STORAGE_DIR"] = str(tmp_path)
    from app.config import get_settings

    get_settings.cache_clear()
    assert load_template("Nobody Inc") is None
    assert load_template(None) is None


def test_template_path_for_none_returns_none(tmp_path: Path) -> None:
    os.environ["STORAGE_DIR"] = str(tmp_path)
    from app.config import get_settings

    get_settings.cache_clear()
    assert template_path_for(None) is None
