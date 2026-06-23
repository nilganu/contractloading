"""Regression test runner.

Each fixture is a directory under tests/regression/fixtures/<name>/ containing:
  - input.xlsx | input.pdf | input.docx | input.png   (the source contract)
  - expected.json                                      (the expected NormalizedExtractionResult)
  - options.json                                       (optional, upload form defaults)

The runner runs the full job pipeline in STUB mode (no live OpenAI calls)
and compares the produced result to the expected JSON. The comparator is
forgiving about unstable fields (uuids, timestamps) but strict about
hotelRows, dynamicColumns, and validationIssues.

Usage: pytest tests/test_regression.py
Add a fixture:
  1. mkdir tests/regression/fixtures/my-contract
  2. drop input.<ext> in
  3. run `python -m tests.regression.runner --record my-contract` to
     generate expected.json from the current pipeline (review it carefully)
  4. commit fixture
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from app.services.cell_audit import audit_cells
from app.services.completeness import check_completeness
from app.services.file_type import detect_file_kind
from app.services.ir_builder import (
    build_ir_from_docx,
    build_ir_from_excel,
    build_ir_from_image,
    build_ir_from_pdf,
)
from app.services.normalizer import normalize_result
from app.services.parsers.docx import parse_docx
from app.services.parsers.excel import parse_excel
from app.services.parsers.image import parse_image
from app.services.parsers.pdf import parse_pdf
from app.services.stub_extractor import stub_extract
from app.services.validator import validate_result
from app.services.direct_vision_extractor import _filter_skeleton_rows


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _input_path_for(fixture_dir: Path) -> Path:
    for ext in ("xlsx", "xls", "pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff"):
        p = fixture_dir / f"input.{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"No input.* in {fixture_dir}")


def _load_options(fixture_dir: Path) -> Dict[str, Any]:
    p = fixture_dir / "options.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {
        "supplierDefault": None,
        "countryDefault": None,
        "cityAreaDefault": None,
        "currencyDefault": None,
        "statusDefault": "Open",
        "checkInDefault": None,
        "checkOutDefault": None,
        "childColumnMode": "dynamic_review",
        "preserveChildPositions": True,
        "extractionMode": "text_only",
    }


def run_pipeline(fixture_dir: Path) -> Dict[str, Any]:
    """Run the full pipeline in deterministic STUB mode for a fixture.

    Returns the final NormalizedExtractionResult-shaped dict.
    """
    # Force stub mode so no live API calls happen during regression tests.
    os.environ["OPENAI_API_KEY"] = ""

    input_path = _input_path_for(fixture_dir)
    options = _load_options(fixture_dir)
    kind = detect_file_kind(input_path)

    if kind in ("xlsx", "xls"):
        parsed = parse_excel(input_path, kind=kind)
        ir = build_ir_from_excel(parsed)
    elif kind == "pdf":
        parsed = parse_pdf(input_path)
        ir = build_ir_from_pdf(parsed)
    elif kind == "docx":
        parsed = parse_docx(input_path)
        ir = build_ir_from_docx(parsed)
    elif kind == "image":
        parsed = parse_image(input_path)
        ir = build_ir_from_image(parsed)
    else:
        raise RuntimeError(f"Unsupported file kind: {kind}")

    raw = stub_extract(ir, options)
    normalized = normalize_result(raw, options, input_path.name)
    normalized = _filter_skeleton_rows(normalized, source_file=input_path.name)

    # Completeness + cell audit
    comp_notes, _comp_warnings = check_completeness(ir, normalized)
    if comp_notes:
        normalized["extractionNotes"] = list(normalized.get("extractionNotes") or []) + comp_notes
    audit = audit_cells(ir, normalized)
    if audit["notes"]:
        normalized["extractionNotes"] = list(normalized.get("extractionNotes") or []) + audit["notes"]

    normalized["validationIssues"] = validate_result(normalized, options)
    return normalized


_UNSTABLE_KEYS = {"id", "_sourceRefs", "_confidence", "_warnings", "_cellMeta", "_reviewState"}


def _sanitize(value: Any) -> Any:
    """Strip unstable fields (uuids, confidence, source refs) for comparison."""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if k not in _UNSTABLE_KEYS}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _row_signature(row: Dict[str, Any]) -> tuple:
    return (
        row.get("Hotel Name"),
        row.get("Room Name"),
        row.get("Start Date"),
        row.get("End Date"),
        row.get("Meal Plan"),
    )


def diff_results(actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable differences. Empty list = matching."""
    diffs: List[str] = []

    a_rows = sorted(actual.get("hotelRows") or [], key=_row_signature)
    e_rows = sorted(expected.get("hotelRows") or [], key=_row_signature)

    if len(a_rows) != len(e_rows):
        diffs.append(f"hotelRows count: got {len(a_rows)}, expected {len(e_rows)}")

    a_san = [_sanitize(r) for r in a_rows]
    e_san = [_sanitize(r) for r in e_rows]
    for i, (a, e) in enumerate(zip(a_san, e_san)):
        if a != e:
            diffs.append(f"hotelRows[{i}] differs:\n  actual:   {a}\n  expected: {e}")

    a_dyn = [
        c.get("key")
        for c in (actual.get("dynamicColumns") or {}).get("childColumns") or []
    ]
    e_dyn = [
        c.get("key")
        for c in (expected.get("dynamicColumns") or {}).get("childColumns") or []
    ]
    if a_dyn != e_dyn:
        diffs.append(f"dynamicColumns.childColumns keys: got {a_dyn}, expected {e_dyn}")

    def _iss_key(i: Dict[str, Any]) -> tuple:
        return (
            i.get("severity") or "",
            i.get("field") or "",
            i.get("hotelName") or "",
        )

    a_iss = sorted((_iss_key(i) for i in actual.get("validationIssues") or []))
    e_iss = sorted((_iss_key(i) for i in expected.get("validationIssues") or []))
    if a_iss != e_iss:
        diffs.append(
            f"validationIssues count: got {len(a_iss)}, expected {len(e_iss)}"
        )

    return diffs


def list_fixtures() -> List[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def record_fixture(name: str) -> Path:
    """Run a fixture in stub mode and overwrite its expected.json. Use with
    care — review the result before committing."""
    fixture = FIXTURES_DIR / name
    result = run_pipeline(fixture)
    out = fixture / "expected.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--record", help="fixture name to (re)record expected.json")
    args = p.parse_args()
    if args.record:
        out = record_fixture(args.record)
        print(f"Wrote {out}")
    else:
        for fx in list_fixtures():
            result = run_pipeline(fx)
            print(
                f"{fx.name}: {len(result.get('hotelRows', []))} rows, "
                f"{len(result.get('extractionNotes', []))} notes, "
                f"{len(result.get('validationIssues', []))} issues"
            )
