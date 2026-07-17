"""原始知识资产的标准化、Hash 去重与类型识别。"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RawAsset:
    asset_id: str
    filename: str
    content_hash: str
    asset_type: str
    size: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RawAssetManager:
    """为文件摄入提供不依赖数据库的规范化边界。"""

    text_extensions = {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".html",
        ".htm",
        ".log",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".sql",
    }

    @staticmethod
    def normalize_text(content: str) -> str:
        return "\n".join(
            line.rstrip() for line in content.replace("\r\n", "\n").split("\n")
        ).strip()

    @staticmethod
    def content_hash(content: str | bytes) -> str:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        return hashlib.sha256(payload).hexdigest()

    def from_text(
        self,
        *,
        filename: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> RawAsset:
        normalized = self.normalize_text(content)
        digest = self.content_hash(normalized)
        suffix = Path(filename).suffix.lower()
        return RawAsset(
            asset_id=digest[:36],
            filename=Path(filename).name,
            content_hash=digest,
            asset_type=self.detect_type(suffix),
            size=len(normalized.encode("utf-8")),
            content=normalized,
            metadata=dict(metadata or {}),
        )

    def from_path(self, path: str | Path, *, encoding: str = "utf-8") -> RawAsset:
        source = Path(path).expanduser().resolve()
        if source.suffix.lower() not in self.text_extensions:
            raise ValueError(f"binary_asset_requires_document_parser:{source.suffix.lower()}")
        return self.from_text(
            filename=source.name,
            content=source.read_text(encoding=encoding),
            metadata={
                "source_path": str(source),
                "mime_type": mimetypes.guess_type(source.name)[0],
            },
        )

    @staticmethod
    def detect_type(suffix: str) -> str:
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix in {".csv", ".json", ".yaml", ".yml", ".xml"}:
            return "structured_data"
        if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".sql"}:
            return "code"
        if suffix in {".html", ".htm"}:
            return "webpage"
        return "document"

    @staticmethod
    def is_duplicate(asset: RawAsset, known_hashes: set[str]) -> bool:
        return asset.content_hash in known_hashes
