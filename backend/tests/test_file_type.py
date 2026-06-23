from pathlib import Path

from app.services.file_type import detect_file_kind


def test_detects_xlsx(sample_xlsx: Path) -> None:
    assert detect_file_kind(sample_xlsx) == "xlsx"


def test_detects_image(tmp_path: Path) -> None:
    p = tmp_path / "fake.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    assert detect_file_kind(p) == "image"


def test_detects_pdf(tmp_path: Path) -> None:
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"%PDF-1.4\n%hello")
    assert detect_file_kind(p) == "pdf"


def test_unknown(tmp_path: Path) -> None:
    p = tmp_path / "thing.bin"
    p.write_bytes(b"random")
    assert detect_file_kind(p) == "unknown"
