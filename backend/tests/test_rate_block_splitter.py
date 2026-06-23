"""Tests for the hotel-sheet rate-block splitter."""
from __future__ import annotations

from app.services.rate_block_splitter import split_sheet_into_rate_blocks


def _cell(v):
    return {"value": v, "row": 0, "col": 0, "type": None, "style": None}


def _row(*vals):
    return [_cell(v) for v in vals]


def test_no_markers_returns_single_block() -> None:
    sheet = {
        "name": "Acrotel",
        "rows": [
            _row("Acrotel Lily Ann Village"),
            _row("Currency", "EUR"),
            _row("FROM", "TO", "Room", "DBL"),
            _row("01/04/2026", "13/06/2026", "Double", 34),
        ],
    }
    blocks = split_sheet_into_rate_blocks(sheet)
    assert len(blocks) == 1
    assert blocks[0]["rows"] is sheet["rows"]
    assert blocks[0]["title"] is None


def test_two_markers_split_into_two_blocks() -> None:
    """A sheet with both Contract Rate and Booking Window sections is split."""
    sheet = {
        "name": "Hotel X",
        "rows": [
            _row("Hotel X"),                           # 0 - preamble
            _row("Currency", "EUR"),                   # 1 - preamble
            _row("Basic treatment: All Inclusive"),    # 2 - preamble
            _row("Contract Rate", None),               # 3 - block 1 header
            _row("FROM", "TO", "Room", "DBL"),         # 4
            _row("01/04/2026", "30/06/2026", "DR", 50),# 5 - data
            _row("Booking Window 30 days"),            # 6 - block 2 header
            _row("FROM", "TO", "Room", "DBL"),         # 7
            _row("01/04/2026", "30/06/2026", "DR", 40),# 8 - data
        ],
    }
    blocks = split_sheet_into_rate_blocks(sheet)
    assert len(blocks) == 2
    assert "contract rate" in blocks[0]["title"]
    assert "booking window" in blocks[1]["title"]
    # Each block includes the preamble (3 rows) plus its own section
    assert all(len(b["rows"]) >= 3 for b in blocks)
    # Block index + block count populated for downstream reporting
    assert blocks[0]["block_index"] == 0 and blocks[0]["block_count"] == 2
    assert blocks[1]["block_index"] == 1


def test_data_row_not_treated_as_header() -> None:
    """A data row that happens to contain a marker word (eg in a column
    header inside a cell) shouldn't be promoted to a block boundary just
    because of one word. The splitter checks numeric density."""
    sheet = {
        "name": "Y",
        "rows": [
            _row("Hotel Y"),
            _row("Contract Rate"),
            _row("FROM", "TO", "DBL", "SGL", "TPL"),
            _row("01/04/2026", "30/06/2026", 50, 75, 130),
            _row("01/07/2026", "31/08/2026", 60, 90, 155),
            _row("01/09/2026", "31/10/2026", 55, 82, 142),
        ],
    }
    blocks = split_sheet_into_rate_blocks(sheet)
    # Only one block found — three rate rows shouldn't be misread as headers
    assert len(blocks) == 1
    assert blocks[0]["title"] is not None
    assert "contract rate" in blocks[0]["title"]


def test_multiple_block_types_volonline_style() -> None:
    """Volonline-style sheet with Booking Window + Contract Rate + Early Booking."""
    sheet = {
        "name": "Volonline Hotel",
        "rows": [
            _row("Hotel"),
            _row("Basic treatment: Hard all inclusive"),
            _row("ITALIAN MARKET RATE SEASON - BW 18.07-31.10"),  # block 1
            _row("FROM", "TO", "release", "SUPERIOR GV"),
            _row("01/11/2025", "14/11/2025", 5, 40),
            _row("ITALIAN MARKET RATE SEASON - Contract Rate"),    # block 2
            _row("FROM", "TO", "release", "SUPERIOR GV"),
            _row("01/11/2025", "24/12/2025", 7, 55),
            _row("Early Booking 10%"),                              # block 3
            _row("FROM", "TO", "release"),
            _row("01/11/2025", "31/03/2026", 14),
        ],
    }
    blocks = split_sheet_into_rate_blocks(sheet)
    assert len(blocks) == 3
    titles = " ".join(b["title"] for b in blocks)
    assert "bw" in titles or "booking window" in titles
    assert "contract rate" in titles
    assert "early booking" in titles
