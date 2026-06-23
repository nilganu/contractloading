"""Canonical extraction call.

Uploads the contract file once to the OpenAI Files API and invokes
``client.responses.parse(text_format=ContractExtraction)``. OpenAI's
strict ``json_schema`` mode enforces our Pydantic model exactly —
column names, enum values, and required fields cannot drift.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..config import get_settings
from .canonical import ContractExtraction

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "extraction"
    / "contract-extraction-v1.txt"
)

# OpenAI's Responses API accepts these file types via ``input_file``.
_FILE_MIME: Dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".odt": "application/vnd.oasis.opendocument.text",
    ".rtf": "application/rtf",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}

_IMAGE_MIME: Dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

SUPPORTED_EXTENSIONS = sorted(set(_FILE_MIME) | set(_IMAGE_MIME))
MAX_BYTES = 50 * 1024 * 1024


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _upload(client, file_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Upload file to OpenAI; return (file_id, content_block)."""
    ext = file_path.suffix.lower()
    if file_path.stat().st_size > MAX_BYTES:
        raise ValueError(
            f"File is {file_path.stat().st_size / 1024 / 1024:.1f} MB. "
            f"OpenAI accepts up to {MAX_BYTES // 1024 // 1024} MB per file."
        )
    if ext not in _FILE_MIME and ext not in _IMAGE_MIME:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Supported: "
            + ", ".join(SUPPORTED_EXTENSIONS)
        )

    is_image = ext in _IMAGE_MIME
    purpose = "vision" if is_image else "user_data"
    with file_path.open("rb") as fh:
        uploaded = client.files.create(file=fh, purpose=purpose)

    if is_image:
        block: Dict[str, Any] = {"type": "input_image", "file_id": uploaded.id}
    else:
        block = {"type": "input_file", "file_id": uploaded.id}
    return uploaded.id, block


def _make_openai_client():
    """One OpenAI client; reused across outline + per-hotel passes."""
    from openai import OpenAI

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    return OpenAI(
        api_key=settings.openai_api_key, timeout=600.0, max_retries=0
    )


def _build_user_directive(
    file_name: str,
    options: Optional[Dict[str, Any]],
    hotel_focus: Optional[str] = None,
    retry_directive: Optional[str] = None,
) -> str:
    opts = options or {}
    base = (
        f"Source filename: {file_name}. "
        f"Supplier hint: {opts.get('supplierDefault') or 'unknown'}. "
        f"Country hint: {opts.get('countryDefault') or 'unknown'}. "
        f"Currency hint: {opts.get('currencyDefault') or 'unknown'}. "
    )
    if hotel_focus:
        base += (
            f"Focus ONLY on hotel '{hotel_focus}' — this sub-file contains "
            f"just that hotel's contract data. "
        )
    if retry_directive:
        base += retry_directive + " "
    base += "Return the JSON object matching the enforced schema."
    return base


def parse_extraction_with_file(
    client,
    file_block: Dict[str, Any],
    *,
    file_name: str,
    options: Optional[Dict[str, Any]] = None,
    hotel_focus: Optional[str] = None,
    retry_directive: Optional[str] = None,
) -> ContractExtraction:
    """One ``responses.parse`` call given an already-uploaded file_block.

    The orchestrator calls this once per hotel against per-hotel sub-files;
    the upload and delete are managed outside so this function is purely
    "given a file_id, return the canonical extraction".
    """
    settings = get_settings()
    system_prompt = _load_prompt()
    response = client.responses.parse(
        model=settings.openai_model_mini,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    file_block,
                    {
                        "type": "input_text",
                        "text": _build_user_directive(
                            file_name, options, hotel_focus, retry_directive
                        ),
                    },
                ],
            },
        ],
        text_format=ContractExtraction,
    )
    parsed: Optional[ContractExtraction] = response.output_parsed
    if parsed is None:
        raise RuntimeError(
            "Model did not return a parseable ContractExtraction. "
            f"Raw output (first 300 chars): {(response.output_text or '')[:300]!r}"
        )
    parsed.source_filename = file_name
    return parsed


def extract_contract(
    file_path: str | Path,
    *,
    options: Optional[Dict[str, Any]] = None,
) -> ContractExtraction:
    """Single-shot extraction: upload, parse, delete. Kept for the
    single-hotel fast path and as a fallback when the orchestrator
    decides not to decompose."""
    file_path = Path(file_path)
    client = _make_openai_client()
    logger.info(
        "canonical extraction: model=%s file=%s size=%dB",
        get_settings().openai_model_mini,
        file_path.name,
        file_path.stat().st_size,
    )
    file_id, file_block = _upload(client, file_path)
    logger.info("uploaded to OpenAI: file_id=%s", file_id)
    try:
        return parse_extraction_with_file(
            client, file_block, file_name=file_path.name, options=options
        )
    finally:
        try:
            client.files.delete(file_id)
        except Exception:  # noqa: BLE001
            logger.warning("could not delete uploaded file %s", file_id)


# Re-exported so the orchestrator can drive the upload/delete itself
# (one upload per per-hotel sub-file).
upload_file = _upload
