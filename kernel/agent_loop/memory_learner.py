from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    ChatSession,
    MemoryCandidate,
    MemoryEvidence,
    ResponseItem,
    ResponseRecord,
    UserMemory,
    UserMemorySettings,
)
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|密码|密钥)\s*[:=：]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class MemoryLearner:
    """Evidence-backed automatic memory candidate extraction."""

    async def learn(self, db: AsyncSession, *, response: ResponseRecord) -> list[str]:
        session = await db.get(ChatSession, response.conversation_id)
        if session is None or session.is_temporary:
            return []
        extension = dict((response.request_payload or {}).get("opentrace") or {})
        mode = str(extension.get("memory_mode") or (response.request_payload or {}).get("memory_mode") or "enabled")
        if mode != "enabled":
            return []
        settings_row = await db.scalar(
            select(UserMemorySettings).where(UserMemorySettings.user_id == response.user_id)
        )
        if settings_row and not settings_row.memory_learning_enabled:
            return []
        input_item = await db.scalar(
            select(ResponseItem)
            .where(ResponseItem.response_id == response.id, ResponseItem.item_type == "input_message")
            .order_by(ResponseItem.sequence_number)
        )
        text = str(input_item.content or "") if input_item else ""
        if not text or self._contains_secret(text):
            return []
        candidates = await self._extract(text)
        created: list[str] = []
        for candidate in candidates[:8]:
            content = str(candidate.get("content") or "").strip()[:2000]
            if not content or self._contains_secret(content) or bool(candidate.get("sensitive", False)):
                continue
            confidence = min(1.0, max(0.0, float(candidate.get("confidence") or 0.0)))
            explicit = bool(candidate.get("explicit", False))
            status = "active" if explicit or confidence >= 0.85 else "pending" if confidence >= 0.60 else "rejected"
            scope_type = str(candidate.get("scope_type") or ("project" if session.project_id else "user"))
            if scope_type not in {"user", "project", "conversation"}:
                scope_type = "user"
            scope_id = session.project_id if scope_type == "project" else session.id if scope_type == "conversation" else None
            memory_key = re.sub(r"[^a-z0-9_.:-]+", "_", str(candidate.get("key") or "").lower()).strip("_")[:128] or None
            conflict = await self._find_conflict(
                db, response.user_id, response.tenant_id, response.workspace_id,
                scope_type, scope_id, memory_key, content
            )
            if conflict and conflict.content != content and not explicit:
                status = "pending"
            row = MemoryCandidate(
                id=str(uuid.uuid4()), user_id=response.user_id, response_id=response.id,
                tenant_id=response.tenant_id, workspace_id=response.workspace_id,
                scope_type=scope_type, scope_id=scope_id,
                kind=str(candidate.get("kind") or "fact")[:30], memory_key=memory_key, content=content,
                confidence=confidence, salience=min(1.0, max(0.0, float(candidate.get("salience") or 0.5))),
                status=status,
                rejection_reason="low_confidence" if status == "rejected" else None,
            )
            db.add(row)
            await db.flush()
            evidence = MemoryEvidence(
                id=str(uuid.uuid4()), candidate_id=row.id, response_id=response.id,
                item_id=input_item.id if input_item else None, excerpt=text[:500],
            )
            db.add(evidence)
            if status == "active" and not await self._has_duplicate(
                db, response.user_id, response.tenant_id, response.workspace_id,
                scope_type, scope_id, content
            ):
                memory = UserMemory(
                    id=str(uuid.uuid4()), user_id=response.user_id, memory_type="semantic",
                    tenant_id=response.tenant_id, workspace_id=response.workspace_id,
                    kind=row.kind, title=content[:80], content=content, enabled=True,
                    memory_key=memory_key,
                    pinned=explicit, score=row.salience, scope_type=scope_type, scope_id=scope_id,
                    status="active", confidence=confidence, salience=row.salience,
                    source_response_id=response.id,
                    supersedes_id=conflict.id if conflict and explicit else None,
                )
                db.add(memory)
                await db.flush()
                if conflict and explicit:
                    conflict.status = "superseded"
                    conflict.enabled = False
                evidence.memory_id = memory.id
                created.append(memory.id)
        await db.commit()
        return created

    async def _extract(self, text: str) -> list[dict[str, Any]]:
        prompt = (
            "从用户消息中提取将来多轮对话中仍有用的稳定记忆。只输出 JSON 数组。"
            "每项字段为 content, key(稳定的snake_case主题键), kind(profile|preference|workflow|fact|episodic), confidence(0-1), "
            "salience(0-1), explicit(boolean), sensitive(boolean), scope_type(user|project)。"
            "scope_type 可为 user|project|conversation。不要记录一次性请求、推测、健康/财务/身份证等敏感信息、认证信息或秘密。"
        )
        try:
            result = await get_model_gateway().complete(
                [LLMMessage(role="system", content=prompt), LLMMessage(role="user", content=text)],
                role=LLMRole.PLANNING,
                fallback_roles=[],
                max_output_tokens=1000,
                store=False,
            )
            raw = str(result.content or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
            parsed = json.loads(raw)
            return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
        except Exception:
            return []

    @staticmethod
    def _contains_secret(text: str) -> bool:
        return any(pattern.search(text) for pattern in _SECRET_PATTERNS)

    @staticmethod
    async def _has_duplicate(
        db: AsyncSession, user_id: str, tenant_id: str, workspace_id: str,
        scope_type: str, scope_id: str | None, content: str
    ) -> bool:
        row = await db.scalar(
            select(UserMemory.id).where(
                UserMemory.user_id == user_id,
                UserMemory.tenant_id == tenant_id,
                UserMemory.workspace_id == workspace_id,
                UserMemory.scope_type == scope_type,
                UserMemory.scope_id == scope_id,
                UserMemory.content == content,
                UserMemory.status == "active",
            )
        )
        return row is not None

    @staticmethod
    async def _find_conflict(
        db: AsyncSession,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        scope_type: str,
        scope_id: str | None,
        memory_key: str | None,
        content: str,
    ) -> UserMemory | None:
        if not memory_key:
            return None
        return await db.scalar(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.tenant_id == tenant_id,
                UserMemory.workspace_id == workspace_id,
                UserMemory.scope_type == scope_type,
                UserMemory.scope_id == scope_id,
                UserMemory.memory_key == memory_key,
                UserMemory.status == "active",
                UserMemory.content != content,
            )
            .order_by(UserMemory.updated_at.desc())
        )
