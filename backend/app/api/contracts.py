"""HTTP routes for contract extraction."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import Job, get_session
from ..schemas.models import (
    EXTRACTION_NOTES_HEADERS,
    FIXED_BASE_HEADERS,
    FIXED_SUPP_HEADERS,
    STRICT_TEMPLATE_CHILD_COLUMNS,
)
from ..extraction.moonstride_mapper import map_extraction
from ..extraction.orchestrator import orchestrate_extraction
from ..services import jobs as job_service
from ..services.moonstride_templates import TEMPLATES as MOONSTRIDE_TEMPLATES
from ..services.moonstride_templates import preview_moonstride, write_raw_rows
from ..services.parsers.excel import cell_at, parse_excel
from ..services.supplement_template import write_supplement_rows

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.post("/extract-and-export")
async def extract_and_export(
    file: UploadFile = File(...),
) -> FileResponse:
    """End-to-end: upload contract -> GPT canonical extraction with strict
    json_schema -> deterministic mapping -> two Moonstride Excel files
    (hotel + supplements) bundled into a single ZIP.

    The LLM never writes Moonstride column names directly; that mapping —
    including Days="1234567", Standard/Count/Index blanking, forced Yes
    fields, and DD-MM-YYYY date formatting — lives in
    ``extraction.moonstride_mapper`` and is 100% testable in isolation.
    """
    import uuid as _uuid
    import zipfile as _zipfile

    suffix = Path(file.filename or "contract").suffix or ".bin"
    settings = get_settings()
    in_dir = settings.storage_path / "uploads"
    in_dir.mkdir(parents=True, exist_ok=True)
    tmp_in = in_dir / f"in-{_uuid.uuid4().hex[:8]}{suffix}"
    tmp_in.write_bytes(await file.read())

    stem = Path(file.filename or "contract").stem
    out_dir = settings.storage_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = _uuid.uuid4().hex[:8]
    hotel_path = out_dir / f"{stem}-moonstride-{run_id}.xlsx"
    supp_path = out_dir / f"{stem}-supplements-{run_id}.xlsx"
    zip_path = out_dir / f"{stem}-bundle-{run_id}.zip"

    try:
        # 1. Canonical extraction. The orchestrator decides single-shot vs
        # multi-hotel decomposition; multi-hotel files get one focused
        # sub-file extraction per hotel, in parallel.
        try:
            extraction = orchestrate_extraction(tmp_in, options={})
        except ValueError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(500, f"Extraction failed: {e}")
        except Exception as e:  # noqa: BLE001 - surface OpenAI/network errors
            # OpenAI raises RateLimitError / AuthenticationError / APIError —
            # none subclass RuntimeError, so without this catch FastAPI hides
            # them behind a generic 500. Surface the real reason instead.
            msg = f"{type(e).__name__}: {e}"
            if "insufficient_quota" in msg or "RateLimitError" in msg:
                raise HTTPException(
                    402,
                    "OpenAI quota exhausted — top up at https://platform.openai.com/account/billing.",
                )
            if "AuthenticationError" in msg or "Incorrect API key" in msg:
                raise HTTPException(
                    401, "OpenAI API key rejected — check backend/.env."
                )
            raise HTTPException(500, f"Extraction failed: {msg}")

        if not extraction.hotels:
            raise HTTPException(
                502, "Model returned no hotels in the canonical extraction."
            )

        # 2. Deterministic mapping -> Moonstride rows.
        mapped = map_extraction(extraction)

        # 3. Hotel xlsx (existing pass-through writer).
        write_raw_rows(mapped.hotel_rows, mapped.template_id, hotel_path)

        # 4. Supplement xlsx — always written, even when no supplements;
        # header-only output distinguishes "no supplements" from "failed".
        write_supplement_rows(mapped.supplement_rows, supp_path)

        # 5. Bundle into a ZIP. Inner filenames are deterministic (no uuid).
        with _zipfile.ZipFile(
            zip_path, mode="w", compression=_zipfile.ZIP_DEFLATED
        ) as zf:
            zf.write(hotel_path, arcname=f"{stem}-moonstride.xlsx")
            zf.write(supp_path, arcname=f"{stem}-supplements.xlsx")

        return FileResponse(
            zip_path,
            filename=f"{stem}-moonstride-bundle.zip",
            media_type="application/zip",
        )
    finally:
        # Clean up temp upload + intermediates (FileResponse already
        # streams the ZIP before this block runs).
        for p in (tmp_in, hotel_path, supp_path):
            try:
                p.unlink()
            except OSError:
                pass


@router.post("/upload")
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    supplierDefault: Optional[str] = Form(None),
    countryDefault: Optional[str] = Form(None),
    cityAreaDefault: Optional[str] = Form(None),
    currencyDefault: Optional[str] = Form(None),
    statusDefault: Optional[str] = Form(None),
    checkInDefault: Optional[str] = Form(None),
    checkOutDefault: Optional[str] = Form(None),
    childColumnMode: Optional[str] = Form(None),
    preserveChildPositions: Optional[bool] = Form(None),
    extractionMode: Optional[str] = Form(None),
    db: Session = Depends(get_session),
) -> Dict[str, Any]:
    settings = get_settings()
    if file.filename is None:
        raise HTTPException(400, "Filename required")

    # save upload to a temp file first, then to storage
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    saved = job_service._save_upload(tmp_path, file.filename)
    try:
        tmp_path.unlink()
    except OSError:
        pass

    options: Dict[str, Any] = {
        "supplierDefault": supplierDefault,
        "countryDefault": countryDefault,
        "cityAreaDefault": cityAreaDefault,
        "currencyDefault": currencyDefault,
        "statusDefault": statusDefault,
        "checkInDefault": checkInDefault,
        "checkOutDefault": checkOutDefault,
        "childColumnMode": childColumnMode or settings.child_column_mode,
        "preserveChildPositions": (
            preserveChildPositions if preserveChildPositions is not None else settings.preserve_child_positions
        ),
        "extractionMode": extractionMode or "auto",
    }

    job = job_service.create_job(
        db,
        original_name=file.filename,
        saved_path=saved,
        options=options,
    )
    background.add_task(job_service.run_job_pipeline, job.id)
    return job.public_status()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_session)) -> Dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.public_status()


@router.get("/jobs/{job_id}/result")
def get_result(job_id: str, db: Session = Depends(get_session)) -> Dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    result = job_service.get_active_result(job)
    if result is None:
        raise HTTPException(409, f"Job is not ready (status={job.status})")
    return {
        "jobId": job.id,
        "status": job.status,
        "options": job.options,
        "result": result,
    }


class PatchPayload(BaseModel):
    result: Dict[str, Any]


@router.patch("/jobs/{job_id}/result")
def patch_result(
    job_id: str, payload: PatchPayload, db: Session = Depends(get_session)
) -> Dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    updated = job_service.patch_result(db, job, payload.result)
    return {"jobId": job.id, "result": updated}


@router.post("/jobs/{job_id}/validate")
def revalidate(job_id: str, db: Session = Depends(get_session)) -> Dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    updated = job_service.revalidate(db, job)
    return {"jobId": job.id, "result": updated}


@router.post("/jobs/{job_id}/enrich-metadata")
def enrich_metadata(
    job_id: str,
    force: bool = False,
    db: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Fill missing hotel address/contact/geo fields using GPT.

    Only empty fields are filled; values are flagged AI-inferred for review.
    ``force`` re-queries even fields that already have values.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    out = job_service.enrich_metadata(db, job, force=force)
    return {"jobId": job.id, "result": out["result"], "summary": out["summary"]}


@router.get("/jobs/{job_id}/export.xlsx")
def export_xlsx(
    job_id: str,
    mode: Optional[str] = None,
    include_internal: bool = False,
    db: Session = Depends(get_session),
) -> FileResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    blocking = [
        i
        for i in (job_service.get_active_result(job) or {}).get("validationIssues", [])
        if i.get("severity") == "error"
    ]
    if blocking:
        raise HTTPException(
            422,
            detail={
                "message": "Cannot export: blocking validation errors exist",
                "errors": blocking,
            },
        )
    path = job_service.export(db, job, mode=mode, include_internal=include_internal)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/jobs/{job_id}/export-preview")
def export_preview(
    job_id: str,
    mode: Optional[str] = None,
    db: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Return the exact Moonstride export table as JSON (headers + rows).

    Lets the UI verify what the generated Excel will contain before exporting.
    ``mode`` selects a specific template; omitted or "moonstride_auto"
    auto-detects from the contract's Rate Type.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    result = job_service.get_active_result(job)
    if result is None:
        raise HTTPException(400, "Job has no result to preview")
    template_id = mode if mode in MOONSTRIDE_TEMPLATES else None
    return preview_moonstride(result, template_id)


@router.get("/jobs/{job_id}/source/{source_ref:path}")
def get_source(
    job_id: str, source_ref: str, db: Session = Depends(get_session)
) -> Dict[str, Any]:
    """Best-effort source preview.

    The source_ref format depends on the input format. For Excel:
        Workbook.xlsx | SheetName!A1:S35
    We resolve sheet + range and return a tabular snippet.
    For PDF/DOCX/image we return the previously-computed raw_excerpt.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    ir = job.ir or {}
    documents = ir.get("documents", []) if isinstance(ir, dict) else []

    for doc in documents:
        if doc.get("source_ref") == source_ref or doc.get("id") == source_ref:
            return {
                "sourceRef": source_ref,
                "kind": doc.get("kind"),
                "classification": doc.get("classification"),
                "summary": doc.get("summary"),
                "rawExcerpt": doc.get("raw_excerpt"),
                "tables": doc.get("tables") or [],
            }

    # Excel detailed snippet
    if "|" in source_ref and "!" in source_ref:
        try:
            _, after = source_ref.split("|", 1)
            sheet_name, _range = after.strip().split("!", 1)
            sheet_name = sheet_name.strip()
            parsed = parse_excel(job.file_path, kind=job.file_type or "xlsx")
            sheet = next((s for s in parsed["sheets"] if s["name"] == sheet_name), None)
            if sheet is None:
                raise HTTPException(404, f"Sheet not found: {sheet_name}")
            return {
                "sourceRef": source_ref,
                "kind": "excel_sheet",
                "summary": {
                    "sheet_name": sheet_name,
                    "used_range": sheet.get("used_range"),
                },
                "rawExcerpt": "",
                "rows": sheet.get("rows", [])[:60],
            }
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"Failed to load source: {e}")

    # PDF / page-range refs (eg "file.pdf | Pages 1-2" or "... | Page 4").
    # The row's source ref may span several pages or use plural wording that
    # doesn't exactly match the per-page IR documents — match by page number.
    if "|" in source_ref:
        tail = source_ref.split("|", 1)[1]
        page_nums = {int(n) for n in re.findall(r"\d+", tail)}
        pdf_pages = [d for d in documents if d.get("kind") == "pdf_page"]

        def _pn(doc: Dict[str, Any]) -> Optional[int]:
            pn = (doc.get("summary") or {}).get("page_number")
            return pn if isinstance(pn, int) else None

        matched = [d for d in pdf_pages if _pn(d) in page_nums]
        if not matched and page_nums:
            lo, hi = min(page_nums), max(page_nums)
            matched = [d for d in pdf_pages if _pn(d) is not None and lo <= _pn(d) <= hi]
        if matched:
            return {
                "sourceRef": source_ref,
                "kind": "pdf_pages",
                "summary": {"pages": sorted(p for p in (_pn(d) for d in matched) if p is not None)},
                "rawExcerpt": "\n\n".join((d.get("raw_excerpt") or "") for d in matched),
                "tables": [t for d in matched for t in (d.get("tables") or [])],
            }

    # Last resort: show the closest available source text rather than 404 —
    # a preview pane is more useful with approximate content than an error.
    if documents:
        joined = "\n\n".join(
            f"[{d.get('id') or d.get('source_ref') or 'doc'}]\n{(d.get('raw_excerpt') or '')}"
            for d in documents
        ).strip()
        if joined:
            return {
                "sourceRef": source_ref,
                "kind": "approximate",
                "summary": {"note": "Exact source span not found — showing closest available text."},
                "rawExcerpt": joined[:8000],
                "tables": [],
            }

    raise HTTPException(404, f"Source reference not found: {source_ref}")


@router.get("/jobs/{job_id}/file")
def get_file(job_id: str, db: Session = Depends(get_session)) -> FileResponse:
    """Serve the original uploaded contract file inline, so the review UI can
    render it (PDF viewer / image) next to the extracted data."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if not job.file_path:
        raise HTTPException(404, "No source file for this job")
    path = Path(job.file_path)
    if not path.exists():
        raise HTTPException(404, "Source file no longer available")
    media = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media,
        filename=job.file_name or path.name,
        content_disposition_type="inline",
    )


@router.get("/jobs/{job_id}/audit")
def get_audit(job_id: str, db: Session = Depends(get_session)) -> Dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {
        "jobId": job.id,
        "fileName": job.file_name,
        "fileType": job.file_type,
        "parserVersion": job.parser_version,
        "promptVersion": job.prompt_version,
        "openaiModel": job.openai_model,
        "extractionMode": job.extraction_mode,
        "audit": job.audit or [],
        "warnings": job.warnings or [],
        "errors": job.errors or [],
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat(),
        "exportPath": job.export_path,
    }


@router.get("/template")
def template_metadata() -> Dict[str, Any]:
    """Expose the strict template column metadata so the UI can render
    header references and the export-mode selector without duplicating
    the contract."""
    return {
        "fixedBaseHeaders": FIXED_BASE_HEADERS,
        "fixedSupplementHeaders": FIXED_SUPP_HEADERS,
        "strictTemplateChildColumns": STRICT_TEMPLATE_CHILD_COLUMNS,
        "extractionNotesHeaders": EXTRACTION_NOTES_HEADERS,
    }
