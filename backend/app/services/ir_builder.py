"""Build the normalized intermediate representation (IR) for downstream LLM input.

Whatever the source file is, we collapse it into a single shape:

{
  "source_file": str,
  "input_format": "xlsx" | "xls" | "pdf" | "docx" | "image" | "mixed",
  "documents": [
      {
        "kind": "excel_sheet" | "pdf_page" | "docx_section" | "image",
        "id": str,                       # eg "Sheet:Charmillion Sea Life" or "Page:4"
        "classification": "hotel_contract" | "index_reference" | ...,
        "source_ref": str,               # eg "Contract.xlsx | Sheet!A1:S35"
        "summary": {...},
        "raw_excerpt": str,              # text / tab table
        "tables": [...],                 # optional
        "detected_hotel_name": str | None
      }
  ]
}
"""
from __future__ import annotations

from typing import Any, Dict, List

from .classifier import classify_excel_sheet, classify_pdf_page
from .parsers.excel import sheet_text_preview
from .parsers.pdf import page_text_preview
from .rate_block_splitter import split_sheet_into_rate_blocks


def build_ir_from_excel(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Build IR from a parsed Excel workbook.

    Hotel-contract sheets are further split into one IR document per
    detected rate block (Contract Rate / Booking Window / Early Booking /
    SPO / etc.) so the LLM extractor can focus on one block at a time.
    Index/reference sheets and support_notes sheets are kept whole.
    """
    documents: List[Dict[str, Any]] = []
    for sheet in parsed.get("sheets", []):
        kind, details = classify_excel_sheet(sheet)

        if kind == "hotel_contract":
            sub_sheets = split_sheet_into_rate_blocks(sheet)
        else:
            sub_sheets = [sheet]

        for sub in sub_sheets:
            sub_name = sub.get("name") or sheet["name"]
            source_ref = (
                f"{parsed['source_file']} | {sub_name}!{sub.get('used_range', '')}"
            )
            documents.append(
                {
                    "kind": "excel_sheet",
                    "id": f"Sheet:{sub_name}",
                    "classification": kind,
                    "source_ref": source_ref,
                    "summary": {
                        "sheet_name": sub_name,
                        "block_title": sub.get("title"),
                        "block_index": sub.get("block_index"),
                        "block_count": sub.get("block_count"),
                        "used_range": sub.get("used_range"),
                        "merged_ranges": sub.get("merged_ranges", []),
                        "hidden_rows": sub.get("hidden_rows", []),
                        "hidden_columns": sub.get("hidden_columns", []),
                        "reason": details.get("reason"),
                        "rate_header_hits": details.get("rate_header_hits"),
                    },
                    "raw_excerpt": sheet_text_preview(sub),
                    "tables": [],
                    "detected_hotel_name": details.get("detected_hotel_name"),
                }
            )

    return {
        "source_file": parsed["source_file"],
        "input_format": parsed["input_format"],
        "documents": documents,
    }


def build_ir_from_pdf(parsed: Dict[str, Any]) -> Dict[str, Any]:
    documents: List[Dict[str, Any]] = []
    for page in parsed.get("pages", []):
        # Re-classify after vision text has been attached so pages with empty
        # pdfplumber output but rich vision_text get correctly identified.
        kind, details = classify_pdf_page(
            {
                **page,
                "text": (page.get("text") or "")
                + ("\n" + page.get("vision_text", "") if page.get("vision_text") else ""),
            }
        )
        source_ref = f"{parsed['source_file']} | Page {page['page_number']}"

        # Merge pdfplumber tables and vision-extracted structured tables.
        merged_tables: List[Dict[str, Any]] = list(page.get("tables", []))
        for i, vt in enumerate(page.get("vision_tables") or [], start=len(merged_tables) + 1):
            merged_tables.append(
                {
                    "index": i,
                    "title": vt.get("title"),
                    "source": "vision",
                    "columns": vt.get("columns"),
                    "rows": vt.get("rows"),
                }
            )

        documents.append(
            {
                "kind": "pdf_page",
                "id": f"Page:{page['page_number']}",
                "classification": kind,
                "source_ref": source_ref,
                "summary": {
                    "page_number": page["page_number"],
                    "needs_vision": page.get("needs_vision"),
                    "vision_used": bool(page.get("vision_text") or page.get("vision_tables")),
                    "vision_tables_count": len(page.get("vision_tables") or []),
                    "vision_reasons": page.get("vision_reasons") or [],
                    "reason": details.get("reason"),
                    "has_tables": details.get("has_tables"),
                },
                "raw_excerpt": page_text_preview(page),
                "tables": merged_tables,
                "detected_hotel_name": None,
            }
        )
    return {
        "source_file": parsed["source_file"],
        "input_format": parsed["input_format"],
        "documents": documents,
    }


def build_ir_from_docx(parsed: Dict[str, Any]) -> Dict[str, Any]:
    text_parts: List[str] = []
    for block in parsed.get("blocks", []):
        prefix = "## " if block["kind"] == "heading" else ""
        text_parts.append(f"{prefix}{block['text']}")
    raw_excerpt = "\n".join(text_parts)

    documents: List[Dict[str, Any]] = [
        {
            "kind": "docx_section",
            "id": "Doc:Body",
            "classification": "hotel_contract",  # default; LLM will sort it out
            "source_ref": f"{parsed['source_file']} | Body",
            "summary": {
                "blocks": len(parsed.get("blocks", [])),
                "tables": len(parsed.get("tables", [])),
                "embedded_images": parsed.get("embedded_images", 0),
            },
            "raw_excerpt": raw_excerpt[:8000],
            "tables": parsed.get("tables", []),
            "detected_hotel_name": None,
        }
    ]
    return {
        "source_file": parsed["source_file"],
        "input_format": parsed["input_format"],
        "documents": documents,
    }


def build_ir_from_image(parsed: Dict[str, Any]) -> Dict[str, Any]:
    documents: List[Dict[str, Any]] = [
        {
            "kind": "image",
            "id": "Image:0",
            "classification": "hotel_contract",
            "source_ref": f"{parsed['source_file']} | full image",
            "summary": {
                "width": parsed.get("width"),
                "height": parsed.get("height"),
                "mode": parsed.get("mode"),
            },
            "raw_excerpt": parsed.get("vision_text") or "",
            "tables": parsed.get("vision_tables") or [],
            "detected_hotel_name": None,
        }
    ]
    return {
        "source_file": parsed["source_file"],
        "input_format": "image",
        "documents": documents,
    }
