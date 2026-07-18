from __future__ import annotations

import json
import re
import uuid
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    AssistantProfile,
    ChatSession,
    MemoryCandidate,
    MemoryEvidence,
    Project,
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
        project = await db.get(Project, session.project_id) if session.project_id else None
        profile_id = session.assistant_profile_id or (
            project.assistant_profile_id if project else None
        )
        profile = await db.get(AssistantProfile, profile_id) if profile_id else None
        memory_policy = dict(profile.memory_policy or {}) if profile else {}
        if memory_policy.get("enabled") is False or memory_policy.get("learn") is False:
            return []
        project_only = bool(
            project
            and (
                project.memory_mode == "project_only"
                or memory_policy.get("project_only") is True
            )
        )
        settings_row = await db.scalar(
            select(UserMemorySettings).where(UserMemorySettings.user_id == response.user_id)
        )
        if settings_row and not settings_row.memory_learning_enabled:
            return []
        preference_learning_enabled = bool(
            settings_row is None or settings_row.preference_learning_enabled
        )
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
            kind = str(candidate.get("kind") or "fact").strip().lower()
            if kind not in {"profile", "preference", "workflow", "fact", "episodic"}:
                kind = "fact"
            if kind in {"profile", "preference"} and not preference_learning_enabled:
                continue
            confidence = min(1.0, max(0.0, float(candidate.get("confidence") or 0.0)))
            explicit = bool(candidate.get("explicit", False))
            status = "active" if explicit or confidence >= 0.85 else "pending" if confidence >= 0.60 else "rejected"
            scope_type = str(candidate.get("scope_type") or ("project" if session.project_id else "user"))
            if scope_type not in {"user", "project", "conversation"}:
                scope_type = "user"
            if project_only:
                scope_type = "project"
            elif scope_type == "project" and not session.project_id:
                # 没有 Project 的普通会话不能产生 scope_id=None 的“伪项目记忆”。
                scope_type = "conversation"
            scope_id = (
                session.project_id
                if scope_type == "project"
                else session.id
                if scope_type == "conversation"
                else None
            )
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
                kind=kind, memory_key=memory_key, content=content,
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
                    id=str(uuid.uuid4()), user_id=response.user_id,
                    memory_type={"workflow": "procedural", "episodic": "episodic"}.get(
                        kind, "semantic"
                    ),
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
        explicit_candidates = self._extract_explicit(text)
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
            model_candidates = (
                [item for item in parsed if isinstance(item, dict)]
                if isinstance(parsed, list)
                else []
            )
        except Exception:
            model_candidates = []
        if explicit_candidates:
            # 明确“记住”指令以确定性候选为准，确保模型变化不会破坏稳定 key 和冲突替代。
            return [
                *explicit_candidates,
                *(item for item in model_candidates if not bool(item.get("explicit"))),
            ]
        return model_candidates or explicit_candidates

    @staticmethod
    def _extract_explicit(text: str) -> list[dict[str, Any]]:
        """在模型不可用时，可靠保留用户明确要求记住的非敏感信息。"""

        match = re.search(
            r"(?:请|务必|一定要)?记住(?:一下)?[\s:：,，]*(?P<content>.+)",
            text.strip(),
            flags=re.I | re.S,
        )
        if match is None:
            match = re.search(
                r"(?:please\s+)?remember(?:\s+that)?[\s,:]*(?P<content>.+)",
                text.strip(),
                flags=re.I | re.S,
            )
        if match is None:
            return []
        content = match.group("content").strip()
        content = re.split(
            r"(?:。|！|!|\n)+(?:以后|今后|下次|未来|when\b|next\s+time\b)",
            content,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" \t\r\n。！!,，")
        if not content or MemoryLearner._contains_secret(content):
            return []
        lowered = content.lower()
        if re.search(r"偏好|喜欢|习惯|回答方式|prefer|preference", lowered):
            kind = "preference"
        elif re.search(r"名字|称呼|职业|所在地|地区|name\b|job\b|location\b", lowered):
            kind = "profile"
        elif re.search(r"流程|步骤|每次|工作流|workflow|procedure", lowered):
            kind = "workflow"
        else:
            kind = "fact"
        scope_type = (
            "project"
            if re.search(r"本项目|这个项目|当前项目|this project|current project", lowered)
            else "user"
        )
        subject_match = re.search(
            r"我的(?P<subject>[^，。,:：]{1,40}?)(?:是|为|:|：)", content
        ) or re.search(
            r"my\s+(?P<subject>[a-z0-9 _-]{1,40}?)\s+(?:is|=|:)",
            lowered,
        )
        subject = subject_match.group("subject").strip() if subject_match else content[:80]
        digest = sha256(subject.lower().encode("utf-8")).hexdigest()[:20]
        return [
            {
                "content": content,
                "key": f"explicit.{kind}.{digest}",
                "kind": kind,
                "confidence": 1.0,
                "salience": 0.9,
                "explicit": True,
                "sensitive": False,
                "scope_type": scope_type,
            }
        ]

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
    Project,
