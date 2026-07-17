"""将受治理知识投影为 WorkBuddy + Obsidian 风格的三层 Vault。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    Document,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeSource,
    KnowledgeSourceVersion,
)
from knowledge.orchestration.data.version.manifest import (
    ManifestAsset,
    ManifestManager,
    WorkspaceManifest,
)
from knowledge.orchestration.metadata.build_guidelines import BuildGuidelines
from knowledge.orchestration.wiki.query.hot_memory import HotMemory


@dataclass(frozen=True, slots=True)
class WorkspacePage:
    id: str
    source_id: str
    source_version_id: str
    title: str
    slug: str
    page_type: str
    content: str
    summary: str
    authority: str
    confidence: float
    status: str
    metadata: dict[str, Any]
    updated_at: str


@dataclass(frozen=True, slots=True)
class WorkspaceRelation:
    id: str
    source_page_id: str
    target_page_id: str
    relation_type: str
    confidence: float


@dataclass(frozen=True, slots=True)
class WorkspaceSource:
    id: str
    document_id: str | None
    title: str
    content_hash: str
    authority: str
    status: str
    active_version_id: str
    version_number: int
    raw_content: str | None = None


@dataclass(slots=True)
class WorkspaceSnapshot:
    tenant_id: str
    workspace_id: str
    owner_id: str | None
    pages: list[WorkspacePage] = field(default_factory=list)
    relations: list[WorkspaceRelation] = field(default_factory=list)
    sources: list[WorkspaceSource] = field(default_factory=list)


@dataclass(slots=True)
class MaterializeResult:
    root: Path
    page_count: int
    relation_count: int
    source_count: int
    written_files: list[Path]
    manifest: WorkspaceManifest


class KnowledgeWorkspace:
    """数据库为事实源，Vault 为可读、可搜索、可迁移的只读投影。"""

    page_directories = {
        "overview": "overviews",
        "concept": "concepts",
        "entity": "entities",
        "question": "questions",
        "procedure": "actions",
        "policy": "policies",
        "case": "cases",
        "metric": "metrics",
        "term": "terms",
    }

    async def snapshot(
        self,
        *,
        tenant_id: str = "default",
        workspace_id: str = "default",
        owner_id: str | None = None,
        include_raw_assets: bool = False,
    ) -> WorkspaceSnapshot:
        page_conditions = [
            KnowledgePage.tenant_id == tenant_id,
            KnowledgePage.workspace_id == workspace_id,
            KnowledgePage.status == "published",
            KnowledgeSource.status == "published",
            KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
        ]
        relation_conditions = [
            KnowledgeRelation.tenant_id == tenant_id,
            KnowledgeRelation.workspace_id == workspace_id,
            KnowledgeRelation.status == "published",
        ]
        source_conditions = [
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.workspace_id == workspace_id,
            KnowledgeSource.status == "published",
            KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
        ]
        if owner_id:
            page_conditions.append(KnowledgePage.owner_id == owner_id)
            relation_conditions.append(KnowledgeRelation.owner_id == owner_id)
            source_conditions.append(KnowledgeSource.owner_id == owner_id)

        async with AsyncSessionLocal() as db:
            page_rows = (
                await db.execute(
                    select(KnowledgePage, KnowledgeSource)
                    .join(
                        KnowledgeSourceVersion,
                        KnowledgePage.source_version_id == KnowledgeSourceVersion.id,
                    )
                    .join(
                        KnowledgeSource,
                        KnowledgeSourceVersion.source_id == KnowledgeSource.id,
                    )
                    .where(*page_conditions)
                    .order_by(KnowledgePage.page_type, KnowledgePage.title)
                )
            ).all()
            relation_rows = list(
                (await db.execute(select(KnowledgeRelation).where(*relation_conditions))).scalars()
            )
            source_rows = (
                await db.execute(
                    select(KnowledgeSource, KnowledgeSourceVersion)
                    .join(
                        KnowledgeSourceVersion,
                        KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                    )
                    .where(*source_conditions)
                    .order_by(KnowledgeSource.title)
                )
            ).all()
            documents: dict[str, Document] = {}
            if include_raw_assets:
                document_ids = [
                    source.document_id for source, _ in source_rows if source.document_id
                ]
                if document_ids:
                    documents = {
                        document.id: document
                        for document in (
                            await db.execute(select(Document).where(Document.id.in_(document_ids)))
                        ).scalars()
                    }

        return WorkspaceSnapshot(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
            pages=[
                WorkspacePage(
                    id=page.id,
                    source_id=source.id,
                    source_version_id=page.source_version_id,
                    title=page.title,
                    slug=page.slug,
                    page_type=page.page_type,
                    content=page.content,
                    summary=page.summary or "",
                    authority=page.authority,
                    confidence=page.confidence,
                    status=page.status,
                    metadata=dict(page.page_metadata or {}),
                    updated_at=page.updated_at.isoformat() if page.updated_at else "",
                )
                for page, source in page_rows
            ],
            relations=[
                WorkspaceRelation(
                    id=row.id,
                    source_page_id=row.source_page_id,
                    target_page_id=row.target_page_id,
                    relation_type=row.relation_type,
                    confidence=row.confidence,
                )
                for row in relation_rows
            ],
            sources=[
                WorkspaceSource(
                    id=source.id,
                    document_id=source.document_id,
                    title=source.title,
                    content_hash=source.content_hash,
                    authority=source.authority,
                    status=source.status,
                    active_version_id=version.id,
                    version_number=version.version_number,
                    raw_content=(
                        documents[source.document_id].content
                        if include_raw_assets and source.document_id in documents
                        else None
                    ),
                )
                for source, version in source_rows
            ],
        )

    async def materialize(
        self,
        output_dir: str | Path,
        *,
        tenant_id: str = "default",
        workspace_id: str = "default",
        owner_id: str | None = None,
        include_raw_assets: bool = False,
    ) -> MaterializeResult:
        snapshot = await self.snapshot(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
            include_raw_assets=include_raw_assets,
        )
        return self.materialize_snapshot(
            snapshot,
            output_dir,
            include_raw_assets=include_raw_assets,
        )

    def materialize_snapshot(
        self,
        snapshot: WorkspaceSnapshot,
        output_dir: str | Path,
        *,
        include_raw_assets: bool = False,
    ) -> MaterializeResult:
        root = Path(output_dir).expanduser().resolve()
        meta_dir = root / "meta"
        wiki_dir = root / "wiki"
        data_dir = root / "data"
        for directory in (meta_dir, wiki_dir, data_dir, root / ".obsidian"):
            directory.mkdir(parents=True, exist_ok=True)

        written: list[Path] = []
        for filename, content in BuildGuidelines.metadata_documents().items():
            written.append(self._write_text(meta_dir / filename, content))

        path_by_page = {page.id: self._page_relative_path(page) for page in snapshot.pages}
        page_by_id = {page.id: page for page in snapshot.pages}
        outgoing: dict[str, list[WorkspaceRelation]] = {}
        incoming: dict[str, list[WorkspaceRelation]] = {}
        for relation in snapshot.relations:
            outgoing.setdefault(relation.source_page_id, []).append(relation)
            incoming.setdefault(relation.target_page_id, []).append(relation)

        for page in snapshot.pages:
            target = wiki_dir / path_by_page[page.id]
            content = self._render_page(
                page,
                page_by_id=page_by_id,
                path_by_page=path_by_page,
                outgoing=outgoing.get(page.id, []),
                incoming=incoming.get(page.id, []),
            )
            written.append(self._write_text(target, content))

        written.append(
            self._write_text(
                wiki_dir / "index.md",
                self._render_index(snapshot.pages, path_by_page),
            )
        )
        hot = HotMemory(max_entries=20)
        hot.remember(
            [
                {
                    "id": page.id,
                    "title": page.title,
                    "text": page.summary or page.content[:300],
                    "score": page.confidence,
                    "source_type": "knowledge_page",
                    "knowledge_page_id": page.id,
                }
                for page in sorted(
                    snapshot.pages,
                    key=lambda item: item.updated_at,
                    reverse=True,
                )[:20]
            ]
        )
        written.append(
            self._write_text(
                wiki_dir / "hot.md",
                hot.render_markdown(workspace_id=snapshot.workspace_id),
            )
        )

        source_pages: dict[str, list[str]] = {}
        for page in snapshot.pages:
            source_pages.setdefault(page.source_id, []).append(page.id)
        assets: list[ManifestAsset] = []
        for source in snapshot.sources:
            raw_path = f"sources/{source.id}.md" if include_raw_assets else None
            if include_raw_assets:
                written.append(
                    self._write_text(
                        data_dir / raw_path,
                        self._render_source(source),
                    )
                )
            assets.append(
                ManifestAsset(
                    asset_id=source.document_id or source.id,
                    filename=source.title,
                    content_hash=source.content_hash,
                    asset_type="document",
                    status=source.status,
                    source_id=source.id,
                    source_version_id=source.active_version_id,
                    wiki_page_ids=tuple(source_pages.get(source.id, [])),
                    metadata={
                        "version_number": source.version_number,
                        "authority": source.authority,
                        "raw_path": raw_path,
                        "wiki_paths": [
                            f"wiki/{path_by_page[page_id].as_posix()}"
                            for page_id in source_pages.get(source.id, [])
                        ],
                    },
                )
            )

        manifest_path = data_dir / ".manifest.json"
        previous = ManifestManager.load(manifest_path)
        manifest = ManifestManager.build(
            workspace_id=snapshot.workspace_id,
            tenant_id=snapshot.tenant_id,
            owner_id=snapshot.owner_id,
            assets=assets,
        )
        manifest.changes = ManifestManager.diff(previous, manifest)
        self._remove_stale_generated_files(root, previous, manifest)
        written.append(ManifestManager.write(manifest, manifest_path))
        written.extend(self._write_obsidian_config(root))
        return MaterializeResult(
            root=root,
            page_count=len(snapshot.pages),
            relation_count=len(snapshot.relations),
            source_count=len(snapshot.sources),
            written_files=written,
            manifest=manifest,
        )

    def _render_page(
        self,
        page: WorkspacePage,
        *,
        page_by_id: dict[str, WorkspacePage],
        path_by_page: dict[str, Path],
        outgoing: list[WorkspaceRelation],
        incoming: list[WorkspaceRelation],
    ) -> str:
        frontmatter = {
            "id": page.id,
            "type": page.page_type,
            "title": page.title,
            "status": page.status,
            "authority": page.authority,
            "confidence": round(page.confidence, 4),
            "source_id": page.source_id,
            "source_version_id": page.source_version_id,
            "source_docs": (
                [page.metadata.get("document_id")] if page.metadata.get("document_id") else []
            ),
            "updated": page.updated_at,
            "stale": page.status == "stale",
            "managed_by": "opentrace",
        }
        lines = [
            "---",
            yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
            "---",
            "",
            f"# {page.title}",
            "",
        ]
        if page.summary:
            lines.extend([f"> {page.summary}", ""])
        lines.append(page.content.strip())
        related = []
        for relation in outgoing:
            target = page_by_id.get(relation.target_page_id)
            if target:
                related.append(
                    f"- {relation.relation_type}: "
                    f"{self._wikilink(path_by_page[target.id], target.title)}"
                )
        backlinks = []
        for relation in incoming:
            source = page_by_id.get(relation.source_page_id)
            if source:
                backlinks.append(
                    f"- {relation.relation_type}: "
                    f"{self._wikilink(path_by_page[source.id], source.title)}"
                )
        if related:
            lines.extend(["", "## 相关知识", "", *sorted(set(related))])
        if backlinks:
            lines.extend(["", "## 反向链接", "", *sorted(set(backlinks))])
        lines.extend(
            [
                "",
                "## 溯源",
                "",
                f"- source_id: `{page.source_id}`",
                f"- source_version_id: `{page.source_version_id}`",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_index(self, pages: list[WorkspacePage], paths: dict[str, Path]) -> str:
        lines = [
            "---",
            "type: index",
            "title: 知识索引",
            "auto_generated: true",
            "managed_by: opentrace",
            "---",
            "",
            "# 知识索引",
            "",
            "[[hot|工作记忆]]",
        ]
        grouped: dict[str, list[WorkspacePage]] = {}
        for page in pages:
            grouped.setdefault(page.page_type, []).append(page)
        for page_type, items in sorted(grouped.items()):
            lines.extend(["", f"## {page_type}", ""])
            for page in sorted(items, key=lambda item: item.title):
                lines.append(f"- {self._wikilink(paths[page.id], page.title)}")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_source(source: WorkspaceSource) -> str:
        frontmatter = {
            "id": source.id,
            "document_id": source.document_id,
            "title": source.title,
            "content_hash": source.content_hash,
            "authority": source.authority,
            "status": source.status,
            "source_version_id": source.active_version_id,
            "version_number": source.version_number,
            "managed_by": "opentrace",
        }
        return "\n".join(
            [
                "---",
                yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
                "---",
                "",
                f"# {source.title}",
                "",
                source.raw_content or "> 原始内容未包含在本次物化中。",
                "",
            ]
        )

    def _page_relative_path(self, page: WorkspacePage) -> Path:
        directory = self.page_directories.get(page.page_type, "pages")
        slug = self._safe_slug(page.slug or page.title)
        return Path(directory) / f"{slug}--{page.id[:8]}.md"

    @staticmethod
    def _safe_slug(value: str) -> str:
        normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.lower()).strip("-")
        return normalized[:120] or "page"

    @staticmethod
    def _wikilink(path: Path, title: str) -> str:
        return f"[[{path.with_suffix('').as_posix()}|{title}]]"

    @staticmethod
    def _write_text(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _remove_stale_generated_files(
        root: Path,
        previous: WorkspaceManifest | None,
        current: WorkspaceManifest,
    ) -> None:
        if previous is None:
            return
        current_paths = {
            path
            for asset in current.assets
            for path in (
                list(asset.metadata.get("wiki_paths") or [])
                + ([f"data/{asset.metadata['raw_path']}"] if asset.metadata.get("raw_path") else [])
            )
        }
        previous_paths = {
            path
            for asset in previous.assets
            for path in (
                list(asset.metadata.get("wiki_paths") or [])
                + ([f"data/{asset.metadata['raw_path']}"] if asset.metadata.get("raw_path") else [])
            )
        }
        for relative in previous_paths - current_paths:
            target = (root / relative).resolve()
            if root == target or root not in target.parents:
                continue
            if target.exists() and target.is_file():
                target.unlink()

    def _write_obsidian_config(self, root: Path) -> list[Path]:
        config = root / ".obsidian"
        return [
            self._write_text(
                config / "app.json",
                json.dumps(
                    {
                        "alwaysUpdateLinks": True,
                        "newFileLocation": "folder",
                        "newFileFolderPath": "wiki",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
            self._write_text(
                config / "graph.json",
                json.dumps(
                    {
                        "collapse-filter": False,
                        "showTags": True,
                        "showAttachments": False,
                        "hideUnresolved": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
        ]


KnowledgeVault = KnowledgeWorkspace
