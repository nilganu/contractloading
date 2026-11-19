"""Source reader, grounding check, review notes and eval scoring."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import openpyxl
import pytest
from openpyxl.comments import Comment
from openpyxl.styles import Font

from app.config import get_settings
from app.extraction import extractor, reader
from app.extraction.canonical import (
    ContractExtraction, HotelExtraction, HotelMetadata, Rate, Season,
)
from app.extraction.grounding import add_grounding_notes, ungrounded_amounts
from app.extraction.reader import SourceView, numbers_in_text, read_excel, read_source
from app.extraction.review_notes import write_review_notes


@pytest.fixture(autouse=True)
def _parsed_mode(monkeypatch):
    monkeypatch.setenv("READER_MODE", "parsed")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "c.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hotel A"
    ws["A1"] = "Hotel A rates"
    ws.merge_cells("A1:C1")
    ws["A2"], ws["B2"], ws["C2"] = "From", "DBL", "Child"
    ws["A3"] = dt.datetime(2026, 5, 1)
    ws["B3"] = 120.5
    ws["C3"] = 0.5
    ws["C3"].number_format = "0%"
    ws["B4"] = 99
    ws["B4"].font = Font(strike=True)
    ws["B4"].comment = Comment("cancelled rate", "supplier")
    ws["A5"] = "secret old row"
    ws.row_dimensions[5].hidden = True
    ws["E2"] = "internal"
    ws.column_dimensions["E"].hidden = True
    wb.create_sheet("Old hotel")["A1"] = 777
    wb["Old hotel"].sheet_state = "hidden"
    wb.save(path)
    return path


def test_excel_grid_addresses_and_layout(tmp_path: Path) -> None:
    view = read_excel(_contract(tmp_path))
    t = view.text
    assert view.engine == "excel-grid" and view.send_file is False
    assert "Merged ranges: A1:C1" in t
    assert "A3=2026-05-01" in t and "B3=120.5" in t
    assert "C3=50%" in t
    assert "B4=~~99~~" in t and 'B4 comment: "cancelled rate"' in t
    assert "secret old row" not in t        # hidden row
    assert "internal" not in t              # hidden column
    assert "777" not in t                   # hidden sheet
    assert {120.5, 0.5, 50.0, 99.0} <= view.numbers
    assert any("Hidden sheet 'Old hotel'" in w for w in view.warnings)


def test_numbers_in_text_both_decimal_conventions() -> None:
    nums = numbers_in_text("€1.234,50 | $1,234.50 | 62,00 | 1,250 | 15.09.2026")
    assert 1234.5 in nums and 62.0 in nums
    assert {1250.0, 1.25} <= nums


def test_read_source_raw_mode_and_unknown_types(tmp_path, monkeypatch) -> None:
    path = _contract(tmp_path)
    assert read_source(path) is not None
    monkeypatch.setenv("READER_MODE", "raw")
    get_settings.cache_clear()
    assert read_source(path) is None
    monkeypatch.setenv("READER_MODE", "parsed")
    get_settings.cache_clear()
    other = tmp_path / "x.json"
    other.write_text("{}")
    assert read_source(other) is None


def test_read_source_without_docling_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reader, "docling_available", lambda: False)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert read_source(pdf) is None


def test_read_source_never_raises(tmp_path) -> None:
    bad = tmp_path / "broken.xlsx"
    bad.write_bytes(b"not a workbook")
    assert read_source(bad) is None


class _FakeFiles:
    def __init__(self):
        self.uploaded = []

    def create(self, file, purpose):
        self.uploaded.append(purpose)
        return type("U", (), {"id": f"file-{len(self.uploaded)}"})()


class _FakeClient:
    def __init__(self):
        self.files = _FakeFiles()


def test_upload_excel_sends_grid_not_file(tmp_path) -> None:
    client = _FakeClient()
    file_id, blocks = extractor.upload_file(client, _contract(tmp_path))
    assert file_id is None and client.files.uploaded == []
    assert [b["type"] for b in blocks] == ["input_text"]
    assert "cell addresses" in blocks[0]["text"]


def test_upload_pdf_sends_file_and_text(tmp_path) -> None:
    client = _FakeClient()
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    view = SourceView(engine="docling", text="<!-- page 1 -->\n| a |", send_file=True)
    file_id, blocks = extractor.upload_file(client, pdf, view)
    assert file_id == "file-1"
    assert [b["type"] for b in blocks] == ["input_file", "input_text"]


def test_upload_without_view_is_raw_file(tmp_path) -> None:
    client = _FakeClient()
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    file_id, blocks = extractor.upload_file(client, pdf, None)
    assert file_id == "file-1" and [b["type"] for b in blocks] == ["input_file"]
    assert extractor.as_content(blocks[0]) == [blocks[0]]


def test_slice_pages_renumbers() -> None:
    v = SourceView(
        engine="docling",
        text="# Doc\n\n<!-- page 1 -->\nA 10\n\n<!-- page 2 -->\nB 20\n\n<!-- page 3 -->\nC 30",
        page_texts={1: "A 10", 2: "B 20", 3: "C 30"},
    )
    s = v.slice_pages([3])
    assert "<!-- page 1 (original page 3) -->" in s.text
    assert "C 30" in s.text and "A 10" not in s.text
    assert 30.0 in s.numbers and 10.0 not in s.numbers


def _extraction(dbl: float) -> ContractExtraction:
    return ContractExtraction(
        source_filename="c.xlsx",
        is_multi_hotel=False,
        detected_rate_type="Per Room Per Night",
        supplements=[],
        notes=[],
        hotels=[
            HotelExtraction(
                metadata=HotelMetadata(name="Hotel A"),
                rooms=[], meal_plans=[], child_policy=[],
                seasons=[Season(label="S1", start_date="2026-05-01", end_date="2026-05-31")],
                rates=[Rate(room_name="DBL", season_label="S1", meal_code="BB", dbl=dbl)],
            )
        ],
    )


def test_grounding_flags_only_unknown_amounts() -> None:
    view = SourceView(engine="excel-grid", text="", numbers={120.5, 0.5})
    assert ungrounded_amounts(_extraction(120.5), view) == []
    assert ungrounded_amounts(_extraction(50), view) == []  # 0.5 shown as 50%
    x = _extraction(130)
    assert add_grounding_notes(x, view) == 1
    assert x.notes[-1].category == "Source ambiguity"
    assert "DBL / S1 / BB dbl = 130" in x.notes[-1].note


def test_grounding_without_view_is_noop() -> None:
    x = _extraction(130)
    assert add_grounding_notes(x, None) == 0 and x.notes == []


def test_review_notes_workbook(tmp_path) -> None:
    x = _extraction(130)
    add_grounding_notes(x, SourceView(engine="excel-grid", text="", numbers={1.0}))
    out = write_review_notes(x, tmp_path / "notes.xlsx")
    ws = openpyxl.load_workbook(out).active
    assert [c.value for c in ws[1]] == ["Hotel", "Category", "Note"]
    assert ws["B2"].value == "Source ambiguity"


def test_eval_scoring() -> None:
    from eval.scoring import score

    s = score(_extraction(120.5), _extraction(120.5))
    assert s["rate_cells"] == 1.0 and s["extra_cells"] == 0 and s["hotels"] == 1.0
    s = score(_extraction(130), _extraction(120.5))
    assert s["rate_cells"] == 0.0
    assert s["wrong_cells_sample"][0]["got"] == 130
