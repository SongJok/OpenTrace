"""Canonical model-first turn preparation for the Responses API.

This module deliberately does not call the legacy chat router.  It builds the
same minimum request context that every user-facing response needs, then hands
execution to ``CognitiveKernel``.  The response router owns persistence of
Response records/items/events around this coordinator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope
from infra.errors import AppException, ErrorCodes
from infra.observability.request_context import set_user_session_context
from infra.storage.models import ChatSession, Message, TraceLog, User, UserCustomInstruction
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
    history = await _load_history(db, conversation_id)
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
        "memory_mode": getattr(request, "memory_mode", "enabled"),
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
        "clarify_context": getattr(request, "clarify_context", None),
        "clarify_question_id": getattr(request, "clarify_question_id", None),
        "attachment_ids": list(getattr(request, "attachment_ids", None) or []),
        "knowledge_control": dict(getattr(request, "knowledge", None) or {}),
        "custom_instruction_block": custom_instruction_block,
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
