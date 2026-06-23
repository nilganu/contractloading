"""Per-supplier template cache.

On a successful export we snapshot the structural "skeleton" (room types,
dynamic child columns, currency, rate type, meal plans) keyed by a
supplier slug. On a new upload from the same supplier, the cached
skeleton can be passed to the LLM as a strong hint so the model doesn't
have to re-discover the layout.

Storage: ${STORAGE_DIR}/templates/<supplier_slug>.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import get_settings


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unknown-supplier"


def _templates_dir() -> Path:
    settings = get_settings()
    d = settings.storage_path / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def template_path_for(supplier: Optional[str]) -> Optional[Path]:
    if not supplier:
        return None
    return _templates_dir() / f"{_slugify(supplier)}.json"


def save_template(supplier: Optional[str], result: Dict[str, Any]) -> Optional[Path]:
    """Persist a structural snapshot for a supplier. Returns the file path
    or None if no supplier was provided."""
    if not supplier:
        return None
    rooms_seen: list[str] = []
    for r in result.get("hotelRows") or []:
        name = r.get("Room Name")
        if name and name not in rooms_seen:
            rooms_seen.append(name)
    periods_seen: list[Dict[str, Any]] = []
    period_keys: set[tuple] = set()
    for r in result.get("hotelRows") or []:
        sd = r.get("Start Date")
        ed = r.get("End Date")
        if not sd or not ed:
            continue
        key = (sd, ed)
        if key in period_keys:
            continue
        period_keys.add(key)
        periods_seen.append({"startDate": sd, "endDate": ed})
    meals_seen: list[str] = []
    for r in result.get("hotelRows") or []:
        m = r.get("Meal Plan")
        if m and m not in meals_seen:
            meals_seen.append(m)

    snapshot = {
        "supplier": supplier,
        "currency": (
            (result.get("hotelRows") or [{}])[0].get("Currency")
            if result.get("hotelRows")
            else None
        ),
        "rateType": (
            (result.get("hotelRows") or [{}])[0].get("Rate Type")
            if result.get("hotelRows")
            else None
        ),
        "rooms": rooms_seen,
        "periods": periods_seen,
        "mealPlans": meals_seen,
        "dynamicChildColumns": (result.get("dynamicColumns") or {}).get("childColumns") or [],
    }
    path = template_path_for(supplier)
    assert path is not None
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


def load_template(supplier: Optional[str]) -> Optional[Dict[str, Any]]:
    p = template_path_for(supplier)
    if not p or not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
