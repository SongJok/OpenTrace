"""Canonical model-first turn preparation for the Responses API.

This module deliberately does not call the legacy chat router.  It builds the
same minimum request context that every user-facing response needs, then hands
execution to ``CognitiveKernel``.  The response router owns persistence of
Response records/items/events around this coordinator.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope
from infra.errors import AppException, ErrorCodes
from infra.observability.request_context import set_user_session_context
from infra.storage.models import (
    ChatSession,
    Message,
    ResponseItem,
    ResponseRecord,
    TraceLog,
    User,
    UserCustomInstruction,
    UserMemory,
    UserMemorySettings,
)
from kernel.cognitive_kernel import CognitiveKernel, KernelRequest, KernelResponse
from kernel.protocol.events import trace_context_for_request


@dataclass
class PreparedResponseTurn:
    conversation_id: str
    request_id: str
    kernel_request: KernelRequest
    knowledge_result: Any | None = None


class ModelAnswerRequiredError(RuntimeError):
    """Raised when a normal response did not invoke the primary model."""


async def _ensure_conversation(
    db: AsyncSession,
    *,
    conversation_id: str | None,
    user: User,
    tenant_metadata: dict[str, Any],
) -> str:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    org_id = str(tenant_metadata.get("org_id") or "default")
    if conversation_id:
        existing = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == conversation_id,
                ChatSession.user_id == user.id,
                ChatSession.tenant_id == tenant_id,
                ChatSession.workspace_id == workspace_id,
            )
        )
        if existing is not None:
            return existing.id
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation 不存在或无权限")

    session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="New conversation",
        display_title="New conversation",
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
    )
    db.add(session)
    await db.commit()
    return session.id


async def _load_history(db: AsyncSession, conversation_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
    # Responses is the canonical store for new conversations.  Follow the
    # active response chain first so retries/branches never leak sibling turns
    # into the prompt for the next answer.
    session = await db.get(ChatSession, conversation_id)
    active_response_id = getattr(session, "active_response_id", None) if session else None
    if active_response_id:
        chain: list[ResponseRecord] = []
        seen: set[str] = set()
        current_id = str(active_response_id)
        while current_id and current_id not in seen and len(chain) < limit:
            seen.add(current_id)
            record = await db.get(ResponseRecord, current_id)
            if record is None or record.conversation_id != conversation_id:
                break
            chain.append(record)
            current_id = str(record.parent_response_id or "")
        if chain:
            response_ids = [record.id for record in reversed(chain)]
            rows = (
                await db.execute(
                    select(ResponseItem)
                    .where(ResponseItem.response_id.in_(response_ids))
                    .order_by(ResponseItem.response_id, ResponseItem.sequence_number)
                )
            ).scalars().all()
            by_response: dict[str, list[ResponseItem]] = {}
            for item in rows:
                by_response.setdefault(item.response_id, []).append(item)
            out: list[dict[str, Any]] = []
            for response_id in response_ids:
                for item in by_response.get(response_id, []):
                    if item.role not in {"user", "assistant", "system", "developer", "tool"}:
                        continue
                    content = str(item.content or "").strip()
                    if not content:
                        continue
                    entry: dict[str, Any] = {"role": item.role, "content": content}
                    payload = item.payload if isinstance(item.payload, dict) else {}
                    if item.item_type == "function_call_output":
                        entry["tool_call_id"] = payload.get("call_id") or item.id
                    out.append(entry)
            if out:
                try:
                    from kernel.token_counter import truncate_messages

                    return truncate_messages(out, max_tokens=4096, strategy="keep_system_recent", keep_recent_turns=4)
                except Exception:
                    return out

    messages = (
        await db.execute(
            select(Message)
            .where(Message.session_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit * 2)
        )
    ).scalars().all()
    if messages:
        out: list[dict[str, Any]] = []
        for message in reversed(messages):
            item: dict[str, Any] = {"role": message.role, "content": message.content or ""}
            if message.tool_calls:
                item["tool_calls"] = message.tool_calls
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            if message.name:
                item["name"] = message.name
            out.append(item)
        try:
            from kernel.token_counter import truncate_messages

            return truncate_messages(out, max_tokens=4096, strategy="keep_system_recent", keep_recent_turns=4)
        except Exception:
            return out

    # The canonical Responses API persists typed ResponseItems rather than
    # legacy Message rows.  Read those items as the authoritative history so
    # a second turn in the same conversation receives the first turn's input
    # and assistant answer.  This fallback is intentionally below Message
    # loading to preserve compatibility with older /api/v1/chat sessions.
    response_items = (
        await db.execute(
            select(ResponseItem, ResponseRecord.created_at)
            .join(ResponseRecord, ResponseRecord.id == ResponseItem.response_id)
            .where(ResponseRecord.conversation_id == conversation_id)
            .order_by(ResponseRecord.created_at.asc(), ResponseItem.sequence_number.asc())
            .limit(limit * 2)
        )
    ).all()
    if response_items:
        out = []
        for item, _created_at in response_items:
            if item.role not in {"user", "assistant", "system", "developer", "tool"}:
                continue
            content = str(item.content or "").strip()
            if not content:
                continue
            entry: dict[str, Any] = {"role": item.role, "content": content}
            payload = item.payload if isinstance(item.payload, dict) else {}
            if item.item_type == "function_call_output":
                entry["tool_call_id"] = payload.get("call_id") or item.id
            out.append(entry)
        if out:
            try:
                from kernel.token_counter import truncate_messages

                return truncate_messages(out, max_tokens=4096, strategy="keep_system_recent", keep_recent_turns=4)
            except Exception:
                return out

    traces = (
        await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == conversation_id)
            .order_by(TraceLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    out = []
    for trace in reversed(traces):
        if trace.query:
            out.append({"role": "user", "content": trace.query})
        if trace.response:
            out.append({"role": "assistant", "content": trace.response})
    try:
        from kernel.token_counter import truncate_messages

        return truncate_messages(out, max_tokens=4096, strategy="keep_system_recent", keep_recent_turns=4)
    except Exception:
        return out


def extract_profile_facts(query: str) -> list[tuple[str, str]]:
    """Extract high-confidence, user-authored profile facts from a turn.

    This deliberately handles only explicit identity statements.  It avoids
    turning arbitrary model output or ambiguous numbers into durable memory,
    while covering natural Chinese forms such as ``我姓宋`` and ``今天88岁``.
    """
    text = str(query or "").strip()
    facts: list[tuple[str, str]] = []
    surname = re.search(r"(?:我姓|我的姓是)\s*([\u4e00-\u9fff])", text)
    if surname:
        facts.append(("姓氏", f"用户姓{surname.group(1)}"))
    age = re.search(r"(?:我(?:今年|现在|今天)?|今年|现在|今天)\s*(\d{1,3})\s*岁", text)
    if age:
        years = int(age.group(1))
        if 0 < years < 130:
            facts.append(("年龄", f"用户今年{years}岁"))
    return facts


def extract_explicit_memory_facts(query: str) -> list[tuple[str, str, str, bool]]:
    """Extract durable facts that the user explicitly asked the assistant to retain.

    Profile statements are intentionally narrow and can be remembered without a
    cue.  Everything else requires an explicit "remember/save" instruction so
    ordinary chat content is never silently promoted into long-term memory.
    """
    text = str(query or "").strip()
    facts: list[tuple[str, str, str, bool]] = [
        (title, content, "profile", True) for title, content in extract_profile_facts(text)
    ]

    patterns = (
        ("姓名", r"(?:我叫|我的名字是)\s*([^，。！？,.!?:：\s]{1,32})"),
        ("所在地", r"(?:我住在|我在)\s*([^，。！？,.!?:：]{2,48})(?:工作|生活|居住)?"),
        ("职业", r"(?:我的职业是|我是一名)\s*([^，。！？,.!?:：]{2,48})"),
    )
    for title, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value:
                facts.append((title, f"用户的{title}是{value}", "profile", True))

    cue = re.search(
        r"(?:请|帮我)?(?:记住|记下|记录(?:一下|下来)?|保存(?:一下|下来)?|别忘了)\s*[，,:：]?\s*(.+)",
        text,
    )
    if cue:
        content = cue.group(1).strip().rstrip("。！？，,.!?")[:500]
        if len(content) >= 2:
            kind = "preference" if any(word in content for word in ("喜欢", "偏好", "希望", "习惯", "回答")) else "fact"
            digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
            facts.append((f"明确记忆-{digest}", content, kind, True))

    deduped: list[tuple[str, str, str, bool]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = (fact[0], fact[1])
        if key not in seen:
            deduped.append(fact)
            seen.add(key)
    return deduped


async def _persist_profile_facts(
    db: AsyncSession,
    *,
    user_id: str,
    query: str,
) -> list[tuple[str, str]]:
    """Upsert explicit profile facts in durable user-scoped memory."""
    settings_row = await db.scalar(
        select(UserMemorySettings).where(UserMemorySettings.user_id == user_id)
    )
    if settings_row is not None and not bool(settings_row.memory_learning_enabled):
        return []
    facts = extract_explicit_memory_facts(query)
    if not facts:
        return []
    changed = False
    for title, content, kind, pinned in facts:
        existing = await db.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.kind == kind,
                UserMemory.title == title,
            )
        )
        if existing is None:
            db.add(
                UserMemory(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    memory_type="semantic",
                    kind=kind,
                    title=title,
                    content=content,
                    tags_json=json.dumps([kind, "explicit"], ensure_ascii=False),
                    metadata_json=json.dumps({"source": "user_turn", "confidence": 1.0}, ensure_ascii=False),
                    enabled=True,
                    pinned=pinned,
                    score=1.0,
                    access_count=1,
                    last_accessed_at=datetime.now(UTC),
                )
            )
        else:
            existing.content = content
            existing.enabled = True
            existing.pinned = bool(existing.pinned or pinned)
            existing.score = max(float(existing.score or 0), 1.0)
            existing.access_count = int(existing.access_count or 0) + 1
            existing.last_accessed_at = datetime.now(UTC)
        changed = True
    if changed:
        await db.commit()
    return [(title, content) for title, content, _kind, _pinned in facts]


async def _load_profile_memory_context(
    db: AsyncSession,
    *,
    user_id: str,
    query: str,
    memory_mode: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Build a compact, deterministic memory block for the current turn."""
    if str(memory_mode or "enabled").lower() != "enabled":
        return "", []
    settings_row = await db.scalar(
        select(UserMemorySettings).where(UserMemorySettings.user_id == user_id)
    )
    if settings_row is not None and not bool(settings_row.memory_learning_enabled):
        return "", []
    rows = (
        await db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.enabled.is_(True),
                UserMemory.kind.in_(["profile", "preference", "project_fact", "fact"]),
            )
            .order_by(UserMemory.pinned.desc(), UserMemory.score.desc(), UserMemory.updated_at.desc())
            .limit(80)
        )
    ).scalars().all()
    if not rows:
        return "", []
    # Profiles and pinned memories are always available for identity and
    # preference questions.  Other explicit memories are ranked by lightweight
    # lexical overlap to keep the prompt bounded and relevant.
    query_chars = set(re.findall(r"[\w\u4e00-\u9fff]", str(query or "").lower()))

    def relevance(row: UserMemory) -> int:
        text = f"{row.title or ''} {row.content or ''}".lower()
        return len(query_chars.intersection(set(re.findall(r"[\w\u4e00-\u9fff]", text))))

    selected = sorted(
        rows,
        key=lambda row: (
            2 if row.kind == "profile" else 0,
            1 if row.pinned else 0,
            relevance(row),
            float(row.score or 0),
            row.updated_at.timestamp() if row.updated_at else 0,
        ),
        reverse=True,
    )[:24]
    lines = [
        "以下是用户明确提供并允许用于后续对话的长期记忆。涉及身份、偏好、项目背景或相关事实时必须使用；不要臆造、覆盖或向无关对象泄露："
    ]
    hits: list[dict[str, Any]] = []
    for row in selected:
        content = str(row.content or "").strip()
        if not content:
            continue
        lines.append(f"- {content[:500]}")
        hits.append({"id": row.id, "title": row.title or "", "kind": row.kind, "pinned": bool(row.pinned)})
        row.access_count = int(row.access_count or 0) + 1
        row.last_accessed_at = datetime.now(UTC)
    if hits:
        await db.commit()
    return ("\n".join(lines) if len(lines) > 1 else ""), hits


async def _load_custom_instructions(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_metadata: dict[str, Any],
) -> str:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    row = await db.scalar(
        select(UserCustomInstruction).where(
            UserCustomInstruction.user_id == user_id,
            UserCustomInstruction.tenant_id == tenant_id,
            UserCustomInstruction.workspace_id == workspace_id,
            UserCustomInstruction.enabled.is_(True),
        )
    )
    if row is None:
        return ""
    parts: list[str] = []
    if row.about_user.strip():
        parts.append(f"用户明确提供的背景信息：\n{row.about_user.strip()[:4000]}")
    if row.response_style.strip():
        parts.append(f"用户明确要求的回答风格：\n{row.response_style.strip()[:4000]}")
    return "\n\n".join(parts)


def _request_instruction_text(value: Any) -> str:
    """Normalize public ``instructions`` into a trusted system message."""
    if isinstance(value, str):
        return value.strip()[:8000]
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        role = getattr(item, "role", None) if not isinstance(item, dict) else item.get("role")
        content = getattr(item, "content", None) if not isinstance(item, dict) else item.get("content")
        if role not in {"system", "developer"}:
            continue
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
    return "\n\n".join(parts)[:8000]


async def prepare_response_turn(
    *,
    db: AsyncSession,
    user: User,
    tenant_metadata: dict[str, Any],
    query: str,
    request: Any,
    request_id: str,
) -> PreparedResponseTurn:
    """Validate and build a model-required KernelRequest for one response."""
    try:
        from safety.guardrails.guardrails import guardrails

        guard = guardrails.check_input(query)
        if not guard.allowed:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"Blocked: {guard.reason}")
    except AppException:
        raise
    except Exception as exc:
        raise AppException(
            ErrorCodes.UPSTREAM_UNAVAILABLE.code,
            message="安全检查暂时不可用，请稍后重试。",
        ) from exc

    conversation_id = await _ensure_conversation(
        db,
        conversation_id=getattr(request, "conversation_id", None),
        user=user,
        tenant_metadata=tenant_metadata,
    )
    set_user_session_context(user_id=user.id, session_id=conversation_id)
    memory_mode = str(getattr(request, "memory_mode", "enabled") or "enabled")
    if memory_mode == "enabled":
        # Persist explicit profile statements before loading context.  This
        # makes the current turn and every later turn observe the same durable
        # user fact, independent of process restarts or embedding quality.
        await _persist_profile_facts(db, user_id=user.id, query=query)
    history = await _load_history(db, conversation_id)
    if memory_mode == "enabled":
        # Backfill facts from turns that were created before the durable
        # profile extractor existed.  This makes upgrading an existing chat
        # seamless instead of requiring the user to repeat their biography.
        for history_item in history:
            if history_item.get("role") == "user":
                await _persist_profile_facts(
                    db,
                    user_id=user.id,
                    query=str(history_item.get("content") or ""),
                )
    profile_memory_block, durable_memory_hits = await _load_profile_memory_context(
        db,
        user_id=user.id,
        query=query,
        memory_mode=memory_mode,
    )
    if profile_memory_block:
        history = [{"role": "system", "content": profile_memory_block}, *history]
    custom_instruction_block = await _load_custom_instructions(
        db, user_id=user.id, tenant_metadata=tenant_metadata
    )
    request_instruction_block = _request_instruction_text(getattr(request, "instructions", None))
    if request_instruction_block:
        history = [{"role": "system", "content": request_instruction_block}, *history]

    try:
        from kernel.conversation_state import ConversationStateManager

        conversation_state = await ConversationStateManager().get_or_create(conversation_id)
    except Exception:
        conversation_state = None

    raw_input = getattr(request, "input", query)
    input_items = (
        [item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item) for item in raw_input]
        if isinstance(raw_input, list)
        else raw_input
    )
    modalities: list[str] = []
    if isinstance(input_items, list):
        for item in input_items:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, list):
                modalities.extend(str(part.get("type")) for part in content if isinstance(part, dict) and part.get("type"))

    metadata = {
        **tenant_metadata,
        "request_id": request_id,
        "model_required": True,
        "answer_policy": "primary_model",
        "memory_mode": memory_mode,
        "tool_choice": getattr(request, "tool_choice", "auto"),
        "requested_model": getattr(request, "model", None),
        "instructions": getattr(request, "instructions", None),
        "request_instruction_block": request_instruction_block,
        "tools": list(getattr(request, "tools", None) or []),
        "parallel_tool_calls": bool(getattr(request, "parallel_tool_calls", True)),
        "max_output_tokens": getattr(request, "max_output_tokens", None),
        "truncation": getattr(request, "truncation", "disabled"),
        "store": bool(getattr(request, "store", True)),
        "response_metadata": dict(getattr(request, "metadata", None) or {}),
        "response_text": dict(getattr(request, "text", None) or {}),
        "reasoning": dict(getattr(request, "reasoning", None) or {}),
        "graph_controls": dict(getattr(request, "graph_controls", None) or {}),
        "enabled_skills": list(getattr(request, "enabled_skills", None) or []),
        "disabled_skills": list(getattr(request, "disabled_skills", None) or []),
        "data_source_id": getattr(request, "data_source_id", None),
        "data_source_name": getattr(request, "data_source_name", None),
        "force_database": bool(getattr(request, "force_database", False)),
        "force_mode": getattr(request, "force_mode", None),
        "execution_profile": getattr(request, "execution_profile", "auto"),
        "execution_mode": getattr(request, "execution_mode", "auto"),
        "clarify_context": getattr(request, "clarify_context", None),
        "clarify_question_id": getattr(request, "clarify_question_id", None),
        "attachment_ids": list(getattr(request, "attachment_ids", None) or []),
        "knowledge_control": dict(getattr(request, "knowledge", None) or {}),
        "custom_instruction_block": custom_instruction_block,
        "profile_memory_context": profile_memory_block,
        "durable_memory_hits": durable_memory_hits,
        "history": history,
        "input_items": input_items,
        "input_modalities": sorted(set(modalities)),
    }
    knowledge_result = None
    knowledge_control = dict(getattr(request, "knowledge", None) or {})
    knowledge_action = str(knowledge_control.get("action") or "auto")
    if knowledge_action not in {"auto", "query", "ingest", "link", "lint", "merge", "evolve", "trace"}:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="knowledge.action 不受支持")
    if knowledge_action == "auto":
        from knowledge.chat_actions import infer_knowledge_action

        knowledge_action = infer_knowledge_action(query)
    if knowledge_action != "query":
        from gateway.api_gateway.resource_scope import normalized_tenant_scope
        from knowledge.chat_actions import perform_knowledge_action

        tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
        knowledge_result = await perform_knowledge_action(
            db,
            action=knowledge_action,
            user=user,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            attachment_ids=list(knowledge_control.get("attachment_ids") or getattr(request, "attachment_ids", None) or []),
            source_ids=list(knowledge_control.get("source_ids") or []),
            publish_policy=str(knowledge_control.get("publish_policy") or "review"),
            resolution=dict(knowledge_control.get("resolution") or {}),
            session_id=conversation_id,
        )
        await db.commit()

    return PreparedResponseTurn(
        conversation_id=conversation_id,
        request_id=request_id,
        kernel_request=KernelRequest(
            query=query,
            session_id=conversation_id,
            user_id=user.id,
            history=history,
            stream=bool(getattr(request, "stream", False)),
            web_enabled=bool(getattr(request, "web_enabled", False)),
            metadata=metadata,
            trace_ctx=trace_context_for_request(
                request_id, session_id=conversation_id, user_id=user.id
            ),
            conversation_state=conversation_state,
        ),
        knowledge_result=knowledge_result,
    )


async def execute_prepared_turn(prepared: PreparedResponseTurn) -> KernelResponse:
    """Run the canonical kernel once; final answers must be model-authored."""
    from model.model_gateway.gateway import capture_model_calls

    if prepared.knowledge_result is not None:
        operation = prepared.knowledge_result
        return KernelResponse(
            content=operation.message,
            session_id=prepared.conversation_id,
            route=f"knowledge_{operation.action}",
            validation_score=1.0,
            passed_validation=True,
            hallucination_risk=0.0,
            intent_category=f"knowledge_{operation.action}",
            intent_complexity="operation",
            total_latency_ms=0,
            metadata={
                "knowledge_operation": True,
                "knowledge_action": operation.to_dict(),
                "knowledge_operations": operation.operations,
                "confidence": 1.0 if operation.status in {"completed", "queued", "published"} else 0.5,
                "uncertainty": [],
            },
        )

    # Explicit Responses tools use one bounded, provider-neutral function loop.
    # Keeping this at the coordinator boundary means sync, background and
    # streaming transports all receive the same tool semantics.
    requested_tools = list((prepared.kernel_request.metadata or {}).get("tools") or [])
    if requested_tools:
        from kernel.runtime.turn_engine import ResponsesToolLoop
        from kernel.tools.function_calling.executor import get_tool_executor
        from model.llm_adapter.base import LLMMessage
        from model.model_gateway.gateway import LLMRole, get_model_gateway

        messages = [
            LLMMessage(role=str(item.get("role") or "user"), content=item.get("content") or "")
            for item in (prepared.kernel_request.history or [])
            if isinstance(item, dict)
        ]
        messages.append(LLMMessage(role="user", content=prepared.kernel_request.query))

        async def _complete(msgs, **kwargs):
            return await get_model_gateway().complete(
                msgs,
                role=LLMRole.QUERY,
                fallback_roles=[],
                tools=requested_tools,
                tool_choice=(prepared.kernel_request.metadata or {}).get("tool_choice", "auto"),
                parallel_tool_calls=bool((prepared.kernel_request.metadata or {}).get("parallel_tool_calls", True)),
                max_output_tokens=(prepared.kernel_request.metadata or {}).get("max_output_tokens"),
            )

        executor = get_tool_executor()
        # Bridge the unified capability registry into the Responses executor.
        # Handlers are still permission-checked by the registry's caller; this
        # only makes already-registered first-party tools callable by name.
        try:
            from kernel.runtime.capability import capability_registry
            for definition in requested_tools:
                name = str(definition.get("name") or definition.get("function", {}).get("name") or "")
                capability = capability_registry.get_tool(name) if name else None
                if capability is not None and executor.get_schema(name) is None:
                    executor.register_tool(name, capability.fn, description=capability.description,
                                           parameters=(definition.get("parameters") or definition.get("function", {}).get("parameters") or {"type": "object", "properties": {}}),
                                           required=list((definition.get("parameters") or definition.get("function", {}).get("parameters") or {}).get("required", [])))
        except Exception:
            # Registry discovery is optional; unknown tools receive a typed
            # failure result from ToolExecutor and the model can recover.
            pass

        with capture_model_calls() as calls:
            response, tool_log = await ResponsesToolLoop(
                _complete, executor, max_rounds=8
            ).run(
                messages,
                tools=requested_tools,
                parallel_tool_calls=bool((prepared.kernel_request.metadata or {}).get("parallel_tool_calls", True)),
                tool_choice=str((prepared.kernel_request.metadata or {}).get("tool_choice") or "auto"),
                max_output_tokens=(prepared.kernel_request.metadata or {}).get("max_output_tokens"),
            )
        response.metadata = {
            **dict(response.raw or {}),
            "model_required": True,
            "tool_calls": tool_log,
            "tool_call_count": len(tool_log),
            "model_call_count": len(calls),
            "model_calls": calls,
        }
        response.model = str(response.model or (calls[-1].get("model") if calls else "") or "")
        return KernelResponse(
            content=str(response.content or ""), session_id=prepared.conversation_id,
            route="responses_tools", model=response.model,
            metadata=response.metadata,
            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
        )

    with capture_model_calls() as calls:
        response = await CognitiveKernel().run(prepared.kernel_request)
    if not calls:
        raise ModelAnswerRequiredError("model_answer_required_but_no_model_call_recorded")
    response.metadata = dict(response.metadata or {})
    response.metadata.setdefault("model_required", True)
    response.metadata["model_call_count"] = len(calls)
    response.metadata["model_calls"] = calls
    response.metadata["model_call_id"] = calls[-1]["id"]
    response.model = str(response.model or calls[-1].get("model") or "")
    return response


async def stream_prepared_turn(prepared: PreparedResponseTurn):
    """Yield the canonical kernel stream without legacy SSE translation."""
    from model.model_gateway.gateway import capture_model_calls

    if prepared.knowledge_result is not None:
        operation = prepared.knowledge_result
        data = {
            "content": operation.message,
            "route": f"knowledge_{operation.action}",
            "knowledge_operation": True,
            "knowledge_action": operation.to_dict(),
            "knowledge_operations": operation.operations,
            "confidence": 1.0 if operation.status in {"completed", "queued", "published"} else 0.5,
            "uncertainty": [],
            "metadata": {
                "knowledge_operation": True,
                "knowledge_action": operation.to_dict(),
                "knowledge_operations": operation.operations,
                "confidence": 1.0 if operation.status in {"completed", "queued", "published"} else 0.5,
                "uncertainty": [],
            },
        }
        yield {"type": "answer.delta", "data": {"text": operation.message}}
        yield {"type": "answer.final", "data": data}
        return

    # The tool-enabled stream shares the exact same bounded Responses loop as
    # sync/background execution.  We surface tool progress as semantic events
    # and emit the final answer once synthesis completes; no progress text is
    # appended to the assistant message.
    requested_tools = list((prepared.kernel_request.metadata or {}).get("tools") or [])
    if requested_tools:
        result = await execute_prepared_turn(prepared)
        tool_log = list((result.metadata or {}).get("tool_calls") or [])
        for call in tool_log:
            yield {"type": "tool_call", "data": {"item_type": "function_call", **call}}
            yield {"type": "tool_result", "data": {"item_type": "function_call_output", **call}}
        yield {"type": "answer.delta", "data": {"text": str(result.content or "")}}
        yield {
            "type": "answer.final",
            "data": {
                "content": str(result.content or ""),
                "route": result.route,
                "model": result.model,
                "metadata": dict(result.metadata or {}),
            },
        }
        return

    with capture_model_calls() as calls:
        async for event in CognitiveKernel().stream(prepared.kernel_request):
            if event.get("type") == "final_answer":
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                if not calls:
                    raise ModelAnswerRequiredError("model_answer_required_but_no_model_call_recorded")
                data = dict(data)
                metadata = dict(data.get("metadata") or {})
                metadata.update(
                    {
                        "model_required": True,
                        "model_call_count": len(calls),
                        "model_calls": calls,
                        "model_call_id": calls[-1]["id"],
                    }
                )
                data["metadata"] = metadata
                event = {**event, "data": data}
            yield event
