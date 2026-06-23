"""When a contract has BOTH inline rate-table child columns (eg
"1st child 0 to 5.99") AND a more-specific Children Policy detailed
table (eg "1st CHD 2-5.99"), the structured extractor should use the
narrower / more accurate age range from the detailed table."""
from __future__ import annotations

from app.services.structured_excel_extractor import _narrow_child_age_from_overrides


def test_narrows_when_override_is_narrower_and_contained() -> None:
    inline = [
        {"col_idx": 6, "position": "first_child", "age_from": 0, "age_to": 5.99,
         "value_type": "percentage_of_adult"},
        {"col_idx": 7, "position": "first_child", "age_from": 6, "age_to": 10.99,
         "value_type": "percentage_of_adult"},
    ]
    overrides = [
        {"position": "first_child", "age_from": 2, "age_to": 5.99},
        {"position": "first_child", "age_from": 6, "age_to": 10.99},
    ]
    out = _narrow_child_age_from_overrides(inline, overrides)
    # The "0–5.99" column narrowed to "2–5.99"
    assert out[0]["age_from"] == 2
    assert out[0]["age_to"] == 5.99
    # The "6–10.99" column unchanged (override has same span)
    assert out[1]["age_from"] == 6
    assert out[1]["age_to"] == 10.99


def test_does_not_narrow_when_override_is_outside_range() -> None:
    inline = [
        {"col_idx": 6, "position": "first_child", "age_from": 0, "age_to": 5.99,
         "value_type": "percentage_of_adult"},
    ]
    overrides = [
        {"position": "first_child", "age_from": 6, "age_to": 10.99},
    ]
    out = _narrow_child_age_from_overrides(inline, overrides)
    # No change — override range isn't contained in inline range
    assert out[0]["age_from"] == 0
    assert out[0]["age_to"] == 5.99


def test_does_not_narrow_when_position_mismatches() -> None:
    inline = [
        {"col_idx": 6, "position": "first_child", "age_from": 0, "age_to": 5.99,
         "value_type": "percentage_of_adult"},
    ]
    overrides = [
        {"position": "second_child", "age_from": 2, "age_to": 5.99},
    ]
    out = _narrow_child_age_from_overrides(inline, overrides)
    assert out[0]["age_from"] == 0


def test_empty_overrides_returns_inline_unchanged() -> None:
    inline = [
        {"col_idx": 6, "position": "first_child", "age_from": 0, "age_to": 5.99}
    ]
    out = _narrow_child_age_from_overrides(inline, [])
    assert out == inline
