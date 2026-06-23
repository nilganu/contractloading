"""pytest entry point for regression fixtures.

Discovers every directory under tests/regression/fixtures/ that contains
both input.* and expected.json, runs the deterministic stub pipeline on
the input, and asserts the result matches expected.json (modulo unstable
fields like UUIDs and confidence scores).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.regression.runner import diff_results, list_fixtures, run_pipeline


def _fixture_ids():
    return [p.name for p in list_fixtures() if (p / "expected.json").exists()]


@pytest.mark.parametrize("fixture_name", _fixture_ids())
def test_regression_fixture(fixture_name: str) -> None:
    fixture_dir = Path(__file__).resolve().parent / "regression" / "fixtures" / fixture_name
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))
    actual = run_pipeline(fixture_dir)
    diffs = diff_results(actual, expected)
    assert not diffs, f"Regression for {fixture_name!r} failed:\n" + "\n\n".join(diffs)
