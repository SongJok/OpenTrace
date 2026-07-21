"""可移植知识工作区的 manifest 与增量差异计算。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ManifestAsset:
    asset_id: str
    filename: str
    content_hash: str
    asset_type: str
    status: str
    source_id: str | None = None
    source_version_id: str | None = None
    wiki_page_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspaceManifest:
    workspace_id: str
    tenant_id: str = "default"
    owner_id: str | None = None
    version: str = "1.0"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    assets: list[ManifestAsset] = field(default_factory=list)
    checksums: dict[str, str] = field(default_factory=dict)
    changes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_assets"] = len(self.assets)
        return data


class ManifestManager:
    @staticmethod
    def build(
        *,
        workspace_id: str,
        assets: Iterable[ManifestAsset],
        tenant_id: str = "default",
        owner_id: str | None = None,
    ) -> WorkspaceManifest:
        ordered = sorted(assets, key=lambda item: (item.filename.lower(), item.asset_id))
        digest = hashlib.sha256(
            json.dumps(
                [asdict(item) for item in ordered],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return WorkspaceManifest(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            assets=ordered,
            checksums={"assets": digest},
        )

    @staticmethod
    def diff(
        previous: WorkspaceManifest | None,
        current: WorkspaceManifest,
    ) -> dict[str, list[str]]:
        old = {item.asset_id: item.content_hash for item in previous.assets} if previous else {}
        new = {item.asset_id: item.content_hash for item in current.assets}
        return {
            "new": sorted(set(new) - set(old)),
            "updated": sorted(key for key in set(new) & set(old) if new[key] != old[key]),
            "deleted": sorted(set(old) - set(new)),
            "unchanged": sorted(key for key in set(new) & set(old) if new[key] == old[key]),
        }

    @staticmethod
    def load(path: str | Path) -> WorkspaceManifest | None:
        target = Path(path)
        if not target.exists():
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
        return WorkspaceManifest(
            workspace_id=data["workspace_id"],
            tenant_id=data.get("tenant_id", "default"),
            owner_id=data.get("owner_id"),
            version=data.get("version", "1.0"),
            generated_at=data.get("generated_at", ""),
            assets=[
                ManifestAsset(
                    **{
                        **item,
                        "wiki_page_ids": tuple(item.get("wiki_page_ids") or ()),
                    }
                )
                for item in data.get("assets", [])
            ],
            checksums=data.get("checksums", {}),
            changes=data.get("changes", {}),
        )

    @staticmethod
    def write(manifest: WorkspaceManifest, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    manifest.to_dict(),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target
