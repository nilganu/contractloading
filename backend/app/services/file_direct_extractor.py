"""Send the entire contract file to GPT — no rasterisation, no per-page
batching, no pdfplumber.

The file is uploaded once to OpenAI's Files API (``client.files.create``)
and the extraction call references it by ``file_id``. PDFs, Office docs,
spreadsheets, text formats, and images are all supported. The model
returns the same structured JSON our pipeline already understands, so the
result drops into ``normalize_result`` unchanged.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import get_settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "file-direct-moonstride-v1.txt"
)

# Extensions OpenAI's Responses API accepts via ``input_file`` -> MIME type.
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

# Images go through ``input_image`` instead.
_IMAGE_MIME: Dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

SUPPORTED_EXTENSIONS = sorted(set(_FILE_MIME) | set(_IMAGE_MIME))

# OpenAI per-file cap for the Responses input_file block.
MAX_BYTES = 50 * 1024 * 1024


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _upload_file(client, file_path: Path) -> tuple[str, Dict[str, Any]]:
    """Upload the file to OpenAI and return (file_id, content_block).

    The content block references the uploaded file by ``file_id`` for the
    Responses API. Images go in ``input_image``, everything else in
    ``input_file``.
    """
    ext = file_path.suffix.lower()
    size = file_path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(
            f"File is {size / 1024 / 1024:.1f} MB. OpenAI accepts up to "
            f"{MAX_BYTES // 1024 // 1024} MB per file."
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


def extract_file_direct(
    file_path: str | Path,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a single Responses-API call with the whole file attached.

    Returns a dict shaped like the rest of our pipeline expects (hotels,
    hotelRows, dynamicChildColumns, extractionNotes, ...). Raises on
    configuration / API / parse errors.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    file_path = Path(file_path)
    system_prompt = _load_prompt()
    opts = options or {}
    defaults_line = (
        f"Supplier default: {opts.get('supplierDefault') or 'unknown'}. "
        f"Country code default: {opts.get('countryDefault') or 'unknown'}. "
        f"City default: {opts.get('cityAreaDefault') or 'unknown'}. "
        f"Currency default: {opts.get('currencyDefault') or 'EUR'}. "
        f"Status default: {opts.get('statusDefault') or 'Open'}."
    )

    from openai import OpenAI

    client = OpenAI(
        api_key=settings.openai_api_key, timeout=300.0, max_retries=0
    )

    logger.info(
        "file-direct extraction: model=%s file=%s size=%dB",
        settings.openai_model_mini,
        file_path.name,
        file_path.stat().st_size,
    )

    file_id, file_content = _upload_file(client, file_path)
    logger.info("uploaded to OpenAI: file_id=%s", file_id)

    try:
        response = client.responses.create(
            model=settings.openai_model_mini,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        file_content,
                        {
                            "type": "input_text",
                            "text": (
                                "The attached file is the hotel contract. "
                                f"{defaults_line}\n"
                                "Read it carefully and return ONLY the JSON "
                                "object described in the system prompt — no "
                                "markdown, no code fences, no commentary."
                            ),
                        },
                    ],
                },
            ],
            text={"format": {"type": "json_object"}},
        )
        raw_text = response.output_text or ""
    finally:
        # Best-effort cleanup so uploaded files don't accumulate.
        try:
            client.files.delete(file_id)
        except Exception:  # noqa: BLE001
            logger.warning("could not delete uploaded file %s", file_id)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Model returned non-JSON output: {exc}. First 200 chars: "
            f"{raw_text[:200]!r}"
        ) from exc
