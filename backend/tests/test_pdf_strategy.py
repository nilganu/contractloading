"""Tests for the PDF extraction strategy router."""
from __future__ import annotations

from app.services.pdf_strategy import choose_strategy


def _pdf(*pages):
    return {"pages": list(pages)}


def test_text_only_mode_forces_native_text() -> None:
    s = choose_strategy(_pdf({"text": "blah", "tables": [], "has_numeric_table": False}), "text_only")
    assert s == "native_text_llm"


def test_vision_required_forces_vision_only() -> None:
    s = choose_strategy(_pdf({"text": "lots of text", "tables": [{}], "has_numeric_table": True}), "vision_required")
    assert s == "vision_only"


def test_mostly_empty_pages_route_to_vision_only() -> None:
    pages = [{"text": "", "tables": [], "rate_token_hits": 0, "has_numeric_table": False}] * 3
    s = choose_strategy(_pdf(*pages), "auto")
    assert s == "vision_only"


def test_scrambled_text_routes_to_two_call_vision() -> None:
    pages = [
        {
            "text": "F L Y 4 Y O U Discount: 1 5 %",
            "tables": [{}],
            "scrambled": True,
            "rate_token_hits": 4,
            "has_numeric_table": False,
        }
    ]
    s = choose_strategy(_pdf(*pages), "auto")
    assert s == "two_call_vision"


def test_clean_numeric_table_routes_to_native_text_llm() -> None:
    pages = [
        {
            "text": "PERIOD ROOM DBL Currency EUR meal plan BB HB",
            "tables": [{"index": 1, "rows": [["FROM", "TO", "DBL"], ["2026-04-01", "2026-06-13", "34"]]}],
            "scrambled": False,
            "rate_token_hits": 5,
            "has_numeric_table": True,
        }
    ]
    s = choose_strategy(_pdf(*pages), "auto")
    assert s == "native_text_llm"


def test_rate_tokens_without_numeric_table_routes_to_two_call() -> None:
    pages = [
        {
            "text": "PRICE LIST PERIOD ROOM BB HB DBL SGL",
            "tables": [],
            "scrambled": False,
            "rate_token_hits": 6,
            "has_numeric_table": False,
        }
    ]
    s = choose_strategy(_pdf(*pages), "auto")
    assert s == "two_call_vision"
