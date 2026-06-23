"""Image / vision parser.

We don't run a local OCR engine. The image bytes are forwarded to the OpenAI
vision-capable model. When no API key is present, we return an empty
extraction with a warning — the rest of the pipeline still completes.

This module is also reused by the PDF stage to call vision for pages flagged
as needing OCR.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image  # noqa: F401  (validates the file)

from ...config import get_settings


def _read_b64(path: Path) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def parse_image(path: str | Path) -> Dict[str, Any]:
    """Return a flat image-record. Vision text is filled lazily on demand."""
    p = Path(path)
    try:
        with Image.open(p) as im:
            w, h = im.size
            mode = im.mode
    except Exception:  # noqa: BLE001
        w, h, mode = 0, 0, "unknown"

    return {
        "source_file": p.name,
        "input_format": "image",
        "path": str(p),
        "width": w,
        "height": h,
        "mode": mode,
        # Filled in when vision is invoked.
        "vision_text": None,
        "vision_tables": [],
        "warnings": [],
    }


def run_vision_on_image(path: str | Path, *, prompt: Optional[str] = None) -> Dict[str, Any]:
    """Call OpenAI vision on an image. Returns dict with text + warnings."""
    settings = get_settings()
    if not settings.openai_api_key:
        return {
            "text": "",
            "warnings": ["OpenAI API key not configured — vision skipped."],
        }
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        b64 = _read_b64(Path(path))

        ext = Path(path).suffix.lower().lstrip(".")
        mime = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }.get(ext, "image/png")

        user_prompt = (
            prompt
            or (
                "You are extracting structured text from a hotel contract image. "
                "Transcribe ALL visible text faithfully. Preserve table layout using "
                "tabs/newlines. Do not invent content. Output plain text only."
            )
        )

        resp = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                }
            ],
            temperature=0,
        )
        text = resp.choices[0].message.content or ""
        return {"text": text, "warnings": []}
    except Exception as e:  # noqa: BLE001
        return {"text": "", "warnings": [f"Vision call failed: {e}"]}


def attach_vision_text(image_record: Dict[str, Any]) -> Dict[str, Any]:
    out = run_vision_on_image(image_record["path"])
    image_record["vision_text"] = out["text"]
    image_record["warnings"] = list(image_record.get("warnings", [])) + list(out["warnings"])
    return image_record


__all__ = ["parse_image", "run_vision_on_image", "attach_vision_text"]
