"""File parsing utilities stub."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


async def parse_attachment_content(file_path: str, content_type: str) -> str:
    return ""


def get_image_raw_data(file_path: str) -> tuple[str, str] | None:
    p = Path(file_path)
    if not p.exists():
        return None
    ext_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    mime = ext_map.get(p.suffix.lower(), "application/octet-stream")
    try:
        data = base64.b64encode(p.read_bytes()).decode()
        return data, mime
    except Exception:
        return None
