"""Manager Loop 的持久 SQL 草案续执行与投影策略。"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import ResponseRecord
from kernel.agent_loop.context import ContextAssembler
from kernel.agent_loop.contracts import (
    DataIntentStage,
    EvidenceRequirement,
    ExecutionPlan,
    ExecutionStep,
    FreshnessRequirement,
    InformationSource,
    IntentPlan,
    PlanningDecision,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.write_intent import is_sql_draft_execution_request


def recent_user_queries(
    messages: list[dict[str, Any]],
    *,
    current_message_count: int,
    limit: int = 4,
) -> list[str]:
    history_end = max(1, len(messages) - max(0, current_message_count))
    queries = [
        str(message.get("content") or "").strip()
        for message in messages[1:history_end]
        if str(message.get("role") or "") == "user"
        and isinstance(message.get("content"), str)
        and str(message.get("content") or "").strip()
    ]
    return queries[-max(1, limit) :]


def pending_action_from_context(
    messages: list[dict[str, Any]],
    specs: list[ToolSpec],
    *,
    current_message_count: int,
) -> dict[str, Any] | None:
    history_end = max(1, len(messages) - max(0, current_message_count))
    history = messages[1:history_end]
    completed_call_ids = {
        str(message.get("tool_call_id") or "")
        for message in history
        if str(message.get("role") or "") == "tool"
    }
    spec_by_name = {spec.name: spec for spec in specs}
    for message in reversed(history):
        for call in reversed(list(message.get("tool_calls") or [])):
            function = dict(call.get("function") or {})
            name = str(call.get("name") or function.get("name") or "")
            call_id = str(call.get("call_id") or call.get("id") or "")
            spec = spec_by_name.get(name)
            if spec is None or spec.side_effect == SideEffect.READ:
                continue
            if call_id and call_id in completed_call_ids:
                continue
            raw_arguments = call.get("arguments") or function.get("arguments") or {}
            if isinstance(raw_arguments, str):
                try:
                    raw_arguments = json.loads(raw_arguments)
                except (TypeError, ValueError):
                    raw_arguments = {}
            return {
                "name": name,
                "call_id": call_id,
                "arguments": dict(raw_arguments) if isinstance(raw_arguments, dict) else {},
            }
    return None


async def pending_sql_draft(
    db: AsyncSession,
    *,
    response: ResponseRecord,
) -> dict[str, Any] | None:
    """只从当前 Response 父链恢复尚可执行的 DataAgent 草案。"""

    from infra.storage.models import SQLQueryCandidate, SQLQueryDraft

    response_ids: list[str] = []
    current_id = response.parent_response_id
    seen: set[str] = set()
    while current_id and current_id not in seen and len(response_ids) < 64:
        seen.add(current_id)
        parent = await db.get(ResponseRecord, current_id)
        if parent is None or not ContextAssembler._same_response_scope(parent, response):
            break
        response_ids.append(parent.id)
        current_id = parent.parent_response_id
    if not response_ids:
        return None
    draft = await db.scalar(
        select(SQLQueryDraft)
        .where(
            SQLQueryDraft.response_id.in_(response_ids),
            SQLQueryDraft.conversation_id == response.conversation_id,
            SQLQueryDraft.user_id == response.user_id,
            SQLQueryDraft.tenant_id == response.tenant_id,
            SQLQueryDraft.workspace_id == response.workspace_id,
            SQLQueryDraft.status.in_(["awaiting_confirmation", "failed", "partially_failed"]),
        )
        .order_by(SQLQueryDraft.created_at.desc())
        .limit(1)
    )
    if draft is None:
        return None
    candidates = list(
        (
            await db.execute(
                select(SQLQueryCandidate)
                .where(SQLQueryCandidate.draft_id == draft.id)
                .order_by(SQLQueryCandidate.position)
            )
        )
        .scalars()
        .all()
    )
    available = [
        {
            "id": item.id,
            "position": int(item.position),
            "title": item.title,
            "execution_status": item.execution_status,
        }
        for item in candidates
        if item.execution_status in {"pending", "failed"}
    ]
    if not available:
        return None
    return {
        "draft_id": draft.id,
        "group_type": draft.group_type,
        "question": draft.question,
        "candidates": available,
    }


def resolve_sql_draft_execution_request(
    query: str,
    draft: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """把用户对已展示候选的选择确定性绑定为持久草案执行参数。"""

    if draft is None or not is_sql_draft_execution_request(query):
        return None
    candidates = list(draft.get("candidates") or [])
    normalized = re.sub(r"\s+", "", query or "").lower()
    retry_failed = any(marker in normalized for marker in ("重试", "retry"))
    execute_all = any(
        marker in normalized
        for marker in ("全部候选", "所有候选", "执行全部", "全部执行", "allcandidates")
    )
    selected_ids = [
        str(item["id"])
        for item in candidates
        if str(item.get("id") or "") and str(item["id"]).lower() in normalized
    ]
    if not selected_ids and not execute_all:
        ordinal_patterns = (
            (1, ("第一个", "第一条", "候选1", "候选一", "方案1", "方案一")),
            (2, ("第二个", "第二条", "候选2", "候选二", "方案2", "方案二")),
            (3, ("第三个", "第三条", "候选3", "候选三", "方案3", "方案三")),
        )
        selected_positions = {
            position
            for position, markers in ordinal_patterns
            if any(marker in normalized for marker in markers)
        }
        selected_ids = [
            str(item["id"])
            for item in candidates
            if int(item.get("position") or 0) in selected_positions
        ]
    eligible = [
        item
        for item in candidates
        if item.get("execution_status") == "pending"
        or (retry_failed and item.get("execution_status") == "failed")
    ]
    eligible_ids = {str(item["id"]) for item in eligible}
    selected_ids = [item_id for item_id in selected_ids if item_id in eligible_ids]
    alternative_all_rejected = False
    if execute_all and str(draft.get("group_type") or "alternative") == "alternative":
        if len(eligible) == 1:
            execute_all = False
            selected_ids = [str(eligible[0]["id"])]
        else:
            execute_all = False
            selected_ids = []
            alternative_all_rejected = True
    if str(draft.get("group_type") or "alternative") == "alternative" and len(selected_ids) > 1:
        selected_ids = []
    if not alternative_all_rejected and not execute_all and not selected_ids and len(eligible) == 1:
        selected_ids = [str(eligible[0]["id"])]
    if not execute_all and not selected_ids:
        options = "；".join(
            f"候选 {item['position']}（ID：{item['id']}，状态：{item['execution_status']}）"
            for item in candidates
        )
        return {
            "status": "clarify",
            "draft_id": draft["draft_id"],
            "original_question": str(draft.get("question") or ""),
            "question": (
                f"请明确选择一个要执行的 SQL 候选：{options}。"
                "备选方案需要分别验证，不能在一次企业问数回答中同时执行。"
            ),
        }
    return {
        "status": "ready",
        "draft_id": draft["draft_id"],
        "original_question": str(draft.get("question") or ""),
        "arguments": {
            "draft_id": draft["draft_id"],
            "candidate_ids": [] if execute_all else selected_ids,
            "execute_all": execute_all,
            "retry_failed": retry_failed,
        },
    }


def apply_pending_sql_draft_policy(
    decision: PlanningDecision,
    request: dict[str, Any],
) -> PlanningDecision:
    intent = decision.intent
    if request.get("status") == "clarify":
        clarified = IntentPlan(
            goal=intent.goal,
            task_type="data_query_execution",
            capabilities=(),
            ambiguity="sql_candidate_selection_required",
            risk=SideEffect.READ,
            execution_profile=intent.execution_profile,
            execution_mode=intent.execution_mode,
            expected_outputs=("candidate_selection",),
            clarification_question=str(request.get("question") or "请明确选择 SQL 候选。"),
            information_sources=(InformationSource.DATA,),
            freshness_requirement=FreshnessRequirement.CURRENT,
            evidence_requirements=(
                EvidenceRequirement.METRIC_DEFINITION,
                EvidenceRequirement.TRUSTED_DATA_SOURCE,
                EvidenceRequirement.BUSINESS_RULES,
                EvidenceRequirement.VALIDATED_SQL,
            ),
            data_stage=DataIntentStage.SELECT_CANDIDATE,
        )
        return PlanningDecision(
            intent=clarified,
            execution_plan=ExecutionPlan(
                goal=decision.execution_plan.goal or intent.goal,
                complexity="simple",
                steps=(
                    ExecutionStep(
                        id="select-sql-candidate",
                        objective="等待用户明确选择已展示的 SQL 候选",
                        success_criteria="候选 ID 或执行全部范围明确",
                    ),
                ),
                success_criteria=("不在候选范围不明确时执行数据库查询",),
                replan_limit=0,
            ),
        )
    executable_intent = IntentPlan(
        goal=intent.goal,
        task_type="data_query_execution",
        capabilities=("execute_sql_draft",),
        ambiguity=None,
        risk=SideEffect.WRITE,
        execution_profile=intent.execution_profile,
        execution_mode=intent.execution_mode,
        expected_outputs=("verified_data_answer", "citations"),
        clarification_question=None,
        information_sources=(InformationSource.DATA,),
        freshness_requirement=FreshnessRequirement.CURRENT,
        evidence_requirements=(
            EvidenceRequirement.METRIC_DEFINITION,
            EvidenceRequirement.TRUSTED_DATA_SOURCE,
            EvidenceRequirement.BUSINESS_RULES,
            EvidenceRequirement.VALIDATED_SQL,
            EvidenceRequirement.EXECUTED_RESULT,
        ),
        data_stage=DataIntentStage.EXECUTE_AND_VERIFY,
    )
    return PlanningDecision(
        intent=executable_intent,
        execution_plan=ExecutionPlan(
            goal=decision.execution_plan.goal or executable_intent.goal,
            complexity="simple",
            steps=(
                ExecutionStep(
                    id="execute-governed-sql-draft",
                    objective="执行用户明确选择且经过治理校验的 SQL 草案候选",
                    capability="execute_sql_draft",
                    success_criteria="完成权限、Schema、语义、EXPLAIN 和结果校验并返回带证据答案",
                ),
            ),
            success_criteria=("数据答案通过结果校验并带可核验引用",),
            replan_limit=0,
        ),
    )


def _tool_name(call: dict[str, Any]) -> str:
    raw_function = call.get("function")
    function = raw_function if isinstance(raw_function, dict) else {}
    return str(call.get("name") or function.get("name") or "")


def bind_sql_draft_execution_call(
    call: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    if _tool_name(call) != "execute_sql_draft":
        return call
    arguments = dict(request.get("arguments") or {})
    call_id = str(call.get("call_id") or call.get("id") or f"call_{uuid.uuid4().hex}")
    return {
        "id": call_id,
        "call_id": call_id,
        "name": "execute_sql_draft",
        "type": "function",
        "arguments": arguments,
        "function": {"name": "execute_sql_draft", "arguments": arguments},
    }


def data_answer_projection(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """把 DataAgent 已验证答案投影到 Response 元数据，供前端与审计直接消费。"""

    if tool_name != "execute_sql_draft":
        return {}
    nested_result = result.get("result")
    payload = nested_result if isinstance(nested_result, dict) else result
    summary = payload.get("execution_summary")
    if not isinstance(summary, dict):
        return {}
    return {
        "data_agent_run_id": summary.get("data_agent_run_id"),
        "state": summary.get("state"),
        "answer": summary.get("answer"),
        "answer_citations": list(summary.get("answer_citations") or []),
        "answer_metadata": dict(summary.get("answer_metadata") or {}),
        "learning": dict(summary.get("learning") or {}),
        "preflight": dict(summary.get("preflight") or {}),
        "result_validation": dict(summary.get("result_validation") or {}),
        "warnings": list(summary.get("warnings") or []),
    }
