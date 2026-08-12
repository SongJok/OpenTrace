from __future__ import annotations

from sqlalchemy import select

from gateway.api_gateway.routers.responses import OpenTraceOptions
from infra.storage.models import Document
from kernel.agent_loop.contracts import (
    ExecutionPlan,
    ExecutionProfile,
    ExecutionStep,
    IntentPlan,
    PlanningDecision,
)
from kernel.agent_loop.rag_routing import resolve_rag_routing
from kernel.agent_loop.runner import AgentLoop
from kernel.cognitive_controls import _strip_rag_routing_query
from plugins.document_retrieval import _apply_document_scope, tokenize


def test_slash_rag_is_a_required_route_and_does_not_pollute_query() -> None:
    decision = resolve_rag_routing(" /rag  请假流程是什么？ ")

    assert decision.required is True
    assert decision.explicit_command is True
    assert decision.reason == "slash_command"
    assert decision.query == "请假流程是什么？"
    assert decision.sources == ("knowledge", "documents")
    assert _strip_rag_routing_query("/RAG 请假流程是什么？") == "请假流程是什么？"


def test_enterprise_grounding_is_fail_closed_to_governed_knowledge() -> None:
    decision = resolve_rag_routing(
        "我们的请假制度是什么？",
        enterprise_grounding=True,
    )

    assert decision.required is True
    assert decision.reason == "enterprise_grounding"
    assert decision.sources == ("knowledge",)


def test_explicit_knowledge_request_does_not_match_definition_question() -> None:
    assert resolve_rag_routing("请根据企业知识库回答请假流程").required is True
    assert resolve_rag_routing("从我的资料中查找报销要求").required is True
    assert resolve_rag_routing("什么是知识库？").required is False


def test_api_knowledge_mode_can_require_rag_without_legacy_force_mode() -> None:
    options = OpenTraceOptions(knowledge_mode="required")
    assert options.knowledge_mode == "required"


def test_required_rag_policy_supplements_intent_and_plan() -> None:
    decision = PlanningDecision(
        intent=IntentPlan(
            goal="回答制度问题",
            capabilities=(),
            execution_profile=ExecutionProfile.AUTO,
            clarification_question="请提供文档",
        ),
        execution_plan=ExecutionPlan(
            goal="回答制度问题",
            steps=(
                ExecutionStep(
                    id="answer",
                    objective="生成回答",
                    success_criteria="回答完成",
                ),
            ),
        ),
    )

    grounded = AgentLoop._apply_required_rag_policy(decision)

    assert grounded.intent.capabilities == ("rag",)
    assert grounded.intent.clarification_question is None
    assert grounded.execution_plan.steps[0].capability == "rag"


def test_workspace_document_scope_keeps_current_users_documents() -> None:
    stmt = _apply_document_scope(
        select(Document),
        user_id="user-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "documents.tenant_id = 'tenant-a'" in sql
    assert "documents.workspace_id = 'workspace-a'" in sql
    assert "documents.owner_id = 'user-a'" in sql


def test_chinese_document_tokenization_extracts_business_terms() -> None:
    terms = tokenize("请根据企业知识库告诉我公司的请假流程是什么？")

    assert "请假" in terms
    assert "流程" in terms
    assert "公司" in terms or "企业" in terms
