from pathlib import Path

from app.services.parsers.excel import parse_excel


def test_enumerates_all_sheets(sample_xlsx: Path) -> None:
    parsed = parse_excel(sample_xlsx)
    names = parsed["sheet_names"]
    assert "Hotel List" in names
    assert "Barceló Tiran Sharm Resort"[:31] in names
    assert len(parsed["sheets"]) == len(names)


def test_each_sheet_has_used_range(sample_xlsx: Path) -> None:
    parsed = parse_excel(sample_xlsx)
    for sheet in parsed["sheets"]:
        assert ":" in sheet["used_range"]
        assert isinstance(sheet["rows"], list)


def test_cell_values_preserved(sample_xlsx: Path) -> None:
    parsed = parse_excel(sample_xlsx)
    hotel_sheet = next(s for s in parsed["sheets"] if "Barcel" in s["name"])
    flat = []
    for r in hotel_sheet["rows"]:
        for c in r:
            if c["value"] is not None:
                flat.append(str(c["value"]))
    flat = " ".join(flat)
    assert "FROM" in flat
    assert "CHD(2-11.99)" in flat
