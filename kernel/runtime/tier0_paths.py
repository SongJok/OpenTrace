"""Tier-0 fast paths — manifest-backed metadata, governance envelope, SQL retrieval.

Kernel SSOT for tier0 semantics. Gateway may inject ``data_query_fn`` for forced DB queries.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.observability.logger import get_logger
from infra.storage.models import TraceLog
from kernel.agent_runtime.manifest import get_manifest
from kernel.runtime.fast_path_metadata import build_fast_path_governance_envelope

logger = get_logger(__name__)

SQL_RETRIEVAL_KEYWORDS = (
    "sql语句是什么",
    "sql是什么",
    "执行的sql",
    "刚才的sql",
    "上一步的sql",
    "之前sql",
    "sql查询是什么",
    "query sql",
    "what sql",
    "生成的sql",
    "sql代码是什么",
    "查询sql",
    "本次查询的sql",
)


def is_sql_retrieval_intent(query: str) -> bool:
    q = query.strip().lower()
    if "sql" not in q:
        return False
    return any(kw in q for kw in SQL_RETRIEVAL_KEYWORDS)


async def get_previous_turn_sql(db: AsyncSession, session_id: str) -> str | None:
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at.desc())
            .limit(30)
        )
        logs = res.scalars().all()
        for log in logs:
            if not log.execution_graph_json:
                continue
            try:
                graph = json.loads(log.execution_graph_json)
                if not isinstance(graph, dict):
                    continue
                route = graph.get("route", "")
                if route == "sql_retrieval":
                    continue
                if log.query and is_sql_retrieval_intent(log.query):
                    continue
                if route in {"database_direct", "data_query", "database_fallback", "tier0_data_query"}:
                    sql = graph.get("sql")
                    if sql:
                        return str(sql)
                nodes = graph.get("nodes", [])
                if isinstance(nodes, list):
                    for node in nodes:
                        if not isinstance(node, dict) or node.get("status") != "SUCCESS":
                            continue
                        metadata = node.get("metadata") or {}
                        if metadata.get("agent_type") == "data":
                            output = node.get("output") or {}
                            sql = output.get("sql")
                            if sql:
                                return str(sql)
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as exc:
        logger.warning("tier0_sql_history_failed", error=str(exc))
    return None


def tier0_governance_envelope(
    *,
    route: str,
    capability_type: str,
    registry_agent: str,
    request_id: str,
    session_id: str,
    tier: str = "tier0",
) -> dict[str, Any]:
    return build_fast_path_governance_envelope(
        route=route,
        capability_type=capability_type,
        registry_agent=registry_agent,
        request_id=request_id,
        session_id=session_id,
        tier=tier,
        extra={"tier0_fast_path": True},
    )


def _record_tier0_compliance_audit(
    *,
    meta: dict[str, Any],
    session_id: str,
    user_id: str = "",
    tenant_id: str = "default",
    success: bool = True,
    route: str = "",
) -> None:
    try:
        import asyncio

        from kernel.governance.compliance_audit_store import record_compliance_event

        payload = {
            "route": route or meta.get("route"),
            "capability_type": meta.get("capability_type"),
            "registry_agent": meta.get("registry_agent"),
            "trace_id": meta.get("trace_id"),
        }
        coro = record_compliance_event(
            tenant_id=str(tenant_id or "default"),
            session_id=session_id,
            user_id=user_id,
            frameworks=["tier0_data"],
            violations=[] if success else ["tier0_execution_failed"],
            allowed=success,
            payload=payload,
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.warning("tier0_compliance_audit_skipped", error=str(exc))


@dataclass
class Tier0SyncOutcome:
    handled: bool
    content: str = ""
    decision_type: str = ""
    validation_score: float = 1.0
    execution_graph: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    state_patch: dict[str, Any] = field(default_factory=dict)


async def run_sql_retrieval_tier0(
    *,
    query: str,
    session_id: str,
    request_id: str,
    db: AsyncSession,
) -> Tier0SyncOutcome | None:
    if not is_sql_retrieval_intent(query):
        return None
    prev_sql = await get_previous_turn_sql(db, session_id)
    if not prev_sql:
        return None
    content = f"上一轮查询执行的 SQL 如下：\n\n```sql\n{prev_sql}\n```"
    cap, reg = get_manifest().resolve_capability_alias("data_query")
    meta = tier0_governance_envelope(
        route="sql_retrieval",
        capability_type=cap,
        registry_agent=reg,
        request_id=request_id,
        session_id=session_id,
    )
    exec_graph = {
        "route": "sql_retrieval",
        "sql": prev_sql,
        "capability_type": cap,
        "agent_type": reg,
        "governance": meta,
        "runtime_gateway_tier0": True,
    }
    state_patch = {
        "last_user_goal": query,
        "last_assistant_summary": content[:300],
        "last_plan": {"subtasks": [], "merge_strategy": "direct", "max_parallel": 0},
        "last_results": [{"agent_type": reg, "status": "success", "content": content[:300]}],
    }
    _record_tier0_compliance_audit(
        meta=meta,
        session_id=session_id,
        success=True,
        route="sql_retrieval",
    )
    return Tier0SyncOutcome(
        handled=True,
        content=content,
        decision_type="sql_retrieval",
        validation_score=1.0,
        execution_graph=exec_graph,
        metadata=meta,
        state_patch=state_patch,
    )


async def run_database_direct_tier0(
    *,
    query: str,
    data_source_id: str,
    session_id: str,
    request_id: str,
    current_user: Any,
    db: AsyncSession,
    data_query_fn: Callable[..., Any],
    data_query_request_factory: Callable[..., Any],
) -> Tier0SyncOutcome | None:
    """Forced database query; ``data_query_request_factory`` builds the router request DTO."""
    cap, reg = get_manifest().resolve_capability_alias("data_query")
    try:
        direct = await data_query_fn(
            data_query_request_factory(
                question=query,
                data_source_id=str(data_source_id),
                dry_run=False,
                sql=None,
            ),
            current_user=current_user,
            db=db,
        )
    except Exception as exc:
        logger.warning("tier0_database_direct_failed", error=str(exc))
        return None

    direct_sql = direct.get("sql")
    direct_rows = direct.get("rows", [])
    direct_summary = str(direct.get("summary") or direct_sql or direct_rows or "查询完成")
    if not direct_rows and "0 行" in direct_summary:
        direct_summary = (
            f"{direct_summary}\n\n"
            f"可能原因：数据源中不存在与「{query}」相关的表或字段，或查询条件未匹配到数据。\n"
            "建议：\n"
            "- 在「数据源」页面检查已连接的表和结构。\n"
            "- 尝试使用更通用的查询条件，或指定具体的表名。"
        )
    meta = tier0_governance_envelope(
        route="tier0_data_query",
        capability_type=cap,
        registry_agent=reg,
        request_id=request_id,
        session_id=session_id,
    )
    exec_graph = {
        "route": "tier0_data_query",
        "legacy_route": "database_direct",
        "data_source_id": data_source_id,
        "sql": direct_sql,
        "rows": (direct_rows or [])[:20],
        "capability_type": cap,
        "agent_type": reg,
        "governance": meta,
        "runtime_gateway_tier0": True,
    }
    state_patch = {
        "last_user_goal": query,
        "last_assistant_summary": direct_summary[:300],
        "last_plan": {
            "subtasks": [
                {
                    "agent_type": reg,
                    "query": query,
                    "params": {"data_source_id": data_source_id},
                }
            ],
            "merge_strategy": "direct",
            "max_parallel": 1,
        },
        "last_results": [
            {"agent_type": reg, "status": "success", "content": direct_summary[:300]}
        ],
    }
    uid = str(getattr(current_user, "id", "") or "")
    tid = str(getattr(current_user, "tenant_id", None) or "default")
    _record_tier0_compliance_audit(
        meta=meta,
        session_id=session_id,
        user_id=uid,
        tenant_id=tid,
        success=True,
        route="tier0_data_query",
    )
    return Tier0SyncOutcome(
        handled=True,
        content=direct_summary,
        decision_type="database_direct",
        validation_score=0.9,
        execution_graph=exec_graph,
        metadata=meta,
        state_patch=state_patch,
    )


def sse_sql_retrieval_events(content: str, exec_graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "reasoning_step",
            "data": {
                "id": "sql_retrieval",
                "stage": "REASON",
                "content": "从上一轮查询中获取 SQL 语句 (tier0)",
                "node_id": "node_sql_retrieval",
                "status": "done",
            },
        },
        {
            "type": "final_answer",
            "data": {
                "content": content,
                "execution_graph": exec_graph,
                "citations": [],
                "annotations": [],
                "state_patch": None,
                "result_refs": [],
                "metadata": exec_graph.get("governance") or {},
            },
        },
    ]


def sse_database_direct_events(
    query: str,
    summary: str,
    exec_graph: dict[str, Any],
    *,
    registry_agent: str,
) -> list[dict[str, Any]]:
    return [
        {
            "type": "reasoning_step",
            "data": {
                "id": "data_detect",
                "stage": "REASON",
                "content": "Tier-0 数据查询 (manifest data_query)",
                "node_id": "node_data",
                "status": "done",
            },
        },
        {
            "type": "dag_node_start",
            "data": {"node_id": "data_0", "agent_type": registry_agent, "depends_on": []},
        },
        {
            "type": "agent_start",
            "data": {"agent_type": registry_agent, "task_id": "data_0", "query": query},
        },
        {
            "type": "dag_node_complete",
            "data": {
                "node_id": "data_0",
                "agent_type": registry_agent,
                "status": "success",
                "preview": str(summary)[:200],
            },
        },
        {
            "type": "agent_complete",
            "data": {
                "agent_type": registry_agent,
                "task_id": "data_0",
                "status": "success",
                "preview": str(summary)[:200],
            },
        },
        {
            "type": "final_answer",
            "data": {
                "content": summary,
                "execution_graph": exec_graph,
                "citations": [],
                "annotations": [],
                "state_patch": None,
                "result_refs": [],
                "metadata": exec_graph.get("governance") or {},
            },
        },
    ]


async def stream_tier0_events(
    events: list[dict[str, Any]],
    *,
    chunk_text: bool = True,
    chunk_size: int = 24,
) -> AsyncIterator[dict[str, Any]]:
    import asyncio

    for event in events:
        if event.get("type") != "final_answer" or not chunk_text:
            yield event
            continue
        data = dict(event.get("data") or {})
        content = str(data.pop("content", ""))
        for i in range(0, len(content), chunk_size):
            yield {"type": "delta", "data": {"text": content[i : i + chunk_size]}}
            await asyncio.sleep(0)
        yield {"type": "final_answer", "data": {**data, "content": content}}