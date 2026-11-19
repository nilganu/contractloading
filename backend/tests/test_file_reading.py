"""File-reading fixes for the live extraction path:

- sheet split keeps formula results (not empty cells)
- hidden sheets are not treated as hotels
- legacy .xls is converted to .xlsx before the openpyxl-based steps
- pypdf (used by the PDF splitter) is a declared dependency
"""
from __future__ import annotations

import datetime as dt
import re
import zipfile
from pathlib import Path

import openpyxl
import pytest

from app.extraction.outline import outline_excel_locally
from app.extraction.splitters import (
    convert_xls_to_xlsx,
    list_hidden_excel_sheets,
    split_excel_sheet,
)


def _inject_cached_values(path: Path, sheet_xml: str, values: dict) -> None:
    """openpyxl never writes cached formula results; Excel does. Patch the
    sheet XML so the file looks like one saved by Excel."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == sheet_xml:
                xml = data.decode()
                for ref, val in values.items():
                    xml = re.sub(
                        rf'(<c r="{ref}"[^>]*>\s*<f>[^<]*</f>)\s*(<v\s*/>|<v></v>)?',
                        rf"\1<v>{val}</v>",
                        xml,
                    )
                data = xml.encode()
            zout.writestr(item, data)
    tmp.replace(path)


def test_split_writes_formula_results_not_blanks(tmp_path: Path) -> None:
    src = tmp_path / "contract.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hotel A"
    ws["B1"] = dt.datetime(2025, 11, 14)
    ws["A2"] = "=B1+1"          # season start date, like Volonline
    ws["B2"] = 100
    ws["C2"] = "=B2*0.5"        # child price as % of adult
    ws["D2"] = "=Z99"           # formula with no cached value
    wb.save(src)
    # 45976 = 2025-11-15 as an Excel serial
    _inject_cached_values(
        src, "xl/worksheets/sheet1.xml", {"A2": "45976", "C2": "50"}
    )

    out = split_excel_sheet(src, "Hotel A", tmp_path / "sub.xlsx")

    sub = openpyxl.load_workbook(out)["Hotel A"]
    assert sub["A2"].data_type != "f"
    assert sub["A2"].value in (45976, dt.datetime(2025, 11, 15))
    assert sub["C2"].value == 50
    # No cached value available -> keep the formula rather than lose it.
    assert sub["D2"].value == "=Z99"


def _workbook_with_hidden(tmp_path: Path) -> Path:
    path = tmp_path / "multi.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Hotel List"
    for name in ["Hotel A", "Hotel B", "Old Hotel C"]:
        wb.create_sheet(name)["A1"] = name
    wb["Old Hotel C"].sheet_state = "hidden"
    wb.save(path)
    return path


def test_list_hidden_excel_sheets(tmp_path: Path) -> None:
    assert list_hidden_excel_sheets(_workbook_with_hidden(tmp_path)) == [
        "Old Hotel C"
    ]


def test_outline_skips_hidden_sheets(tmp_path: Path) -> None:
    outline = outline_excel_locally(_workbook_with_hidden(tmp_path))
    assert [h.name for h in outline.hotels] == ["Hotel A", "Hotel B"]
    assert outline.is_multi_hotel


# --- .xls conversion (xlrd book faked; no .xls writer is installed) ---------


class _Cell:
    def __init__(self, ctype, value):
        self.ctype, self.value = ctype, value


class _Sheet:
    def __init__(self, name, rows, visibility=0, merged=()):
        self.name, self._rows, self.visibility = name, rows, visibility
        self.merged_cells = list(merged)
        self.nrows = len(rows)
        self.ncols = max((len(r) for r in rows), default=0)

    def cell(self, r, c):
        row = self._rows[r]
        return row[c] if c < len(row) else _Cell(0, "")


class _Book:
    datemode = 0

    def __init__(self, sheets):
        self._sheets = sheets

    def sheets(self):
        return self._sheets


def test_convert_xls_to_xlsx(tmp_path: Path, monkeypatch) -> None:
    import xlrd

    book = _Book([
        _Sheet("Hotel List", [[_Cell(xlrd.XL_CELL_TEXT, "index")]]),
        _Sheet(
            "Hotel A",
            [
                [_Cell(xlrd.XL_CELL_TEXT, "From"), _Cell(xlrd.XL_CELL_TEXT, "Price")],
                [_Cell(xlrd.XL_CELL_DATE, 45975.0), _Cell(xlrd.XL_CELL_NUMBER, 120.0)],
            ],
            merged=[(0, 1, 0, 2)],
        ),
        _Sheet("Old Hotel", [[_Cell(xlrd.XL_CELL_TEXT, "x")]], visibility=1),
    ])
    monkeypatch.setattr(xlrd, "open_workbook", lambda *a, **k: book)

    src = tmp_path / "legacy.xls"
    src.write_bytes(b"")
    out = convert_xls_to_xlsx(src, tmp_path / "legacy.xlsx")

    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Hotel List", "Hotel A", "Old Hotel"]
    ws = wb["Hotel A"]
    assert ws["A2"].value == dt.datetime(2025, 11, 14)  # serial 45975
    assert ws["B2"].value == 120
    assert "A1:B1" in {str(r) for r in ws.merged_cells.ranges}
    assert wb["Old Hotel"].sheet_state == "hidden"
    # And the converted file goes through the normal outline.
    assert [h.name for h in outline_excel_locally(out).hotels] == ["Hotel A"]


def test_pypdf_is_a_declared_dependency() -> None:
    req = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    assert re.search(r"^pypdf==", req, re.MULTILINE), (
        "splitters.py imports pypdf; without it PDF splitting silently "
        "falls back to sending the whole file per hotel"
    )
