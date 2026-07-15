from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    AssistantProfile,
    ChatSession,
    Project,
    ResponseItem,
    ResponseRecord,
    UserCustomInstruction,
    UserMemory,
)


@dataclass
class AssembledContext:
    messages: list[dict[str, Any]]
    memory_ids: list[str]
    project_id: str | None
    assistant_profile_id: str | None


class ContextAssembler:
    """Build model context from one canonical Response branch.

    Legacy chat rows are migration inputs, not online conversation state.
    """

    def __init__(self, *, max_history_items: int = 80, max_chars: int = 120_000):
        self.max_history_items = max_history_items
        self.max_chars = max_chars

    async def assemble(
        self,
        db: AsyncSession,
        *,
        response: ResponseRecord,
        user_query: str,
        request_payload: dict[str, Any],
    ) -> AssembledContext:
        session = await db.get(ChatSession, response.conversation_id)
        extension = dict(request_payload.get("opentrace") or {})
        project_id = str(extension.get("project_id") or getattr(session, "project_id", None) or "") or None
        profile_id = str(extension.get("assistant_profile_id") or getattr(session, "assistant_profile_id", None) or "") or None

        system_blocks = [
            "你是 OpenTrace 主助手。你负责统筹工具和专家能力，并只输出经过证据检查的最终回答。"
            "不要输出隐藏思维链；可以输出简洁、可核验的推理摘要。",
            (
                "租户与工作区边界：只能使用当前租户和工作区中已授权的数据与工具。"
                f" tenant={response.tenant_id}; workspace={response.workspace_id}。"
            ),
        ]
        tenant_policy = dict((response.response_metadata or {}).get("tenant_policy") or {})
        if tenant_policy:
            system_blocks.append("租户策略：\n" + json.dumps(tenant_policy, ensure_ascii=False, sort_keys=True))

        # Precedence is encoded by block order: platform/tenant, project,
        # profile/custom instructions, conversation/turn instructions, input.
        if project_id:
            project = await db.scalar(
                select(Project).where(
                    Project.id == project_id,
                    Project.user_id == response.user_id,
                    Project.tenant_id == response.tenant_id,
                    Project.workspace_id == response.workspace_id,
                )
            )
            if project and project.instructions.strip():
                system_blocks.append("Project 指令：\n" + project.instructions.strip())
            if project and not profile_id:
                profile_id = project.assistant_profile_id

        if profile_id:
            profile = await db.scalar(
                select(AssistantProfile).where(
                    AssistantProfile.id == profile_id,
                    AssistantProfile.user_id == response.user_id,
                    AssistantProfile.tenant_id == response.tenant_id,
                    AssistantProfile.workspace_id == response.workspace_id,
                )
            )
            if profile:
                personality = {
                    "friendly": "语气友好、自然，但保持清晰和诚实。",
                    "pragmatic": "直接给出结论和可执行内容，避免不必要铺垫。",
                    "none": "使用中性、清晰的表达。",
                }.get(profile.personality, "")
                system_blocks.append("助手角色：\n" + "\n".join(x for x in (personality, profile.instructions.strip()) if x))

        custom = await db.scalar(
            select(UserCustomInstruction).where(
                UserCustomInstruction.user_id == response.user_id,
                UserCustomInstruction.tenant_id == response.tenant_id,
                UserCustomInstruction.workspace_id == response.workspace_id,
                UserCustomInstruction.enabled.is_(True),
            )
        )
        if custom:
            if custom.about_user.strip():
                system_blocks.append("用户提供的背景：\n" + custom.about_user.strip())
            if custom.response_style.strip():
                system_blocks.append("用户偏好的回答方式：\n" + custom.response_style.strip())

        if session and session.conversation_instructions and session.conversation_instructions.strip():
            system_blocks.append("会话指令：\n" + session.conversation_instructions.strip()[:8000])
        instructions = request_payload.get("instructions")
        if isinstance(instructions, str) and instructions.strip():
            system_blocks.append("当前回合指令：\n" + instructions.strip()[:8000])

        memory_mode = str(extension.get("memory_mode") or request_payload.get("memory_mode") or "enabled")
        memory_ids: list[str] = []
        if memory_mode == "enabled" and not bool(getattr(session, "is_temporary", False)):
            now = datetime.now(UTC)
            memories = (
                await db.execute(
                    select(UserMemory)
                    .where(
                        UserMemory.user_id == response.user_id,
                        UserMemory.tenant_id == response.tenant_id,
                        UserMemory.workspace_id == response.workspace_id,
                        UserMemory.enabled.is_(True),
                        UserMemory.status == "active",
                        (UserMemory.expires_at.is_(None) | (UserMemory.expires_at > now)),
                        (UserMemory.scope_type == "user")
                        | ((UserMemory.scope_type == "project") & (UserMemory.scope_id == project_id))
                        | ((UserMemory.scope_type == "conversation") & (UserMemory.scope_id == response.conversation_id)),
                    )
                    .order_by(UserMemory.pinned.desc(), UserMemory.salience.desc(), UserMemory.updated_at.desc())
                    .limit(24)
                )
            ).scalars().all()
            if memories:
                memory_ids = [item.id for item in memories]
                system_blocks.append(
                    "可用于个性化的已确认记忆（若与当前消息冲突，以当前消息为准）：\n"
                    + "\n".join(f"- {item.content}" for item in memories)
                )

        history = await self._active_branch_items(db, response)
        messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(system_blocks)}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_query})
        return AssembledContext(
            messages=self._trim(messages),
            memory_ids=memory_ids,
            project_id=project_id,
            assistant_profile_id=profile_id,
        )

    async def _active_branch_items(self, db: AsyncSession, response: ResponseRecord) -> list[dict[str, Any]]:
        chain: list[str] = []
        seen: set[str] = set()
        current_id = response.parent_response_id
        while current_id and current_id not in seen and len(chain) < self.max_history_items:
            seen.add(current_id)
            row = await db.get(ResponseRecord, current_id)
            if row is None or row.conversation_id != response.conversation_id:
                break
            chain.append(row.id)
            current_id = row.parent_response_id
        if not chain:
            return []
        ordered_ids = list(reversed(chain))
        rows = list((
            await db.execute(
                select(ResponseItem)
                .where(ResponseItem.response_id.in_(ordered_ids))
                .order_by(ResponseItem.created_at, ResponseItem.sequence_number)
            )
        ).scalars().all())
        order = {response_id: index for index, response_id in enumerate(ordered_ids)}
        rows.sort(key=lambda item: (order.get(item.response_id, 999999), item.sequence_number))
        last_summary = next(
            (index for index in range(len(rows) - 1, -1, -1) if rows[index].item_type == "conversation_summary"),
            None,
        )
        if last_summary is not None:
            rows = rows[last_summary:]
        result: list[dict[str, Any]] = []
        for item in rows:
            if item.item_type in {"input_message", "message", "conversation_summary"} and item.role in {"user", "assistant", "system", "developer"}:
                if item.content:
                    result.append({"role": item.role, "content": item.content})
            elif item.item_type == "function_call_output":
                result.append({
                    "role": "tool",
                    "name": str((item.payload or {}).get("name") or "tool"),
                    "tool_call_id": str((item.payload or {}).get("call_id") or item.id),
                    "content": item.content or json.dumps(item.payload or {}, ensure_ascii=False),
                })
        return result[-self.max_history_items :]

    def _trim(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if sum(len(str(item.get("content") or "")) for item in messages) <= self.max_chars:
            return messages
        system, rest = messages[0], messages[1:]
        kept: list[dict[str, Any]] = []
        budget = max(0, self.max_chars - len(str(system.get("content") or "")))
        for item in reversed(rest):
            size = len(str(item.get("content") or ""))
            if kept and size > budget:
                break
            kept.append(item)
            budget -= size
        return [system, *reversed(kept)]
