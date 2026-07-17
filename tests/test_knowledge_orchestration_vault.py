from pathlib import Path

import pytest

from infra.storage.models import DocumentChunk
from knowledge.compiler import compile_payload
from knowledge.orchestration import (
    HotMemory,
    ManifestAsset,
    ManifestManager,
    QueryPipeline,
    RawAssetManager,
    RetrievalLevel,
    SchemaManager,
)
from knowledge.query import _tokens, infer_knowledge_query_type
from knowledge.workspace import (
    KnowledgeWorkspace,
    WorkspacePage,
    WorkspaceRelation,
    WorkspaceSnapshot,
    WorkspaceSource,
)


def test_schema_manager_generates_governed_obsidian_page():
    markdown = SchemaManager().generate_page(
        "concept",
        {
            "title": "知识编排",
            "description": "把原始资产转化为受治理知识。",
            "definition": "一种可编程、可追溯的知识处理方式。",
            "features": ["规则先行", "渐进式披露"],
            "source_docs": ["doc-1"],
        },
    )

    assert "managed_by: opentrace" in markdown
    assert "source_docs:" in markdown
    assert "## 定义" in markdown
    assert "## 关键特征" in markdown


def test_raw_asset_and_manifest_support_hash_dedup_and_incremental_diff():
    manager = RawAssetManager()
    first = manager.from_text(filename="policy.md", content="退款制度\r\n七天内申请。")
    same = manager.from_text(filename="copy.md", content="退款制度\n七天内申请。")
    changed = manager.from_text(filename="policy.md", content="退款制度\n十四天内申请。")

    assert first.content_hash == same.content_hash
    assert manager.is_duplicate(same, {first.content_hash}) is True

    previous = ManifestManager.build(
        workspace_id="ws",
        assets=[
            ManifestAsset(
                asset_id="doc-1",
                filename="policy.md",
                content_hash=first.content_hash,
                asset_type="markdown",
                status="published",
            )
        ],
    )
    current = ManifestManager.build(
        workspace_id="ws",
        assets=[
            ManifestAsset(
                asset_id="doc-1",
                filename="policy.md",
                content_hash=changed.content_hash,
                asset_type="markdown",
                status="published",
            )
        ],
    )

    assert ManifestManager.diff(previous, current)["updated"] == ["doc-1"]


def test_chinese_query_tokens_and_intent_do_not_require_external_segmenter():
    tokens = _tokens("请问退款政策是什么")

    assert "退款政策" in tokens
    assert "退款" in tokens
    assert "政策" in tokens
    assert infer_knowledge_query_type("退款和换货有什么区别") == "comparison"
    assert infer_knowledge_query_type("退款如何办理") == "procedure"


def test_compiler_adds_traceable_cross_page_reference_edges():
    chunks = [
        DocumentChunk(
            id="chunk-1",
            document_id="doc-1",
            chunk_index=0,
            content="退款限制适用于特殊订单。具体要求见退款流程。",
            chunk_metadata='{"heading": "退款限制"}',
        ),
        DocumentChunk(
            id="chunk-2",
            document_id="doc-1",
            chunk_index=1,
            content="退款流程要求七天内申请。",
            chunk_metadata='{"heading": "退款流程"}',
        ),
    ]
    _, _, relations = compile_payload(
        document_id="doc-1",
        source_version_id="version-1",
        title="退款制度",
        chunks=chunks,
    )

    relation_types = {item["relation_type"] for item in relations}
    assert {"references", "referenced_by"} <= relation_types


@pytest.mark.asyncio
async def test_query_pipeline_uses_hot_memory_then_governed_search():
    calls = []

    async def fake_search(**kwargs):
        calls.append(kwargs)
        return [
            {
                "id": "page-1",
                "source_type": "knowledge_page",
                "title": "退款流程",
                "text": "订单完成后七天内申请。",
                "score": 0.88,
                "disclosure_stage": "summary",
                "provenance": {"document_id": "doc-1"},
            }
        ]

    pipeline = QueryPipeline(hot_memory=HotMemory(), search_function=fake_search)
    first = await pipeline.query("退款流程", workspace_id="ws")
    second = await pipeline.query("退款流程", workspace_id="ws")

    assert calls
    assert RetrievalLevel.L2_INDEX in first.retrieval_levels_used
    assert RetrievalLevel.L1_HOT in second.retrieval_levels_used
    assert "[[退款流程]]" in second.answer


def test_materializer_creates_meta_wiki_data_and_bidirectional_links(tmp_path: Path):
    snapshot = WorkspaceSnapshot(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        owner_id="user-a",
        pages=[
            WorkspacePage(
                id="page-overview",
                source_id="source-1",
                source_version_id="version-1",
                title="退款制度",
                slug="overview",
                page_type="overview",
                content="退款制度总览。",
                summary="退款制度总览",
                authority="approved",
                confidence=0.9,
                status="published",
                metadata={"document_id": "doc-1"},
                updated_at="2026-07-16T00:00:00+00:00",
            ),
            WorkspacePage(
                id="page-action",
                source_id="source-1",
                source_version_id="version-1",
                title="退款流程",
                slug="退款流程",
                page_type="procedure",
                content="订单完成后七天内申请。",
                summary="七天内申请",
                authority="approved",
                confidence=0.88,
                status="published",
                metadata={"document_id": "doc-1"},
                updated_at="2026-07-16T01:00:00+00:00",
            ),
        ],
        relations=[
            WorkspaceRelation(
                id="relation-1",
                source_page_id="page-overview",
                target_page_id="page-action",
                relation_type="contains",
                confidence=0.9,
            )
        ],
        sources=[
            WorkspaceSource(
                id="source-1",
                document_id="doc-1",
                title="退款制度",
                content_hash="hash-1",
                authority="approved",
                status="published",
                active_version_id="version-1",
                version_number=1,
                raw_content="退款制度原文。",
            )
        ],
    )

    result = KnowledgeWorkspace().materialize_snapshot(
        snapshot,
        tmp_path / "vault",
        include_raw_assets=True,
    )

    assert result.page_count == 2
    assert (result.root / "meta" / "usage.md").exists()
    assert (result.root / "wiki" / "index.md").exists()
    assert (result.root / "wiki" / "hot.md").exists()
    assert (result.root / "data" / ".manifest.json").exists()
    assert (result.root / ".obsidian" / "app.json").exists()
    overview = next((result.root / "wiki" / "overviews").glob("*.md")).read_text(encoding="utf-8")
    action = next((result.root / "wiki" / "actions").glob("*.md")).read_text(encoding="utf-8")
    assert "[[actions/" in overview
    assert "## 反向链接" in action
    assert "managed_by: opentrace" in action
