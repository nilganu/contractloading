"""Tests that hotel-level fields from the skeleton are broadcast to every
row even when the fill call forgets them.

We test the broadcast logic directly by exercising the same loop in
isolation — the real two-call path needs a live OpenAI account.
"""
from __future__ import annotations

from typing import Any, Dict


def _broadcast(rows, skeleton):
    """Mirror the broadcast in _process_batch_two_call."""
    addr = skeleton.get("hotelAddress") or {}
    skeleton_broadcast: Dict[str, Any] = {
        "Hotel Name": skeleton.get("hotelName"),
        "Supplier": skeleton.get("supplier"),
        "Address Line 1": addr.get("addressLine1"),
        "Country Code ": addr.get("countryCode"),
        "State / Province / Region": addr.get("stateOrRegion"),
        "City / Area": addr.get("cityOrArea"),
        "Currency": skeleton.get("currency"),
        "Customer Price Currency": skeleton.get("currency"),
        "Rate Type": skeleton.get("rateType"),
    }
    room_broadcast = {
        r["name"]: {
            "Min Adult": r.get("minAdult"),
            "Max Adult": r.get("maxAdult"),
            "Max Pax": r.get("maxPax"),
        }
        for r in (skeleton.get("roomTypes") or [])
        if r.get("name")
    }
    for row in rows:
        for k, v in skeleton_broadcast.items():
            if v in (None, ""):
                continue
            if row.get(k) in (None, ""):
                row[k] = v
        rb = room_broadcast.get(row.get("Room Name"))
        if rb:
            for k, v in rb.items():
                if v in (None, "") :
                    continue
                if row.get(k) in (None, ""):
                    row[k] = v
    return rows


def test_broadcast_fills_missing_hotel_fields() -> None:
    skel = {
        "hotelName": "Acrotel Lily Ann Village",
        "supplier": "FLY 4 YOU SRL",
        "hotelAddress": {
            "addressLine1": "Nikiti",
            "cityOrArea": "Nikiti",
            "stateOrRegion": "Halkidiki",
            "countryCode": "GR",
        },
        "currency": "EUR",
        "rateType": "Per Person Per Day",
        "roomTypes": [
            {"name": "Superior Room", "minAdult": 2, "maxAdult": 3, "maxPax": 4},
        ],
    }
    rows = [
        {"Room Name": "Superior Room", "DBL": 43, "SGL": None, "Hotel Name": None},
    ]
    out = _broadcast(rows, skel)
    r = out[0]
    assert r["Hotel Name"] == "Acrotel Lily Ann Village"
    assert r["Supplier"] == "FLY 4 YOU SRL"
    assert r["Country Code "] == "GR"
    assert r["State / Province / Region"] == "Halkidiki"
    assert r["City / Area"] == "Nikiti"
    assert r["Currency"] == "EUR"
    assert r["Customer Price Currency"] == "EUR"
    assert r["Rate Type"] == "Per Person Per Day"
    assert r["Min Adult"] == 2
    assert r["Max Adult"] == 3
    assert r["Max Pax"] == 4


def test_broadcast_does_not_overwrite_existing_values() -> None:
    skel = {"supplier": "Skeleton Supplier", "hotelName": "Skeleton Hotel"}
    rows = [{"Supplier": "Existing", "Hotel Name": "Existing Hotel"}]
    out = _broadcast(rows, skel)
    assert out[0]["Supplier"] == "Existing"
    assert out[0]["Hotel Name"] == "Existing Hotel"


def test_broadcast_skips_null_skeleton_values() -> None:
    skel = {"hotelName": None, "supplier": None, "hotelAddress": {"countryCode": "EG"}}
    rows = [{"Room Name": "Suite"}]
    out = _broadcast(rows, skel)
    assert out[0].get("Hotel Name") is None
    assert out[0].get("Supplier") is None
    assert out[0]["Country Code "] == "EG"
