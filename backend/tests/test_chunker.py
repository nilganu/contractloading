"""Chunker tests — verify split / merge behaviour for long IRs."""
from __future__ import annotations

from app.services.llm_chunker import (
    CHUNK_SIZE_DEFAULT,
    merge_chunk_results,
    split_ir_into_chunks,
)


def _make_doc(doc_id: str, classification: str) -> dict:
    return {
        "id": doc_id,
        "kind": "pdf_page",
        "classification": classification,
        "source_ref": f"file.pdf | {doc_id}",
        "summary": {},
        "raw_excerpt": "",
        "tables": [],
        "detected_hotel_name": None,
    }


def test_split_small_ir_returns_single_chunk() -> None:
    """When chunk_size >= number of hotel docs, the IR is returned as a
    single chunk."""
    ir = {
        "source_file": "x.pdf",
        "input_format": "pdf",
        "documents": [
            _make_doc("Page:1", "hotel_contract"),
            _make_doc("Page:2", "hotel_contract"),
        ],
    }
    # Use an explicit chunk_size larger than the doc count so the test
    # remains stable as the DEFAULT shrinks.
    chunks = split_ir_into_chunks(ir, chunk_size=4)
    assert len(chunks) == 1
    assert chunks[0] is ir


def test_split_large_ir_chunks_by_hotel_pages_and_keeps_context() -> None:
    hotel_docs = [_make_doc(f"Page:{i}", "hotel_contract") for i in range(1, 15)]
    ctx = [_make_doc("Page:Index", "index_reference")]
    ir = {
        "source_file": "long.pdf",
        "input_format": "pdf",
        "documents": ctx + hotel_docs,
    }
    chunks = split_ir_into_chunks(ir, chunk_size=6)
    # 14 hotel docs / 6 per chunk -> 3 chunks
    assert len(chunks) == 3
    # Every chunk includes the index_reference document for cross-hotel context
    for c in chunks:
        ids = [d["id"] for d in c["documents"]]
        assert "Page:Index" in ids
    # Hotel pages are split across chunks, not duplicated
    hotel_ids_per_chunk = [
        [d["id"] for d in c["documents"] if d["classification"] == "hotel_contract"]
        for c in chunks
    ]
    flat = [i for sub in hotel_ids_per_chunk for i in sub]
    assert len(flat) == 14  # no duplicates
    assert len(set(flat)) == 14


def test_merge_concatenates_rows_and_unions_dynamic_columns() -> None:
    chunk_a = {
        "workbookSummary": {
            "sourceFile": "x.pdf",
            "inputFormat": "pdf",
            "sheetsOrPagesProcessed": ["Page:1"],
            "indexSheets": [],
            "hotelSheets": ["Page:1"],
            "ignoredSheetsOrPages": [],
            "overallConfidence": 0.6,
        },
        "dynamicColumns": {
            "childColumns": [
                {"key": "CHD(0-2)", "label": "CHD(0-2)", "ageFrom": 0, "ageTo": 2, "ageLabel": None, "childPosition": None, "valueType": "amount"},
            ]
        },
        "hotels": [
            {"hotelName": "Acrotel", "rateBlocks": [{"title": "BB"}], "roomTypes": [], "childPolicies": []}
        ],
        "hotelRows": [{"id": "r1", "Hotel Name": "Acrotel", "Start Date": "2026-04-01", "End Date": "2026-06-13"}],
        "extractionNotes": [{"Source File": "x.pdf", "Page": "Page:1", "Category": "Other", "Note": "same"}],
        "validationIssues": [],
    }
    chunk_b = {
        "workbookSummary": {
            "sourceFile": "x.pdf",
            "inputFormat": "pdf",
            "sheetsOrPagesProcessed": ["Page:2"],
            "indexSheets": [],
            "hotelSheets": ["Page:2"],
            "ignoredSheetsOrPages": [],
            "overallConfidence": 0.4,
        },
        "dynamicColumns": {
            "childColumns": [
                {"key": "CHD(2-11.99)", "label": "CHD(2-11.99)", "ageFrom": 2, "ageTo": 11.99, "ageLabel": None, "childPosition": None, "valueType": "amount"},
            ]
        },
        "hotels": [
            {"hotelName": "Acrotel", "rateBlocks": [{"title": "HB"}], "roomTypes": [], "childPolicies": []},
        ],
        "hotelRows": [{"id": "r2", "Hotel Name": "Acrotel", "Start Date": "2026-06-14", "End Date": "2026-08-31"}],
        "extractionNotes": [
            {"Source File": "x.pdf", "Page": "Page:1", "Category": "Other", "Note": "same"},  # duplicate
            {"Source File": "x.pdf", "Page": "Page:2", "Category": "Cancellation", "Note": "rules"},
        ],
        "validationIssues": [],
    }
    merged = merge_chunk_results([chunk_a, chunk_b], source_file="x.pdf")

    assert {c["key"] for c in merged["dynamicColumns"]["childColumns"]} == {"CHD(0-2)", "CHD(2-11.99)"}
    assert [r["id"] for r in merged["hotelRows"]] == ["r1", "r2"]
    # Hotel grouped by name; rate blocks concatenated
    assert len(merged["hotels"]) == 1
    assert [b["title"] for b in merged["hotels"][0]["rateBlocks"]] == ["BB", "HB"]
    # Duplicate note deduped, new note kept
    assert len(merged["extractionNotes"]) == 2
    assert merged["workbookSummary"]["sheetsOrPagesProcessed"] == ["Page:1", "Page:2"]
    # Average confidence
    assert merged["workbookSummary"]["overallConfidence"] == 0.5
