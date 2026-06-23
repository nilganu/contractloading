"""Tests for the LLM input trimming — must handle list-row AND dict-row tables."""
from __future__ import annotations

from app.services.llm_extractor import _trim_ir_for_prompt, _trim_table


def test_trim_table_handles_list_rows() -> None:
    table = {
        "index": 1,
        "rows": [
            ["a", "b", "c"],
            ["d", "e", "f"],
        ],
    }
    out = _trim_table(table, max_rows=1000, max_cols=100)
    assert out["rows"][0] == ["a", "b", "c"]


def test_trim_table_handles_dict_rows() -> None:
    table = {
        "title": "Price List",
        "columns": ["Period", "Board", "DBL"],
        "rows": [
            {"Period": "01.04-13.06", "Board": "BB", "DBL": "€34"},
            {"Period": "01.04-13.06", "Board": "HB", "DBL": "€50"},
        ],
    }
    out = _trim_table(table, max_rows=1000, max_cols=100)
    assert isinstance(out["rows"][0], dict)
    assert out["rows"][0]["Board"] == "BB"


def test_trim_ir_keeps_dict_rows_intact() -> None:
    ir = {
        "source_file": "x.pdf",
        "input_format": "pdf",
        "documents": [
            {
                "id": "Page:1",
                "classification": "hotel_contract",
                "source_ref": "x.pdf | Page 1",
                "summary": {},
                "raw_excerpt": "rate table",
                "tables": [
                    {
                        "index": 1,
                        "source": "vision",
                        "columns": ["Period", "Board", "DBL"],
                        "rows": [{"Period": "01.04-13.06", "Board": "BB", "DBL": 34}],
                    }
                ],
                "detected_hotel_name": "Acrotel",
            }
        ],
    }
    out = _trim_ir_for_prompt(ir)
    rows = out["documents"][0]["tables"][0]["rows"]
    assert isinstance(rows[0], dict)
    assert rows[0]["DBL"] == 34
