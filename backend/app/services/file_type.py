"""File type detection from extension + magic bytes."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

FileKind = Literal["xlsx", "xls", "pdf", "docx", "image", "unknown"]

_MAGIC: list[tuple[bytes, FileKind]] = [
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "xlsx"),  # zip-based (also docx) — resolved below
    (b"\xd0\xcf\x11\xe0", "xls"),  # OLE compound (legacy xls and old doc)
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"II*\x00", "image"),  # TIFF little-endian
    (b"MM\x00*", "image"),  # TIFF big-endian
]

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
_OFFICE_ZIP_HINT = {
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".docx": "docx",
}


def detect_file_kind(path: str | Path) -> FileKind:
    p = Path(path)
    ext = p.suffix.lower()

    head = b""
    try:
        with open(p, "rb") as fh:
            head = fh.read(8)
    except OSError:
        head = b""

    for prefix, kind in _MAGIC:
        if head.startswith(prefix):
            # zip-based — disambiguate xlsx vs docx by extension
            if kind == "xlsx" and ext in _OFFICE_ZIP_HINT:
                return _OFFICE_ZIP_HINT[ext]  # type: ignore[return-value]
            if kind == "xlsx":
                # Unknown zip; fall through to extension check
                break
            return kind

    if ext in _IMAGE_EXTS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext in {".xlsx", ".xlsm"}:
        return "xlsx"
    if ext == ".xls":
        return "xls"

    return "unknown"
