"""Review-notes workbook shipped in the export ZIP.

Moonstride's import files have no place for the model's notes
(cancellation terms, ambiguities, amounts not found in the source), so
they go into a small separate workbook the reviewer reads before import.
"""
from __future__ import annotations

from pathlib import Path

from .canonical import ContractExtraction

HEADERS = ["Hotel", "Category", "Note"]
# Source ambiguities first: they are the ones that need action.
_ORDER = {"Source ambiguity": 0}


def write_review_notes(extraction: ContractExtraction, dest: Path) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Review notes"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    notes = sorted(
        extraction.notes or [],
        key=lambda n: (_ORDER.get(n.category, 1), n.hotel_name or "", n.category),
    )
    for n in notes:
        ws.append([n.hotel_name or "", n.category, n.note])
    if not notes:
        ws.append(["", "", "No notes."])
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 110
    for row in ws.iter_rows(min_row=2):
        row[2].alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    wb.save(dest)
    return dest
