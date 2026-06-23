"""Job orchestration — drives a single job through every stage.

For simplicity (and to keep the local-dev experience easy) jobs run
synchronously in a background thread spawned by FastAPI's BackgroundTasks.
Replace with a real queue (rq / celery / arq) for production scale.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import Job, SessionLocal
from .audit import append_event
from .cell_audit import audit_cells
from .completeness import check_completeness
from .direct_vision_extractor import extract_image_directly, extract_pdf_directly
from .exporter import export_workbook
from .file_type import detect_file_kind
from .hotel_enrichment import enrich_result
from .ir_builder import (
    build_ir_from_docx,
    build_ir_from_excel,
    build_ir_from_image,
    build_ir_from_pdf,
)
from .llm_chunker import CHUNK_SIZE_DEFAULT, run_extraction_chunked
from .normalizer import normalize_result
from .parsers.docx import parse_docx
from .parsers.excel import parse_excel
from .parsers.image import attach_vision_text, parse_image
from .parsers.pdf import parse_pdf
from .parsers.pdf_vision import enrich_pdf_with_vision
from .pdf_strategy import choose_strategy
from .structured_excel_extractor import extract_excel_structured
from .supplier_templates import load_template, save_template
from .validator import validate_result

logger = logging.getLogger(__name__)


def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _save_upload(upload_path: Path, original_name: str) -> Path:
    settings = get_settings()
    uploads = settings.storage_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    target = uploads / f"{uuid.uuid4().hex}-{original_name}"
    shutil.copy(upload_path, target)
    return target


def create_job(
    db: Session,
    *,
    original_name: str,
    saved_path: Path,
    options: Dict[str, Any],
) -> Job:
    # Re-read settings each job so env var edits (eg PROMPT_VERSION) are
    # reflected without restarting uvicorn.
    get_settings.cache_clear()
    settings = get_settings()

    # If we have a cached template for this supplier, fold it into options
    # so downstream extractors can use it as a layout hint.
    supplier = options.get("supplierDefault")
    cached = load_template(supplier)
    if cached:
        options = {**options, "supplierTemplate": cached}

    job = Job(
        id=str(uuid.uuid4()),
        status="uploaded",
        progress=0,
        file_name=original_name,
        file_path=str(saved_path),
        file_checksum=file_checksum(saved_path),
        options=options,
        parser_version=settings.parser_version,
        prompt_version=settings.prompt_version,
        extraction_mode=options.get("extractionMode", "auto"),
        warnings=[],
        errors=[],
        sheet_summary=[],
        audit=[],
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    append_event(db, job, event="job.created", detail={"file": original_name})
    return job


def _set_status(db: Session, job: Job, status: str, progress: int) -> None:
    job.status = status
    job.progress = progress
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()


def _summarize_sheets(ir: Dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in ir.get("documents", []):
        out.append(
            {
                "id": doc.get("id"),
                "kind": doc.get("kind"),
                "classification": doc.get("classification"),
                "detectedHotelName": doc.get("detected_hotel_name"),
                "sourceRef": doc.get("source_ref"),
                "summary": doc.get("summary"),
            }
        )
    return out


def run_job_pipeline(job_id: str) -> None:
    """Run the full pipeline for a single job. Intended to be called in a
    background thread or task runner."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("Job %s not found in DB", job_id)
            return
        try:
            _set_status(db, job, "detecting_file_type", 5)
            kind = detect_file_kind(job.file_path)
            job.file_type = kind
            append_event(db, job, event="file_type_detected", detail={"kind": kind})

            _set_status(db, job, "parsing", 15)
            ir: Dict[str, Any]
            extraction_mode = job.options.get("extractionMode", "auto")

            # Format-specific parsing. For PDFs we additionally pick an
            # extraction strategy based on parser diagnostics + user mode.
            pdf_strategy = None
            if kind in ("xlsx", "xls"):
                parsed = parse_excel(job.file_path, kind=kind)
                ir = build_ir_from_excel(parsed)
            elif kind == "pdf":
                parsed = parse_pdf(job.file_path)
                pdf_strategy = choose_strategy(parsed, extraction_mode)
                ir = build_ir_from_pdf(parsed)
                append_event(
                    db,
                    job,
                    event="pdf_strategy_selected",
                    detail={"strategy": pdf_strategy, "mode": extraction_mode},
                )
            elif kind == "docx":
                parsed = parse_docx(job.file_path)
                ir = build_ir_from_docx(parsed)
            elif kind == "image":
                parsed = parse_image(job.file_path)
                ir = build_ir_from_image(parsed)
            else:
                raise RuntimeError(f"Unsupported file kind: {kind}")

            use_direct_vision = (
                kind in ("pdf", "image")
                and extraction_mode != "text_only"
                and bool(get_settings().openai_api_key)
                and (kind != "pdf" or pdf_strategy != "native_text_llm")
            )

            _set_status(db, job, "classifying_sheets_or_pages", 45)
            job.sheet_summary = _summarize_sheets(ir)

            _set_status(db, job, "building_intermediate_representation", 55)
            job.ir = ir

            llm_out: Dict[str, Any]
            if use_direct_vision and kind == "pdf":
                _set_status(db, job, "running_ocr_or_vision", 35)
                # Direct vision: one call per page, parallel, returns rows directly.
                hotel_page_numbers = [
                    p["page_number"]
                    for p in parsed.get("pages", [])
                ]
                append_event(
                    db,
                    job,
                    event="direct_vision_started",
                    detail={
                        "mode": extraction_mode,
                        "pages": hotel_page_numbers,
                        "page_count": len(hotel_page_numbers),
                    },
                )
                _set_status(db, job, "running_llm_extraction", 65)
                llm_out = extract_pdf_directly(
                    job.file_path,
                    pages=hotel_page_numbers,
                    options=job.options or {},
                )
                append_event(
                    db,
                    job,
                    event="direct_vision_done",
                    detail={
                        "pages": llm_out.get("pages") or [],
                        "warnings": llm_out.get("warnings") or [],
                        "errors": llm_out.get("errors") or [],
                    },
                )
            elif use_direct_vision and kind == "image":
                _set_status(db, job, "running_ocr_or_vision", 35)
                append_event(db, job, event="direct_vision_started", detail={"image": True})
                _set_status(db, job, "running_llm_extraction", 65)
                llm_out = extract_image_directly(job.file_path, options=job.options or {})
            elif kind in ("xlsx", "xls") and bool(get_settings().openai_api_key):
                # Excel goes through the deterministic structured extractor:
                # one LLM call per hotel sheet to build a column map, then
                # Python iterates the grid (every date row × every room
                # column). Guarantees full coverage; no LLM laziness.
                _set_status(db, job, "running_llm_extraction", 65)
                append_event(
                    db,
                    job,
                    event="structured_excel_started",
                    detail={"sheet_count": len(parsed.get("sheets") or [])},
                )
                llm_out = extract_excel_structured(parsed, job.options or {})
                append_event(
                    db,
                    job,
                    event="structured_excel_done",
                    detail={
                        "rows": len((llm_out.get("result") or {}).get("hotelRows") or []),
                        "errors": llm_out.get("errors") or [],
                    },
                )
            else:
                _set_status(db, job, "running_llm_extraction", 65)
                llm_out = run_extraction_chunked(
                    ir, job.options or {}, chunk_size=CHUNK_SIZE_DEFAULT
                )
            if llm_out.get("chunks") and len(llm_out["chunks"]) > 1:
                append_event(
                    db,
                    job,
                    event="llm_chunked",
                    detail={
                        "chunk_count": len(llm_out["chunks"]),
                        "chunks": [
                            {
                                "i": c.get("chunk_index"),
                                "docs": c.get("documents") or c.get("sheet") or c.get("blocks"),
                                "errors": c.get("errors") or [],
                            }
                            for c in llm_out["chunks"]
                        ],
                    },
                )
            job.raw_llm_request = llm_out.get("raw_request") or {"mode": "direct_vision"}
            job.raw_llm_response = llm_out.get("raw_response") or ""
            job.openai_model = llm_out.get("model")
            warnings = list(job.warnings or []) + list(llm_out["warnings"])
            errors = list(job.errors or []) + list(llm_out["errors"])
            job.warnings = warnings
            job.errors = errors

            if llm_out["result"] is None:
                _set_status(db, job, "failed", 100)
                append_event(db, job, event="failed", detail={"errors": errors})
                return

            _set_status(db, job, "normalizing", 75)
            normalized = normalize_result(llm_out["result"], job.options or {}, job.file_name)

            # Drop skeleton rows defensively — any row that has neither a
            # Hotel Name nor any numeric rate value gets pulled out and
            # surfaced as an Extraction Note instead.
            from .direct_vision_extractor import _filter_skeleton_rows
            normalized = _filter_skeleton_rows(normalized, source_file=job.file_name)

            # Completeness check: warn when the LLM produced far fewer rows
            # than a detected rate-table grid implies. Notes are appended; the
            # job continues to ready_for_review so reviewers can patch by hand.
            comp_notes, comp_warnings = check_completeness(ir, normalized)
            if comp_notes:
                normalized["extractionNotes"] = list(normalized.get("extractionNotes") or []) + comp_notes
            if comp_warnings:
                job.warnings = list(job.warnings or []) + comp_warnings
                append_event(
                    db,
                    job,
                    event="completeness_warning",
                    detail={"messages": comp_warnings},
                )

            # Defensive cell audit — every numeric source cell must be
            # represented in a row, otherwise surface as an Extraction Note.
            audit = audit_cells(ir, normalized)
            if audit["notes"]:
                normalized["extractionNotes"] = list(
                    normalized.get("extractionNotes") or []
                ) + audit["notes"]
            if audit["warnings"]:
                job.warnings = list(job.warnings or []) + audit["warnings"]
            append_event(
                db,
                job,
                event="cell_audit",
                detail=audit["stats"],
            )

            _set_status(db, job, "validating", 85)
            issues = validate_result(normalized, job.options or {})
            normalized["validationIssues"] = issues

            job.result = normalized
            job.edited_result = None

            _set_status(db, job, "ready_for_review", 95)
            append_event(
                db,
                job,
                event="ready_for_review",
                detail={
                    "hotelRows": len(normalized.get("hotelRows", [])),
                    "extractionNotes": len(normalized.get("extractionNotes", [])),
                    "issues": len(issues),
                },
            )
            _set_status(db, job, "ready_for_review", 100)
        except Exception as e:  # noqa: BLE001
            logger.exception("Pipeline failure for job %s", job_id)
            errors = list(job.errors or []) + [f"{type(e).__name__}: {e}"]
            job.errors = errors
            _set_status(db, job, "failed", 100)
            append_event(db, job, event="failed", detail={"error": str(e)})
    finally:
        db.close()


def get_active_result(job: Job) -> Dict[str, Any] | None:
    if job.edited_result:
        return job.edited_result
    return job.result


def patch_result(db: Session, job: Job, patched_result: Dict[str, Any]) -> Dict[str, Any]:
    """User-edited normalized JSON. Re-run validation."""
    normalized = normalize_result(patched_result, job.options or {}, job.file_name)
    issues = validate_result(normalized, job.options or {})
    normalized["validationIssues"] = issues
    job.edited_result = normalized
    db.add(job)
    db.commit()
    append_event(db, job, event="result_patched", detail={"issues": len(issues)})
    return normalized


def enrich_metadata(db: Session, job: Job, *, force: bool = False) -> Dict[str, Any]:
    """Fill missing hotel address/contact/geo fields via GPT, then revalidate.

    Saves to edited_result without re-normalizing, so the AI-inferred marks
    (warnings + cellMeta) survive. Returns {result, summary}.
    """
    current = get_active_result(job)
    if current is None:
        raise RuntimeError("Job has no result to enrich")
    summary = enrich_result(current, force=force)
    issues = validate_result(current, job.options or {})
    current["validationIssues"] = issues
    job.edited_result = current
    db.add(job)
    db.commit()
    append_event(
        db,
        job,
        event="metadata_enriched",
        detail={
            "hotelsProcessed": summary.get("hotelsProcessed"),
            "fieldsFilled": summary.get("fieldsFilled"),
            "skipped": summary.get("skipped"),
        },
    )
    return {"result": current, "summary": summary}


def revalidate(db: Session, job: Job) -> Dict[str, Any]:
    current = get_active_result(job)
    if current is None:
        raise RuntimeError("Job has no result to validate")
    issues = validate_result(current, job.options or {})
    current["validationIssues"] = issues
    if job.edited_result is not None:
        job.edited_result = current
    else:
        job.result = current
    db.add(job)
    db.commit()
    append_event(db, job, event="revalidated", detail={"issues": len(issues)})
    return current


def export(
    db: Session,
    job: Job,
    *,
    mode: Optional[str] = None,
    include_internal: bool = False,
) -> Path:
    settings = get_settings()
    current = get_active_result(job)
    if current is None:
        raise RuntimeError("Job has no result to export")
    chosen_mode = mode or "moonstride_auto"

    out_dir = settings.storage_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{job.id}-{chosen_mode}.xlsx"

    export_workbook(
        current,
        output_path=out_path,
        mode=chosen_mode,
        include_internal=include_internal,
    )
    job.status = "completed"
    job.export_path = str(out_path)
    db.add(job)
    db.commit()
    append_event(
        db, job, event="exported", detail={"mode": chosen_mode, "path": str(out_path)}
    )

    # Persist a per-supplier template snapshot so future uploads from the
    # same supplier can reuse the layout without re-discovering it.
    supplier = (job.options or {}).get("supplierDefault")
    if not supplier:
        for r in (current.get("hotelRows") or [])[:1]:
            supplier = r.get("Supplier")
    if supplier:
        saved = save_template(supplier, current)
        if saved:
            append_event(
                db, job, event="supplier_template_saved",
                detail={"supplier": supplier, "path": str(saved)},
            )

    return out_path


def spawn_pipeline(job_id: str) -> None:
    threading.Thread(target=run_job_pipeline, args=(job_id,), daemon=True).start()
