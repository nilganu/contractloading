"""Source reader: turns an uploaded contract into an addressed text view
that is sent to the LLM alongside (or instead of) the raw file.

Why: sending only the raw file means OpenAI's own, opaque conversion
decides what the model sees. Owning this step lets us

- give every Excel value its cell address (``F14=120``), with formula
  results, merged ranges, struck-through cells and comments, and hidden
  rows / columns / sheets left out;
- run a layout model (Docling: layout analysis + TableFormer table
  structure + OCR for scanned regions) over PDFs, Word files, images and
  emails, so tables arrive as real tables with page numbers;
- collect every number that appears in the source, so extracted prices
  can be checked deterministically (see ``grounding.py``).

Engines:
- ``excel-grid`` — our own openpyxl serializer (.xlsx; .xls is converted
  to .xlsx by the orchestrator before it gets here).
- ``docling``    — PDF, images, DOCX, PPTX, HTML, EML. Optional
  dependency (``requirements-docling.txt``); when it isn't installed the
  reader returns ``None`` and the pipeline sends the raw file as before.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# Above this the text view is too big to be useful next to the file; we
# fall back to the raw file only (a 15-hotel Volonline sheet is ~20k).
MAX_TEXT_CHARS = 400_000

EXCEL_EXTS = {".xlsx", ".xlsm"}
DOCLING_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ".docx", ".pptx", ".html", ".htm", ".eml",
}
# Formats where the model also gets the original file: PDF/images carry
# visual layout the text can't; DOCX is cheap. Excel is replaced by the
# grid (OpenAI's own spreadsheet conversion loses addresses and merges);
# formats OpenAI won't accept as files (.eml, .tif) go as text only.
SEND_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".pptx"}


@dataclass
class SourceView:
    engine: str
    text: str
    numbers: Set[float] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)
    send_file: bool = True
    # page number -> text, for paged documents (PDF). Lets the orchestrator
    # hand each hotel its own pages without parsing the PDF again.
    page_texts: dict = field(default_factory=dict)

    def slice_pages(self, pages: List[int]) -> "SourceView":
        """View limited to ``pages`` (1-based), renumbered like the
        sub-PDF the splitter writes (its page 1 = first listed page)."""
        if not self.page_texts:
            return self
        header = self.text.split("\n<!-- page ", 1)[0]
        parts = [header]
        for i, p in enumerate(pages, start=1):
            if p in self.page_texts:
                parts.append(
                    f"\n<!-- page {i} (original page {p}) -->\n{self.page_texts[p]}"
                )
        text = "\n".join(parts)
        return SourceView(
            engine=self.engine,
            text=text,
            numbers=numbers_in_text(text),
            warnings=list(self.warnings),
            send_file=self.send_file,
        )

    def llm_text(self) -> str:
        intro = (
            "SOURCE TEXT — produced by our document reader from the attached "
            "contract. "
        )
        if self.engine == "excel-grid":
            intro += (
                "It is the complete spreadsheet content with cell addresses; "
                "treat these values as authoritative. "
            )
        else:
            intro += (
                "Text and tables were reconstructed by a layout model "
                "(page markers <!-- page N -->). Where the text came from the "
                "PDF text layer it is exact; where it was OCR'd or a table "
                "looks misaligned, check the attached page images and prefer "
                "what the page shows. "
            )
        if self.warnings:
            intro += "Reader warnings: " + " ".join(self.warnings) + " "
        return intro + "\n\n" + self.text


# --------------------------------------------------------------------------
# Numbers (shared with grounding)
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![\w.])-?\d[\d.,' ]*\d|(?<![\w.])\d")


def numbers_in_text(text: str) -> Set[float]:
    """Every number in ``text``, under both decimal conventions.

    '1.234,50' and '1,234.50' both yield 1234.5; ambiguous '1,250' yields
    both 1250 and 1.25. Over-collecting is fine: the set is only used to
    ask "does this extracted value appear anywhere in the source?".
    """
    out: Set[float] = set()
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).replace(" ", "").replace("'", "")
        for cand in _interpretations(raw):
            out.add(round(cand, 4))
    return out


def _interpretations(raw: str) -> List[float]:
    cands: List[str] = []
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            cands.append(raw.replace(".", "").replace(",", "."))
        else:
            cands.append(raw.replace(",", ""))
    elif "," in raw:
        cands += [raw.replace(",", "."), raw.replace(",", "")]
    elif raw.count(".") > 1:
        cands.append(raw.replace(".", ""))
    else:
        cands += [raw]
        if re.fullmatch(r"\d{1,3}\.\d{3}", raw):
            cands.append(raw.replace(".", ""))  # 1.250 = 1250 (EU)
    vals = []
    for c in cands:
        try:
            vals.append(float(c))
        except ValueError:
            pass
    return vals


# --------------------------------------------------------------------------
# Excel grid
# --------------------------------------------------------------------------


def _fmt_value(value, number_format: str) -> str:
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        if "%" in (number_format or ""):
            return f"{value * 100:g}%"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, float):
            return f"{round(value, 6):g}"
        return str(value)
    text = str(value).strip()
    return json.dumps(text, ensure_ascii=False)


def _hidden_columns(ws) -> Set[str]:
    """Letters of hidden columns. A dimension can cover a range of columns
    (``<col min=5 max=7 hidden=1>`` is stored once, under 'E')."""
    from openpyxl.utils import column_index_from_string, get_column_letter

    out: Set[str] = set()
    for key, d in ws.column_dimensions.items():
        if not d.hidden:
            continue
        lo = d.min or column_index_from_string(key)
        hi = max(d.max or lo, lo)
        out.update(get_column_letter(i) for i in range(lo, hi + 1))
    return out


def _cached_formula_values(path: Path, wb) -> dict:
    """{(sheet, row, col): cached value} for formula cells only. The
    data_only copy is opened read-only and streamed once, so a workbook is
    never held in memory twice."""
    import openpyxl

    wanted = {
        ws.title: {(c.row, c.column) for row in ws.iter_rows() for c in row if c.data_type == "f"}
        for ws in wb.worksheets if ws.sheet_state == "visible"
    }
    wanted = {k: v for k, v in wanted.items() if v}
    if not wanted:
        return {}
    out = {}
    vwb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for title, coords in wanted.items():
            for r_idx, row in enumerate(vwb[title].iter_rows(values_only=True), start=1):
                for c_idx, v in enumerate(row, start=1):
                    if (r_idx, c_idx) in coords:
                        out[(title, r_idx, c_idx)] = v
    finally:
        vwb.close()
    return out


def read_excel(path: Path) -> SourceView:
    import openpyxl
    from openpyxl.utils import get_column_letter

    wb = openpyxl.load_workbook(path)
    cached_values = _cached_formula_values(path, wb)
    parts: List[str] = [
        f"# Workbook {path.name}",
        "Cells are listed per row as ADDRESS=value. Empty cells, hidden "
        "rows, hidden columns and hidden sheets are left out. "
        "~~value~~ means the cell is struck through (cancelled). "
        "Formula cells show their calculated result.",
    ]
    warnings: List[str] = []
    numbers: Set[float] = set()

    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            warnings.append(f"Hidden sheet '{ws.title}' not read.")
            continue
        hidden_cols = _hidden_columns(ws)
        hidden_rows = {k for k, d in ws.row_dimensions.items() if d.hidden}
        parts.append(f"\n## Sheet: {ws.title} ({ws.dimensions})")
        merges = [str(r) for r in ws.merged_cells.ranges]
        if merges:
            parts.append("Merged ranges: " + ", ".join(merges))
        notes: List[str] = []
        skipped_rows = 0
        for row in ws.iter_rows():
            if not row:
                continue
            r = row[0].row
            if r in hidden_rows:
                if any(c.value is not None for c in row):
                    skipped_rows += 1
                continue
            cells: List[str] = []
            for cell in row:
                if cell.value is None:
                    continue
                col = get_column_letter(cell.column)
                if col in hidden_cols:
                    continue
                value = cell.value
                if cell.data_type == "f":
                    cached = cached_values.get((ws.title, r, cell.column))
                    value = cached if cached is not None else value
                if value is None or (isinstance(value, str) and not value.strip()):
                    continue
                shown = _fmt_value(value, cell.number_format)
                if cell.font is not None and cell.font.strike:
                    shown = f"~~{shown}~~"
                cells.append(f"{col}{r}={shown}")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numbers.add(round(float(value), 4))
                    if "%" in (cell.number_format or ""):
                        numbers.add(round(float(value) * 100, 4))
                elif isinstance(value, str):
                    numbers |= numbers_in_text(value)
                if cell.comment is not None and cell.comment.text:
                    notes.append(
                        f"{col}{r} comment: "
                        + json.dumps(cell.comment.text.strip(), ensure_ascii=False)
                    )
            if cells:
                parts.append(f"R{r}: " + " | ".join(cells))
        if notes:
            parts.append("Comments:\n" + "\n".join(notes))
        if skipped_rows:
            warnings.append(
                f"Sheet '{ws.title}': {skipped_rows} hidden row(s) not read."
            )

    return SourceView(
        engine="excel-grid",
        text="\n".join(parts),
        numbers=numbers,
        warnings=warnings,
        send_file=False,
    )


# --------------------------------------------------------------------------
# Docling (PDF, images, DOCX, PPTX, HTML, EML)
# --------------------------------------------------------------------------

_converters: dict = {}
_converter_lock = threading.Lock()

# OCR costs ~35 s/page on CPU, so it only runs when a PDF needs it: a page
# with (almost) no text layer, or with a large embedded picture (a rate
# table pasted in as an image, as in the Acrotel contract).
_OCR_MIN_CHARS = 100
_OCR_IMAGE_COVER = 0.15


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def pdf_needs_ocr(path: Path) -> bool:
    """True if any page lacks a usable text layer or is largely a picture."""
    import pdfplumber

    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                if len(page.chars) < _OCR_MIN_CHARS:
                    return True
                area = float(page.width * page.height) or 1.0
                covered = 0.0
                for im in page.images:
                    w = min(im["x1"], page.width) - max(im["x0"], 0)
                    h = min(im["bottom"], page.height) - max(im["top"], 0)
                    covered += max(0.0, w) * max(0.0, h)
                if covered / area >= _OCR_IMAGE_COVER:
                    return True
    except Exception:  # noqa: BLE001 - unreadable text layer: OCR it
        return True
    return False


def _get_converter(ocr: bool = True):
    """One converter per OCR setting per process: model loading takes
    seconds."""
    _converter = _converters.get(ocr)
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
        )
        from docling.document_converter import (
            DocumentConverter,
            ImageFormatOption,
            PdfFormatOption,
        )

        pdf_opts = PdfPipelineOptions()
        pdf_opts.do_ocr = ocr
        pdf_opts.do_table_structure = True
        pdf_opts.table_structure_options.mode = TableFormerMode.ACCURATE
        pdf_opts.table_structure_options.do_cell_matching = True
        _converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=pdf_opts),
            }
        )
        _converters[ocr] = _converter
    return _converter


def read_with_docling(path: Path) -> SourceView:
    # Docling's models are not documented as thread-safe and the
    # orchestrator runs hotels in parallel: serialise conversions.
    ext = path.suffix.lower()
    # Images always need OCR; Office/HTML/EML have real text (OCR unused).
    ocr = pdf_needs_ocr(path) if ext == ".pdf" else ext not in {
        ".docx", ".pptx", ".html", ".htm", ".eml",
    }
    with _converter_lock:
        result = _get_converter(ocr).convert(str(path))
    doc = result.document
    warnings: List[str] = []
    if ext == ".pdf" and ocr:
        warnings.append(
            "Scanned or image-based content: values were read by OCR; "
            "check them against the page image."
        )
    page_nos = sorted(doc.pages.keys()) if getattr(doc, "pages", None) else []
    parts = [
        f"# Document {path.name} (parsed by layout model; tables are "
        "reconstructed from the page; scanned regions were OCR'd)"
    ]
    page_texts = {}
    if page_nos:
        for p in page_nos:
            md = doc.export_to_markdown(
                page_no=p, escape_html=False, escape_underscores=False
            )
            page_texts[p] = md
            parts.append(f"\n<!-- page {p} -->\n{md}")
            if len(md.strip()) < 40:
                warnings.append(
                    f"Page {p}: almost no text found; the model must rely "
                    "on the page image."
                )
    else:
        parts.append(
            doc.export_to_markdown(escape_html=False, escape_underscores=False)
        )
    text = "\n".join(parts)
    n_tables = len(getattr(doc, "tables", []) or [])
    if path.suffix.lower() == ".pdf" and n_tables == 0:
        warnings.append("No tables detected in the PDF.")
    return SourceView(
        engine="docling",
        text=text,
        numbers=numbers_in_text(text),
        warnings=warnings,
        send_file=path.suffix.lower() in SEND_FILE_EXTS,
        page_texts=page_texts,
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def read_source(path: Path) -> Optional[SourceView]:
    """Addressed text view of ``path``, or ``None`` when we have no reader
    for it (caller then sends the raw file only). Never raises: a reader
    failure must not lose the extraction."""
    from ..config import get_settings

    if get_settings().reader_mode == "raw":
        return None
    ext = path.suffix.lower()
    try:
        if ext in EXCEL_EXTS:
            view = read_excel(path)
        elif ext in DOCLING_EXTS:
            if not docling_available():
                logger.info("reader: docling not installed; raw file for %s", path.name)
                return None
            view = read_with_docling(path)
        else:
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("reader failed for %s (%s); sending raw file", path.name, e)
        return None
    if len(view.text) > MAX_TEXT_CHARS:
        logger.warning(
            "reader: %s text view is %d chars (> %d); sending raw file",
            path.name, len(view.text), MAX_TEXT_CHARS,
        )
        return None
    logger.info(
        "reader: %s via %s, %d chars, %d numbers, %d warning(s)",
        path.name, view.engine, len(view.text), len(view.numbers), len(view.warnings),
    )
    return view
