from pathlib import Path

from app.services.classifier import classify_excel_sheet
from app.services.parsers.excel import parse_excel


def test_hotel_list_is_index(sample_xlsx: Path) -> None:
    parsed = parse_excel(sample_xlsx)
    index_sheet = next(s for s in parsed["sheets"] if s["name"] == "Hotel List")
    kind, _ = classify_excel_sheet(index_sheet)
    assert kind == "index_reference"


def test_hotel_named_sheet_is_contract(sample_xlsx: Path) -> None:
    parsed = parse_excel(sample_xlsx)
    hotel_sheet = next(s for s in parsed["sheets"] if "Barcel" in s["name"])
    kind, _ = classify_excel_sheet(hotel_sheet)
    assert kind == "hotel_contract"
