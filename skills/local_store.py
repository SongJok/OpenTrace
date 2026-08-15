"""Skill 本地镜像仓库。

公共目录 Skill 与公司上传 Skill 都先落盘，再由运行时从本地文件安装或读取。
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infra.config.settings import settings

ROOT = Path(__file__).resolve().parents[1]
_MAX_SKILL_BYTES = 2_000_000
_SAFE_REVISION = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class LocalSkillArtifact:
    relative_path: str
    source_revision: str
    content_sha256: str
    cached_at: str


class LocalSkillStore:
    """管理可跨 API/Worker 共享的只读 Skill 镜像。"""

    def root(self) -> Path:
        configured = Path(str(settings.skillhub_local_mirror_dir)).expanduser()
        root = configured if configured.is_absolute() else ROOT / configured
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    @staticmethod
    def _scope_key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _revision_key(revision: str, content_sha256: str) -> str:
        cleaned = _SAFE_REVISION.sub("-", revision).strip("-.")[:80]
        return cleaned or content_sha256

    def _resolve_relative(self, relative_path: str) -> Path:
        root = self.root()
        target = (root / relative_path).resolve()
        if root != target and root not in target.parents:
            raise ValueError("invalid_local_skill_path")
        return target

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    def _acquire_bootstrap_lock(self):
        handle = (self.root() / ".bootstrap.lock").open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    @asynccontextmanager
    async def bootstrap_lock(self) -> AsyncIterator[None]:
        """跨 API/Worker 进程串行化首次镜像同步。"""

        handle = await asyncio.to_thread(self._acquire_bootstrap_lock)
        try:
            yield
        finally:
            await asyncio.to_thread(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
            await asyncio.to_thread(handle.close)

    def has_catalog_files(self) -> bool:
        catalog_root = self.root() / "catalog"
        try:
            return any(catalog_root.glob("*/*/SKILL.md"))
        except OSError:
            return False

    def write_catalog_skill(
        self,
        *,
        external_id: str,
        content: str,
        source_revision: str,
        metadata: dict[str, Any],
    ) -> LocalSkillArtifact:
        raw = content.encode("utf-8")
        if not raw or len(raw) > _MAX_SKILL_BYTES:
            raise ValueError("invalid_local_skill_content")
        content_sha256 = hashlib.sha256(raw).hexdigest()
        revision = source_revision.strip() or content_sha256
        relative_dir = (
            Path("catalog")
            / self._scope_key(external_id)
            / self._revision_key(revision, content_sha256)
        )
        skill_path = relative_dir / "SKILL.md"
        cached_at = datetime.now(UTC).isoformat()
        self._atomic_write(self._resolve_relative(skill_path.as_posix()), raw)
        manifest = {
            "schema_version": 1,
            "kind": "catalog",
            "external_id": external_id,
            "source_revision": revision,
            "content_sha256": content_sha256,
            "cached_at": cached_at,
            **metadata,
        }
        self._atomic_write(
            self._resolve_relative((relative_dir / "metadata.json").as_posix()),
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return LocalSkillArtifact(
            relative_path=skill_path.as_posix(),
            source_revision=revision,
            content_sha256=content_sha256,
            cached_at=cached_at,
        )

    def read_catalog_skill(self, metadata: dict[str, Any]) -> tuple[str, str]:
        relative_path = str(metadata.get("local_path") or "").strip()
        expected_sha256 = str(metadata.get("local_sha256") or "").strip()
        source_revision = str(metadata.get("local_revision") or "").strip()
        if not relative_path or not expected_sha256 or not source_revision:
            raise FileNotFoundError("local_skill_not_ready")
        path = self._resolve_relative(relative_path)
        raw = path.read_bytes()
        if not raw or len(raw) > _MAX_SKILL_BYTES:
            raise ValueError("invalid_local_skill_content")
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("local_skill_checksum_mismatch")
        return raw.decode("utf-8"), source_revision

    def catalog_available(self, metadata: dict[str, Any]) -> bool:
        relative_path = str(metadata.get("local_path") or "").strip()
        if (
            not relative_path
            or not str(metadata.get("local_sha256") or "").strip()
            or not str(metadata.get("local_revision") or "").strip()
        ):
            return False
        try:
            return self._resolve_relative(relative_path).is_file()
        except (OSError, ValueError):
            return False

    def write_company_skill(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        runtime_id: str,
        name: str,
        description: str,
        instructions: str,
        classification: str,
        source_digest: str,
    ) -> LocalSkillArtifact:
        return self.write_company_skill_package(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            runtime_id=runtime_id,
            name=name,
            description=description,
            classification=classification,
            source_digest=source_digest,
            files=[
                {
                    "path": "SKILL.md",
                    "content": instructions,
                    "content_type": "text/markdown",
                }
            ],
        )

    def write_company_skill_package(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        runtime_id: str,
        name: str,
        description: str,
        classification: str,
        source_digest: str,
        files: list[dict[str, Any]],
    ) -> LocalSkillArtifact:
        skill_md: bytes | None = None
        prepared: list[tuple[str, bytes, str]] = []
        for item in files:
            relative_path = str(item.get("path") or "").replace("\\", "/").strip("/")
            content = item.get("content")
            if not relative_path or not isinstance(content, str):
                raise ValueError("invalid_company_skill_package")
            raw = content.encode("utf-8")
            if not raw or len(raw) > _MAX_SKILL_BYTES:
                raise ValueError("invalid_company_skill_content")
            # 复用同一个安全路径解析器，拒绝包内路径穿越镜像根目录。
            resolved = self._resolve_relative(relative_path)
            if resolved == self.root() or ".." in Path(relative_path).parts:
                raise ValueError("invalid_company_skill_path")
            prepared.append((relative_path, raw, str(item.get("content_type") or "text/plain")))
            if relative_path.casefold() == "skill.md":
                skill_md = raw
        if skill_md is None:
            raise ValueError("company_skill_md_required")
        content_sha256 = hashlib.sha256(skill_md).hexdigest()
        relative_dir = (
            Path("company")
            / self._scope_key(tenant_id)
            / self._scope_key(workspace_id)
            / self._scope_key(runtime_id)
            / self._revision_key(source_digest, content_sha256)
        )
        skill_path = relative_dir / "SKILL.md"
        cached_at = datetime.now(UTC).isoformat()
        file_manifest: list[dict[str, Any]] = []
        for relative_path, raw, content_type in prepared:
            target = relative_dir / relative_path
            self._atomic_write(self._resolve_relative(target.as_posix()), raw)
            file_manifest.append(
                {
                    "path": relative_path,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size": len(raw),
                    "content_type": content_type,
                }
            )
        self._atomic_write(
            self._resolve_relative((relative_dir / "metadata.json").as_posix()),
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "company",
                    "tenant_scope": self._scope_key(tenant_id),
                    "workspace_scope": self._scope_key(workspace_id),
                    "runtime_id": runtime_id,
                    "name": name,
                    "description": description,
                    "classification": classification,
                    "source_revision": source_digest,
                    "content_sha256": content_sha256,
                    "files": file_manifest,
                    "cached_at": cached_at,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
        return LocalSkillArtifact(
            relative_path=skill_path.as_posix(),
            source_revision=source_digest,
            content_sha256=content_sha256,
            cached_at=cached_at,
        )

    def company_available(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        runtime_id: str,
        source_digest: str,
    ) -> bool:
        relative_path = (
            Path("company")
            / self._scope_key(tenant_id)
            / self._scope_key(workspace_id)
            / self._scope_key(runtime_id)
            / self._revision_key(source_digest, source_digest)
            / "SKILL.md"
        )
        try:
            return self._resolve_relative(relative_path.as_posix()).is_file()
        except (OSError, ValueError):
            return False


local_skill_store = LocalSkillStore()
