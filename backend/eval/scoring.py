"""Field-level scoring of a ContractExtraction against a verified one.

Matching is by normalised names, so cosmetic differences ("Superior GV"
vs "superior gv") don't count as errors, but wrong numbers do.

Scores (each a fraction 0..1, plus raw counts):
- hotels          recall of expected hotel names
- rooms/seasons   recall of expected room names / season date ranges
- rate_cells      expected non-empty sgl/dbl/tpl/qdp cells whose value
                  matches exactly (key: hotel, room, season dates, meal)
- extra_cells     non-empty cells in the output that don't exist in the
                  expected result (invented rows)
- supplements     expected supplements found by name with equal cost
- child_bands     expected child age bands found with equal value
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from app.extraction.canonical import ContractExtraction

_CELLS = ("sgl", "dbl", "tpl", "qdp", "extra_bed_adult", "extra_bed_child")


def _n(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _eq(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 0.005


def _rate_cells(x: ContractExtraction) -> Dict[Tuple, float]:
    cells: Dict[Tuple, float] = {}
    for h in x.hotels:
        seasons = {s.label: (s.start_date, s.end_date) for s in h.seasons}
        for r in h.rates:
            dates = seasons.get(r.season_label, (r.season_label, ""))
            for f in _CELLS:
                v = getattr(r, f, None)
                if v is not None:
                    key = (_n(h.metadata.name), _n(r.room_name), dates, _n(r.meal_code), f)
                    cells[key] = v
    return cells


def _ratio(hit: int, total: int) -> float:
    return 1.0 if total == 0 else hit / total


def score(got: ContractExtraction, expected: ContractExtraction) -> Dict[str, Any]:
    g_hotels = {_n(h.metadata.name): h for h in got.hotels}
    e_hotels = {_n(h.metadata.name): h for h in expected.hotels}
    hotel_hits = [k for k in e_hotels if k in g_hotels]

    room_hit = room_tot = season_hit = season_tot = band_hit = band_tot = 0
    for k, eh in e_hotels.items():
        gh = g_hotels.get(k)
        g_rooms = {_n(r.name) for r in gh.rooms} if gh else set()
        g_seasons = {(s.start_date, s.end_date) for s in gh.seasons} if gh else set()
        g_bands = (
            {(b.age_from, b.age_to, b.value) for b in gh.child_policy} if gh else set()
        )
        for r in eh.rooms:
            room_tot += 1
            room_hit += _n(r.name) in g_rooms
        for s in eh.seasons:
            season_tot += 1
            season_hit += (s.start_date, s.end_date) in g_seasons
        for b in eh.child_policy:
            band_tot += 1
            band_hit += any(
                _eq(b.age_from, a) and _eq(b.age_to, t) and _eq(b.value, v)
                for a, t, v in g_bands
            )

    e_cells, g_cells = _rate_cells(expected), _rate_cells(got)
    cell_hit = sum(1 for k, v in e_cells.items() if k in g_cells and _eq(g_cells[k], v))
    wrong = sorted(
        (k, v, g_cells.get(k)) for k, v in e_cells.items()
        if not (k in g_cells and _eq(g_cells[k], v))
    )
    extra = [k for k in g_cells if k not in e_cells]

    g_supp = {(_n(s.hotel_name), _n(s.name)): s for s in got.supplements or []}
    supp_hit = sum(
        1 for s in expected.supplements or []
        if (k := (_n(s.hotel_name), _n(s.name))) in g_supp
        and _eq(g_supp[k].supplier_cost, s.supplier_cost)
    )
    supp_tot = len(expected.supplements or [])

    return {
        "hotels": _ratio(len(hotel_hits), len(e_hotels)),
        "rooms": _ratio(room_hit, room_tot),
        "seasons": _ratio(season_hit, season_tot),
        "rate_cells": _ratio(cell_hit, len(e_cells)),
        "extra_cells": len(extra),
        "supplements": _ratio(supp_hit, supp_tot),
        "child_bands": _ratio(band_hit, band_tot),
        "counts": {
            "rate_cells_expected": len(e_cells),
            "rate_cells_correct": cell_hit,
            "supplements_expected": supp_tot,
        },
        "wrong_cells_sample": [
            {"key": list(map(str, k)), "expected": v, "got": g} for k, v, g in wrong[:20]
        ],
    }
