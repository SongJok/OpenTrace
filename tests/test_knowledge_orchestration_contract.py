from infra.storage.models import DocumentChunk
from knowledge.compiler import compile_payload
from knowledge.domain import (
    KNOWLEDGE_QUERY_PLAN_VERSION,
    KnowledgeStatus,
    source_status_during_refresh,
)
from knowledge.query import build_knowledge_query_plan
from services.rag_query_planning import build_rag_query_plan, normalize_rag_evidence
from services.rag_retrieval_fusion import reciprocal_rank_fusion


def _chunk(chunk_id: str, index: int, content: str, heading: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id="doc-1",
        chunk_index=index,
        content=content,
        chunk_metadata=f'{{"heading": "{heading}"}}',
    )


def test_compiler_creates_traceable_pages_claims_and_bidirectional_navigation_seed():
    pages, claims, relations = compile_payload(
        document_id="doc-1",
        source_version_id="version-1",
        title="退款制度",
        chunks=[
            _chunk(
                "chunk-1", 0, "退款需要在订单完成后七天内申请。提交申请后由客服审核。", "退款流程"
            ),
            _chunk("chunk-2", 1, "特殊订单不支持退款。", "退款限制"),
        ],
    )

    assert pages[0]["page_type"] == "overview"
    assert {page["title"] for page in pages} >= {"退款制度", "退款流程", "退款限制"}
    assert claims and all(claim["evidence_chunk_id"] for claim in claims)
    assert {relation["relation_type"] for relation in relations} == {"contains", "part_of"}
    assert len(relations) == (len(pages) - 1) * 2


def test_compiler_deduplicates_repeated_claims_within_the_same_page():
    _, claims, _ = compile_payload(
        document_id="doc-1",
        source_version_id="version-1",
        title="运行手册",
        chunks=[
            _chunk("chunk-1", 0, "服务启动后执行健康检查。", "部署流程"),
            _chunk("chunk-2", 1, "服务启动后执行健康检查。", "部署流程"),
        ],
    )

    assert len(claims) == 1
    assert claims[0]["evidence_chunk_id"] == "chunk-1"
    assert len({claim["id"] for claim in claims}) == len(claims)


def test_refresh_keeps_previous_published_revision_queryable():
    assert (
        source_status_during_refresh("version-live", KnowledgeStatus.COMPILING)
        == KnowledgeStatus.PUBLISHED.value
    )
    assert (
        source_status_during_refresh("version-live", KnowledgeStatus.ERROR)
        == KnowledgeStatus.PUBLISHED.value
    )
    assert (
        source_status_during_refresh(None, KnowledgeStatus.COMPILING)
        == KnowledgeStatus.COMPILING.value
    )


def test_knowledge_query_plan_uses_progressive_disclosure_and_relation_hops():
    plan = build_knowledge_query_plan("relation", 5).to_dict()

    assert plan["version"] == KNOWLEDGE_QUERY_PLAN_VERSION
    assert plan["paths"][:3] == ["hot_knowledge", "knowledge_page", "knowledge_relation"]
    assert plan["progressive_disclosure"] == ["summary", "page", "claim", "source_evidence"]
    assert plan["max_hops"] == 2


def test_rag_plan_exposes_governed_knowledge_lane_and_evidence_provenance():
    plan = build_rag_query_plan(
        raw_query="退款政策是什么",
        normalized_query="退款政策是什么",
        rewritten_query="退款政策",
        query_type="definition",
        hints=[],
        query_terms=["退款", "政策"],
        sources=["knowledge", "documents"],
        top_k=4,
        llmwiki_top_k=2,
        min_score=0.35,
        user_id="u1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    )
    data = plan.to_dict()
    lanes = {lane["name"]: lane for lane in data["lanes"]}
    evidence = normalize_rag_evidence(
        {
            "id": "claim-1",
            "source_type": "knowledge_claim",
            "text": "订单完成后七天内可退款。",
            "score": 0.8,
            "knowledge_page_id": "page-1",
            "claim_id": "claim-1",
            "source_id": "source-1",
            "source_version_id": "version-1",
            "provenance": {"document_id": "doc-1", "evidence_chunk_id": "chunk-1"},
        },
        plan=plan,
    )

    assert lanes["knowledge"]["enabled"] is True
    assert data["knowledge_plan"]["progressive_disclosure"][0] == "summary"
    assert evidence["lane"] == "knowledge"
    assert evidence["claim_id"] == "claim-1"
    assert evidence["provenance"]["evidence_chunk_id"] == "chunk-1"


def test_weighted_rrf_is_calibrated_and_keeps_knowledge_provenance():
    merged = reciprocal_rank_fusion(
        [
            {
                "source_type": "knowledge_claim",
                "id": "claim-1",
                "text": "订单完成后七天内可退款。",
                "score": 0.8,
                "claim_id": "claim-1",
            },
            {
                "source_type": "document",
                "id": "chunk-1",
                "text": "退款流程原文。",
                "score": 0.8,
            },
        ],
        lane_weights={"knowledge": 1.25, "document": 1.0},
        top_n=2,
    )

    assert len(merged) == 2
    assert all(0.0 <= row["rrf_score"] <= 1.0 for row in merged)
    assert all("raw_score" in row for row in merged)
    assert any(row.get("claim_id") == "claim-1" for row in merged)
