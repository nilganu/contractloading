"""Chunked LLM extraction for large IRs.

For long contracts (many sheets or many PDF pages) a single LLM call risks
hitting context or output-token limits and silently truncating rate rows.
This module splits the IR into chunks that the LLM handles independently and
merges the results back together.

Chunking rules:
- hotel_contract documents are split into chunks of `chunk_size` (default 6).
- index_reference + support_notes documents are duplicated into every chunk
  so the model always has the cross-hotel context (eg the Hotel List sheet)
  when interpreting the hotel pages.
- A small IR (<= chunk_size hotel docs) skips chunking entirely.

Merge rules:
- workbookSummary: union sheetsOrPagesProcessed/indexSheets/hotelSheets,
  union ignoredSheetsOrPages, average overallConfidence.
- dynamicColumns.childColumns: union by key, keep first occurrence.
- hotels: group by hotelName, concatenate rateBlocks and childPolicies.
- hotelRows: concatenate (each row id is already unique).
- extractionNotes: concatenate, deduped by (Source File, Page, Category, Note).
- validationIssues: concatenate.

Failure isolation: a chunk that returns no result raises a warning and an
extraction note rather than aborting the whole job. The merged result is
always returned.
"""
from __future__ import annotations

import copy
import json
import uuid
from typing import Any, Dict, List

from .llm_extractor import run_extraction


CHUNK_SIZE_DEFAULT = 1


def _classify(doc: Dict[str, Any]) -> str:
    return (doc.get("classification") or "unknown")


def split_ir_into_chunks(ir: Dict[str, Any], *, chunk_size: int = CHUNK_SIZE_DEFAULT) -> List[Dict[str, Any]]:
    docs = ir.get("documents") or []
    hotel_docs = [d for d in docs if _classify(d) == "hotel_contract"]
    context_docs = [d for d in docs if _classify(d) in ("index_reference", "support_notes")]
    other_docs = [d for d in docs if _classify(d) not in ("hotel_contract", "index_reference", "support_notes")]

    # If small enough, return as one chunk.
    if len(hotel_docs) <= chunk_size:
        return [ir]

    chunks: List[Dict[str, Any]] = []
    for i in range(0, len(hotel_docs), chunk_size):
        slice_ = hotel_docs[i : i + chunk_size]
        chunk_ir = {
            "source_file": ir.get("source_file"),
            "input_format": ir.get("input_format"),
            "documents": list(context_docs) + list(slice_) + list(other_docs if i == 0 else []),
            "_chunk_index": len(chunks),
        }
        chunks.append(chunk_ir)
    return chunks


def _union_list(*lists: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen: set[Any] = set()
    for lst in lists:
        for item in lst or []:
            key = json.dumps(item, sort_keys=True, default=str) if not isinstance(item, str) else item
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def _merge_dynamic_columns(parts: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for part in parts:
        for col in part or []:
            key = col.get("key") or col.get("label")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(col)
    return out


def _merge_hotels(parts: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for part in parts:
        for h in part or []:
            name = h.get("hotelName") or h.get("name") or "Unknown Hotel"
            if name not in grouped:
                grouped[name] = copy.deepcopy(h)
                order.append(name)
            else:
                tgt = grouped[name]
                tgt.setdefault("rateBlocks", []).extend(h.get("rateBlocks") or [])
                tgt.setdefault("roomTypes", []).extend(h.get("roomTypes") or [])
                tgt.setdefault("childPolicies", []).extend(h.get("childPolicies") or [])
                # keep first metadata, but fill in missing fields from later chunks
                meta = tgt.get("metadata") or {}
                for k, v in (h.get("metadata") or {}).items():
                    if meta.get(k) in (None, "") and v not in (None, ""):
                        meta[k] = v
                tgt["metadata"] = meta
    return [grouped[n] for n in order]


def _merge_notes(parts: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    seen: set[tuple] = set()
    out: List[Dict[str, Any]] = []
    for part in parts:
        for note in part or []:
            key = (
                note.get("Source File", ""),
                note.get("Page", ""),
                note.get("Category", ""),
                (note.get("Note") or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(note)
    return out


def _merge_workbook_summary(parts: List[Dict[str, Any]], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not parts:
        return fallback
    merged = {
        "sourceFile": parts[0].get("sourceFile") or fallback.get("sourceFile"),
        "inputFormat": parts[0].get("inputFormat") or fallback.get("inputFormat"),
        "sheetsOrPagesProcessed": _union_list(*(p.get("sheetsOrPagesProcessed") or [] for p in parts)),
        "indexSheets": _union_list(*(p.get("indexSheets") or [] for p in parts)),
        "hotelSheets": _union_list(*(p.get("hotelSheets") or [] for p in parts)),
        "ignoredSheetsOrPages": _union_list(*(p.get("ignoredSheetsOrPages") or [] for p in parts)),
    }
    confs = [p.get("overallConfidence") for p in parts if isinstance(p.get("overallConfidence"), (int, float))]
    merged["overallConfidence"] = round(sum(confs) / len(confs), 3) if confs else 0.5
    return merged


def merge_chunk_results(chunk_results: List[Dict[str, Any]], *, source_file: str) -> Dict[str, Any]:
    """Merge several NormalizedExtractionResult-shaped dicts into one."""
    valid = [r for r in chunk_results if r]

    merged_summary = _merge_workbook_summary(
        [r.get("workbookSummary", {}) for r in valid],
        {"sourceFile": source_file, "inputFormat": "unknown"},
    )

    dyn_parts = [(r.get("dynamicColumns") or {}).get("childColumns") or [] for r in valid]
    merged_dynamic = {"childColumns": _merge_dynamic_columns(dyn_parts)}

    merged_hotels = _merge_hotels([r.get("hotels") or [] for r in valid])

    merged_rows: List[Dict[str, Any]] = []
    for r in valid:
        merged_rows.extend(r.get("hotelRows") or [])

    merged_notes = _merge_notes([r.get("extractionNotes") or [] for r in valid])

    merged_issues: List[Dict[str, Any]] = []
    for r in valid:
        merged_issues.extend(r.get("validationIssues") or [])

    return {
        "workbookSummary": merged_summary,
        "dynamicColumns": merged_dynamic,
        "hotels": merged_hotels,
        "hotelRows": merged_rows,
        "extractionNotes": merged_notes,
        "validationIssues": merged_issues,
    }


_CHUNK_MAX_WORKERS = 6


def run_extraction_chunked(
    ir: Dict[str, Any],
    options: Dict[str, Any],
    *,
    chunk_size: int = CHUNK_SIZE_DEFAULT,
    max_workers: int = _CHUNK_MAX_WORKERS,
    progress_cb=None,
) -> Dict[str, Any]:
    """Run the LLM extraction stage with automatic chunking + parallel calls.

    Up to `max_workers` chunks are processed concurrently (each chunk is
    one OpenAI call). For a 91-chunk Excel workbook that drops wall-clock
    from ~15 min to ~2 min.

    Returns the same shape as `run_extraction` plus a list of per-chunk
    diagnostics in `chunks`.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    chunks = split_ir_into_chunks(ir, chunk_size=chunk_size)
    if len(chunks) == 1:
        out = run_extraction(ir, options)
        out["chunks"] = [{"chunk_index": 0, "errors": out["errors"], "model": out["model"]}]
        return out

    raw_responses: List[Optional[str]] = [None] * len(chunks)
    raw_requests: List[Optional[Dict[str, Any]]] = [None] * len(chunks)
    warnings: List[str] = []
    errors: List[str] = []
    chunk_results: List[Optional[Dict[str, Any]]] = [None] * len(chunks)
    chunk_diagnostics: List[Optional[Dict[str, Any]]] = [None] * len(chunks)
    model_used = "unknown"
    usage_total: Dict[str, int] = {}
    done_count = 0

    def _process(idx: int, chunk: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        return idx, run_extraction(chunk, options)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_process, i, c): i for i, c in enumerate(chunks)}
        for fut in as_completed(futures):
            idx, out = fut.result()
            done_count += 1
            if progress_cb:
                try:
                    progress_cb(done_count, len(chunks))
                except Exception:  # noqa: BLE001
                    pass
            raw_requests[idx] = {"chunk_index": idx, "request": out.get("raw_request")}
            raw_responses[idx] = f"=== chunk {idx} ===\n{out.get('raw_response', '')}"
            warnings.extend(out.get("warnings") or [])
            chunk_diagnostics[idx] = {
                "chunk_index": idx,
                "documents": [d.get("id") for d in chunks[idx].get("documents") or []],
                "errors": out.get("errors") or [],
                "model": out.get("model"),
                "usage": out.get("usage") or {},
            }
            if out.get("model"):
                model_used = out["model"]
            for k, v in (out.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    usage_total[k] = usage_total.get(k, 0) + v
            if out.get("result"):
                chunk_results[idx] = out["result"]
            else:
                errors.extend(out.get("errors") or [])
                warnings.append(f"Chunk {idx} produced no result — see audit log.")

    # Compact preserved-order lists for downstream consumers.
    raw_responses_compact = [r for r in raw_responses if r is not None]
    raw_requests_compact = [r for r in raw_requests if r is not None]
    chunk_diagnostics_compact = [d for d in chunk_diagnostics if d is not None]
    chunk_results_compact = [r for r in chunk_results if r is not None]

    merged = merge_chunk_results(
        chunk_results_compact, source_file=ir.get("source_file", "unknown")
    )

    # If some chunks failed, add an extraction note so reviewers see it.
    failed = [d for d in chunk_diagnostics_compact if d.get("errors")]
    if failed:
        merged.setdefault("extractionNotes", []).append(
            {
                "id": f"note_{uuid.uuid4().hex[:8]}",
                "Source File": ir.get("source_file", "unknown"),
                "Page": "—",
                "Category": "Source ambiguity",
                "Note": (
                    f"{len(failed)} extraction chunk(s) failed: "
                    + "; ".join(f"chunk {d['chunk_index']}: {d['errors']}" for d in failed)
                ),
                "_sourceRefs": [],
                "_confidence": 0.2,
                "hotelName": None,
                "linkedHotelRowId": None,
            }
        )

    return {
        "result": merged,
        "raw_request": {"chunked": True, "chunks": raw_requests_compact},
        "raw_response": "\n\n".join(raw_responses_compact),
        "model": model_used,
        "usage": usage_total,
        "warnings": warnings,
        "errors": errors,
        "chunks": chunk_diagnostics_compact,
    }
