from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.security.resource_scope import load_scoped_conversation
from infra.storage.models import (
    AssistantProfile,
    MemoryCandidate,
    MemoryEvidence,
    Project,
    ResponseItem,
    ResponseRecord,
    UserMemory,
    UserMemorySettings,
)
from memory.constitution import (
    EffectiveMemoryConstitution,
    add_memory_constitution_audit,
    evaluate_memory_constitution,
    load_effective_memory_constitution,
    memory_expiry,
)
from memory.graph import link_memory_graph
from memory.quality import memory_quality_issue
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|密码|密钥)\s*[:=：]\s*\S+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)(?:身份证|护照|社保|驾驶证|银行卡|信用卡|银行账号|支付账号|税号)\s*(?:号码|号)?\s*(?:是|为|[:：=])?\s*[A-Z0-9-]{5,}"
    ),
    re.compile(r"(?i)(?:手机号|手机号码|电话号码|电子邮箱|邮箱|家庭住址|详细地址)\s*[:：=]?\s*\S+"),
    re.compile(r"(?i)(?:我|本人).{0,12}(?:患有|确诊|病史|过敏|正在服用|用药|心理疾病|精神疾病)"),
    re.compile(
        r"(?i)(?:我的|本人).{0,8}(?:收入|薪资|工资|存款|债务|贷款|账户余额)\s*(?:是|为|[:：=])"
    ),
)

_TRANSIENT_MARKERS = re.compile(
    r"(?i)(?:仅这一次|只在这次|本次请求|当前问题|临时|暂时|今天|今晚|待会|稍后|刚才|这一次|one[- ]?off|for this (?:request|time)|today|tonight)"
)

_FACT_SUBJECTS = {
    "名字",
    "称呼",
    "代号",
    "时区",
    "语言",
    "母语",
    "职业",
    "岗位",
    "职位",
    "行业",
    "团队",
    "公司",
    "角色",
    "技术栈",
    "常用技术栈",
    "工作地点",
}


class MemoryLearner:
    """Evidence-backed automatic memory candidate extraction."""

    async def learn(
        self,
        db: AsyncSession,
        *,
        response: ResponseRecord,
        deterministic_only: bool = False,
    ) -> list[str]:
        session = await load_scoped_conversation(
            db,
            conversation_id=response.conversation_id,
            user_id=response.user_id,
            tenant_id=response.tenant_id,
            workspace_id=response.workspace_id,
        )
        if session is None or session.is_temporary:
            return []
        extension = dict((response.request_payload or {}).get("opentrace") or {})
        mode = str(
            extension.get("memory_mode")
            or (response.request_payload or {}).get("memory_mode")
            or "enabled"
        )
        if mode != "enabled":
            return []
        project = (
            await db.scalar(
                select(Project).where(
                    Project.id == session.project_id,
                    Project.user_id == response.user_id,
                    Project.tenant_id == response.tenant_id,
                    Project.workspace_id == response.workspace_id,
                    Project.archived_at.is_(None),
                )
            )
            if session.project_id
            else None
        )
        profile_id = session.assistant_profile_id or (
            project.assistant_profile_id if project else None
        )
        profile = (
            await db.scalar(
                select(AssistantProfile).where(
                    AssistantProfile.id == profile_id,
                    AssistantProfile.user_id == response.user_id,
                    AssistantProfile.tenant_id == response.tenant_id,
                    AssistantProfile.workspace_id == response.workspace_id,
                )
            )
            if profile_id
            else None
        )
        memory_policy = dict(profile.memory_policy or {}) if profile else {}
        if memory_policy.get("enabled") is False or memory_policy.get("learn") is False:
            return []
        project_only = bool(
            project
            and (project.memory_mode == "project_only" or memory_policy.get("project_only") is True)
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
            .where(
                ResponseItem.response_id == response.id, ResponseItem.item_type == "input_message"
            )
            .order_by(ResponseItem.sequence_number)
        )
        text = str(input_item.content or "") if input_item else ""
        if not text:
            return []
        constitution = await load_effective_memory_constitution(
            db,
            tenant_id=response.tenant_id,
            workspace_id=response.workspace_id,
        )
        source_decision = evaluate_memory_constitution(
            text,
            constitution=constitution,
            learning_mode="proactive",
            confidence=1.0,
        )
        explicit_memory_request = bool(
            re.search(r"(?:记住|记下来|remember(?:\s+that)?)", text, flags=re.I)
        )
        if source_decision.decision == "block" and explicit_memory_request:
            add_memory_constitution_audit(
                db,
                tenant_id=response.tenant_id,
                workspace_id=response.workspace_id,
                constitution_version=constitution.version,
                decision=source_decision,
                content=text,
                source="response_learning",
                subject_user_id=response.user_id,
                response_id=response.id,
            )
            await db.commit()
            return []
        candidates = (
            self.deterministic_candidates(text)
            if deterministic_only
            else await self._extract(text, constitution=constitution)
        )
        created: list[str] = []
        for candidate in candidates[:8]:
            content = str(candidate.get("content") or "").strip()[:2000]
            if (
                not content
                or self._contains_secret(content)
                or self._contains_sensitive(content)
                or bool(candidate.get("sensitive", False))
            ):
                continue
            kind = str(candidate.get("kind") or "fact").strip().lower()
            if kind not in {"profile", "preference", "workflow", "fact", "episodic"}:
                kind = "fact"
            if memory_quality_issue(
                content,
                kind=kind,
                memory_key=str(candidate.get("key") or "") or None,
                source_response_id=None,
            ):
                continue
            if kind in {"profile", "preference"} and not preference_learning_enabled:
                continue
            personal_category = self.personal_category(
                content=content,
                memory_key=str(candidate.get("key") or ""),
                kind=kind,
            )
            confidence = min(1.0, max(0.0, float(candidate.get("confidence") or 0.0)))
            explicit = bool(candidate.get("explicit", False))
            learning_mode = str(
                candidate.get("_learning_mode") or ("explicit" if explicit else "model")
            )
            authoritative = explicit or learning_mode == "correction"
            status = self._candidate_status(
                confidence=confidence,
                explicit=authoritative,
                learning_mode=learning_mode,
            )
            constitution_decision = evaluate_memory_constitution(
                content,
                constitution=constitution,
                kind=kind,
                learning_mode=learning_mode,
                confidence=confidence,
            )
            if constitution_decision.decision == "block":
                add_memory_constitution_audit(
                    db,
                    tenant_id=response.tenant_id,
                    workspace_id=response.workspace_id,
                    constitution_version=constitution.version,
                    decision=constitution_decision,
                    content=content,
                    source="response_learning",
                    subject_user_id=response.user_id,
                    response_id=response.id,
                )
                continue
            if constitution_decision.decision == "review":
                status = "pending"
            scope_type = str(
                candidate.get("scope_type") or ("project" if session.project_id else "user")
            )
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
                else session.id if scope_type == "conversation" else None
            )
            memory_key = (
                re.sub(r"[^a-z0-9_.:-]+", "_", str(candidate.get("key") or "").lower()).strip("_")[
                    :128
                ]
                or None
            )
            conflict = await self._find_conflict(
                db,
                response.user_id,
                response.tenant_id,
                response.workspace_id,
                scope_type,
                scope_id,
                memory_key,
                content,
            )
            if conflict and conflict.content != content and not authoritative:
                status = "pending"
            row = await self._find_pending_candidate(
                db,
                response.user_id,
                response.tenant_id,
                response.workspace_id,
                scope_type,
                scope_id,
                memory_key,
                content,
            )
            if row is None:
                row = MemoryCandidate(
                    id=str(uuid.uuid4()),
                    user_id=response.user_id,
                    response_id=response.id,
                    tenant_id=response.tenant_id,
                    workspace_id=response.workspace_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    kind=kind,
                    personal_category=personal_category,
                    memory_key=memory_key,
                    content=content,
                    confidence=confidence,
                    salience=min(1.0, max(0.0, float(candidate.get("salience") or 0.5))),
                    observations=1,
                    learning_mode=learning_mode,
                    constitution_version=constitution.version,
                    status=status,
                    rejection_reason="low_confidence" if status == "rejected" else None,
                )
                db.add(row)
            else:
                row.observations = int(row.observations or 1) + 1
                row.confidence = max(float(row.confidence or 0.0), confidence)
                row.salience = max(
                    float(row.salience or 0.0),
                    min(1.0, max(0.0, float(candidate.get("salience") or 0.5))),
                )
                row.constitution_version = constitution.version
                row.personal_category = personal_category
                row.last_observed_at = datetime.now(UTC)
                if constitution_decision.decision == "allow":
                    status = self._candidate_status(
                        confidence=row.confidence,
                        explicit=explicit,
                        learning_mode=learning_mode,
                    )
                row.status = status
            if conflict and conflict.content != content and not authoritative:
                row.status = "pending"
            required_observations = int(constitution.rules["proactive_activation_observations"])
            if (
                learning_mode == "proactive"
                and row.status == "active"
                and int(row.observations or 1) < required_observations
            ):
                row.status = "pending"
            await db.flush()
            evidence = MemoryEvidence(
                id=str(uuid.uuid4()),
                candidate_id=row.id,
                response_id=response.id,
                item_id=input_item.id if input_item else None,
                excerpt=text[:500],
            )
            db.add(evidence)
            if constitution_decision.decision == "review":
                add_memory_constitution_audit(
                    db,
                    tenant_id=response.tenant_id,
                    workspace_id=response.workspace_id,
                    constitution_version=constitution.version,
                    decision=constitution_decision,
                    content=content,
                    source="response_learning",
                    subject_user_id=response.user_id,
                    response_id=response.id,
                    candidate_id=row.id,
                )
            if row.status == "active" and not await self._has_duplicate(
                db,
                response.user_id,
                response.tenant_id,
                response.workspace_id,
                scope_type,
                scope_id,
                content,
            ):
                memory = UserMemory(
                    id=str(uuid.uuid4()),
                    user_id=response.user_id,
                    memory_type={"workflow": "procedural", "episodic": "episodic"}.get(
                        kind, "semantic"
                    ),
                    tenant_id=response.tenant_id,
                    workspace_id=response.workspace_id,
                    kind=row.kind,
                    personal_category=row.personal_category,
                    title=content[:80],
                    content=content,
                    enabled=True,
                    metadata_json=json.dumps(
                        {
                            "learning_mode": learning_mode,
                            "candidate_id": row.id,
                            "constitution_version": constitution.version,
                            "observations": int(row.observations or 1),
                        },
                        ensure_ascii=False,
                    ),
                    memory_key=memory_key,
                    pinned=explicit,
                    score=row.salience,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    status="active",
                    confidence=confidence,
                    salience=row.salience,
                    source_response_id=response.id,
                    supersedes_id=conflict.id if conflict and authoritative else None,
                    expires_at=memory_expiry(constitution),
                )
                db.add(memory)
                await db.flush()
                await link_memory_graph(
                    db,
                    memory=memory,
                    evidence_response_id=response.id,
                )
                if conflict and authoritative:
                    conflict.status = "superseded"
                    conflict.enabled = False
                evidence.memory_id = memory.id
                created.append(memory.id)
        await db.commit()
        return created

    async def _extract(
        self,
        text: str,
        *,
        constitution: EffectiveMemoryConstitution | None = None,
    ) -> list[dict[str, Any]]:
        deterministic_candidates = self.deterministic_candidates(text)
        # 企业主链路优先使用可审计的确定性规则：命中后不再为相同信息额外调用模型，
        # 避免 Response 已完成后记忆投影仍被模型延迟或抖动阻塞。模型只补充规则未覆盖的表达。
        if deterministic_candidates:
            return deterministic_candidates
        prompt = (
            "主动从用户消息中提取将来多轮对话中仍有用的稳定记忆，即使用户没有说‘记住’也要识别。只输出 JSON 数组。"
            "每项字段为 content, key(稳定的snake_case主题键), kind(profile|preference|workflow|fact|episodic), confidence(0-1), "
            "salience(0-1), explicit(boolean), sensitive(boolean), scope_type(user|project)。"
            "scope_type 可为 user|project|conversation。优先提取用户直接陈述的稳定身份、长期偏好、长期目标、重复工作方式和项目约定。"
            "不要记录问题、一次性请求、临时状态、模型推测、第三方信息、健康/财务/身份号码/联系方式等敏感信息、认证信息或秘密。"
            "个人记忆应服务于个人术语/黑话、回复风格偏好、审批/操作习惯、常用模板与片段、日历和任务等长期补强。"
        )
        if constitution is not None:
            prompt += (
                "\n必须遵守以下工作区记忆宪法；若内容与宪法冲突，不得输出候选：\n"
                + constitution.content[:6000]
            )
        try:
            result = await get_model_gateway().complete(
                [LLMMessage(role="system", content=prompt), LLMMessage(role="user", content=text)],
                role=LLMRole.COMPRESS,
                fallback_roles=[LLMRole.QUERY],
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
            for item in model_candidates:
                item["_learning_mode"] = "model"
                # 只有本地明确指令解析器可以授予 explicit 权限，不能信任模型自报。
                item["_model_claimed_explicit"] = bool(item.get("explicit"))
                item["explicit"] = False
        except Exception:
            model_candidates = []
        # 本地规则提供可审计、无模型依赖的主动学习基线，模型只补充未覆盖的候选。
        # 明确“记住”仍以确定性候选为准，确保模型变化不会破坏稳定 key 和冲突替代。
        candidates = list(deterministic_candidates)
        seen_keys = {
            str(item.get("key") or "").strip().lower() for item in candidates if item.get("key")
        }
        seen_contents = {str(item.get("content") or "").strip() for item in candidates}
        for item in model_candidates:
            if any(item.get("explicit") for item in deterministic_candidates) and bool(
                item.get("_model_claimed_explicit")
            ):
                continue
            key = str(item.get("key") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if (key and key in seen_keys) or content in seen_contents:
                continue
            candidates.append(item)
            if key:
                seen_keys.add(key)
            if content:
                seen_contents.add(content)
        return candidates

    @classmethod
    def deterministic_candidates(cls, text: str) -> list[dict[str, Any]]:
        """返回无需模型即可审计和落库的稳定记忆候选。"""

        return [
            *cls._extract_explicit(text),
            *cls._extract_corrections(text),
            *cls._extract_proactive(text),
        ]

    @staticmethod
    def personal_category(*, content: str, memory_key: str, kind: str) -> str:
        """按产品定义把 user_id 分片记忆投影到稳定的个人记忆类别。"""

        value = f"{memory_key} {content}".lower()
        rules = (
            ("terminology", ("术语", "黑话", "简称", "jargon", "glossary")),
            (
                "response_style",
                ("回复风格", "回答风格", "回复要", "回答要", "格式偏好", "response_style"),
            ),
            (
                "approval_habit",
                ("审批", "批准", "操作习惯", "工作流习惯", "approval", "operation_habit"),
            ),
            ("template", ("模板", "片段", "固定格式", "template", "snippet")),
            (
                "calendar",
                (
                    "日历",
                    "日程",
                    "会议时间",
                    "工作时间",
                    "办公时间",
                    "可用时间",
                    "时区",
                    "calendar",
                    "schedule",
                    "timezone",
                    "working_hours",
                ),
            ),
            ("task", ("任务", "待办", "todo", "task")),
        )
        for category, markers in rules:
            if any(marker in value for marker in markers):
                return category
        return "response_style" if kind == "preference" and "回答" in value else "profile"

    @staticmethod
    def _extract_corrections(text: str) -> list[dict[str, Any]]:
        """提取用户对稳定个人事实的明确更正，允许以可审计方式替代旧值。"""

        without_code = re.sub(r"```[\s\S]*?```", " ", text)
        statements = [
            part.strip(" \t\r\n-•")
            for part in re.split(r"(?<=[。！？!?])\s*|\n+", without_code)
            if part.strip()
        ]
        candidates: list[dict[str, Any]] = []
        for statement in statements:
            if _TRANSIENT_MARKERS.search(statement):
                continue
            prefixed = re.match(r"^(?:更正|纠正|更新|修改)(?:一下)?[：:，, ]*", statement)
            normalized = (statement[prefixed.end() :] if prefixed else statement).rstrip(
                " \t。！？!?"
            )
            negative_match = re.match(
                r"^我的(?P<subject>[^，。:：]{1,20}?)(?:不再是|不是)\s*"
                r"[^，。！？!?]{1,100}?(?:[，,]?而是|[，,]?现在是)\s*"
                r"(?P<value>[^。！？!?]{1,160})$",
                normalized,
                flags=re.I,
            )
            now_match = re.match(
                r"^我的(?P<subject>[^，。:：]{1,20}?)现在(?:改为|改成|换成|是|为)\s*"
                r"(?P<value>[^。！？!?]{1,160})$",
                normalized,
                flags=re.I,
            )
            change_match = re.match(
                r"^我的(?P<subject>[^，。:：]{1,20}?)(?:改为|改成|换成)\s*"
                r"(?P<value>[^。！？!?]{1,160})$",
                normalized,
                flags=re.I,
            )
            direct_match = (
                re.match(
                    r"^我的(?P<subject>[^，。:：]{1,20}?)(?:是|为)\s*"
                    r"(?P<value>[^。！？!?]{1,160})$",
                    normalized,
                    flags=re.I,
                )
                if prefixed
                else None
            )
            selected = negative_match or now_match or change_match or direct_match
            if selected is None:
                continue
            subject = selected.group("subject").strip()
            value = selected.group("value").strip(" \t，,。！!")
            if subject not in _FACT_SUBJECTS or not value:
                continue
            content = f"我的{subject}是 {value}"
            if MemoryLearner._contains_secret(content) or MemoryLearner._contains_sensitive(
                content
            ):
                continue
            kind = (
                "profile" if subject in {"名字", "称呼", "职业", "岗位", "职位", "角色"} else "fact"
            )
            memory_key = MemoryLearner._subject_memory_key(subject, kind=kind)
            candidates.append(
                {
                    "content": content,
                    "key": memory_key,
                    "kind": kind,
                    "confidence": 0.98,
                    "salience": 0.9,
                    "explicit": False,
                    "sensitive": False,
                    "scope_type": "user",
                    "_learning_mode": "correction",
                }
            )
        return candidates[:4]

    @staticmethod
    def _extract_proactive(text: str) -> list[dict[str, Any]]:
        """确定性提取用户未显式要求记住、但长期稳定且低风险的信息。"""

        without_code = re.sub(r"```[\s\S]*?```", " ", text)
        statements = [
            part.strip(" \t\r\n-•")
            for part in re.split(r"(?<=[。！？!?])\s*|\n+", without_code)
            if part.strip()
        ]
        candidates: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        def add(
            *,
            content: str,
            key: str,
            kind: str,
            confidence: float,
            salience: float,
            scope_type: str = "user",
        ) -> None:
            normalized = content.strip(" \t\r\n。！!，,")
            if (
                not normalized
                or key in seen_keys
                or MemoryLearner._contains_secret(normalized)
                or MemoryLearner._contains_sensitive(normalized)
                or _TRANSIENT_MARKERS.search(normalized)
            ):
                return
            seen_keys.add(key)
            candidates.append(
                {
                    "content": normalized,
                    "key": key,
                    "kind": kind,
                    "confidence": confidence,
                    "salience": salience,
                    "explicit": False,
                    "sensitive": False,
                    "scope_type": scope_type,
                    "_learning_mode": "proactive",
                }
            )

        for statement in statements:
            if len(candidates) >= 6:
                break
            if not 3 <= len(statement) <= 280 or "?" in statement or "？" in statement:
                continue
            if _TRANSIENT_MARKERS.search(statement):
                continue

            name_match = re.match(
                r"^(?:顺便说一下[，,]?\s*)?(?:我的名字是|我叫|请称呼我为|你可以叫我)\s*(?P<value>[^，。！？!?]{1,50})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^(?:my name is|call me)\s+(?P<value>[^,.!?]{1,50})",
                statement,
                flags=re.I,
            )
            if name_match:
                add(
                    content=f"我的名字是 {name_match.group('value').strip()}",
                    key="profile.name",
                    kind="profile",
                    confidence=0.98,
                    salience=0.95,
                )
                continue

            occupation_match = re.match(
                r"^(?:我的(?:职业|岗位|职位)是|我是一名|我从事)\s*(?P<value>[^，。！？!?]{2,100})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^(?:my (?:job|role) is|i work as)\s+(?P<value>[^,.!?]{2,100})",
                statement,
                flags=re.I,
            )
            if occupation_match:
                add(
                    content=f"我的职业是 {occupation_match.group('value').strip()}",
                    key="profile.occupation",
                    kind="profile",
                    confidence=0.94,
                    salience=0.82,
                )
                continue

            time_definition_match = re.match(
                r"^(?:我的)?(?P<subject>时区|常用时区|默认时区|所在地时区|工作时间|办公时间|"
                r"可用时间|空闲时间|默认会议时长|会议默认时长)(?:是|为|[:：])\s*"
                r"(?P<value>[^。！？!?]{2,180})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^my\s+(?P<subject>timezone|working hours|office hours|available hours|"
                r"default meeting duration)\s+(?:is|are|:)\s+(?P<value>[^.!?]{2,180})",
                statement,
                flags=re.I,
            )
            if time_definition_match:
                subject = time_definition_match.group("subject").strip().lower()
                if "时区" in subject or subject == "timezone":
                    key = "profile.timezone"
                    kind = "profile"
                    salience = 0.90
                else:
                    normalized_subject = {
                        "工作时间": "working_hours",
                        "办公时间": "working_hours",
                        "working hours": "working_hours",
                        "office hours": "working_hours",
                        "可用时间": "available_hours",
                        "空闲时间": "available_hours",
                        "available hours": "available_hours",
                        "默认会议时长": "meeting_duration",
                        "会议默认时长": "meeting_duration",
                        "default meeting duration": "meeting_duration",
                    }.get(subject, sha256(subject.encode("utf-8")).hexdigest()[:16])
                    key = f"preference.schedule.{normalized_subject}"
                    kind = "preference"
                    salience = 0.88
                add(
                    content=statement,
                    key=key,
                    kind=kind,
                    confidence=0.94,
                    salience=salience,
                )
                continue

            preference_match = re.match(
                r"^(?:我(?:一直|通常|比较|更)?(?:偏好|喜欢|习惯)|我的偏好是)\s*(?P<value>[^。！？!?]{2,180})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^(?:i (?:strongly )?(?:prefer|like)|my preference is)\s+(?P<value>[^.!?]{2,180})",
                statement,
                flags=re.I,
            )
            if preference_match:
                value = preference_match.group("value").strip()
                topic = (
                    "response_style"
                    if re.search(
                        r"回答|回复|输出|格式|语言|中文|英文|简洁|详细|代码|表格|answer|response|format|language|concise|detailed",
                        value,
                        flags=re.I,
                    )
                    else sha256(value.lower().encode("utf-8")).hexdigest()[:16]
                )
                add(
                    content=statement,
                    key=f"preference.{topic}",
                    kind="preference",
                    confidence=0.92,
                    salience=0.86,
                )
                continue

            durable_instruction = re.match(
                r"^(?:以后|今后|后续|默认情况下)(?:请|都请|请你)?\s*(?P<value>[^。！？!?]{2,180})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^(?:from now on|in future|by default)[, ]+(?:please )?(?P<value>[^.!?]{2,180})",
                statement,
                flags=re.I,
            )
            if durable_instruction and re.search(
                r"回答|回复|输出|称呼|格式|语言|代码|表格|answer|reply|output|call me|format|language|code|table",
                durable_instruction.group("value"),
                flags=re.I,
            ):
                add(
                    content=statement,
                    key="preference.response_style",
                    kind="preference",
                    confidence=0.91,
                    salience=0.88,
                )
                continue

            goal_match = re.match(
                r"^(?:我的)?(?:长期目标|长期计划|职业目标)是\s*(?P<value>[^。！？!?]{3,200})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^my (?:long[- ]term |career )?goal is\s+(?P<value>[^.!?]{3,200})",
                statement,
                flags=re.I,
            )
            if goal_match:
                value = goal_match.group("value").strip()
                digest = sha256(value.lower().encode("utf-8")).hexdigest()[:16]
                add(
                    content=statement,
                    key=f"goal.long_term.{digest}",
                    kind="fact",
                    confidence=0.90,
                    salience=0.92,
                )
                continue

            workflow_match = re.match(
                r"^(?:我的(?:工作流程|工作方式|固定流程)是|我通常会)\s*(?P<value>[^。！？!?]{3,200})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^(?:my workflow is|i usually)\s+(?P<value>[^.!?]{3,200})",
                statement,
                flags=re.I,
            )
            if workflow_match:
                value = workflow_match.group("value").strip()
                digest = sha256(value.lower().encode("utf-8")).hexdigest()[:16]
                add(
                    content=statement,
                    key=f"workflow.routine.{digest}",
                    kind="workflow",
                    confidence=(
                        0.88
                        if "流程" in statement.lower() or "workflow" in statement.lower()
                        else 0.78
                    ),
                    salience=0.78,
                )
                continue

            project_match = re.match(
                r"^(?:本项目|这个项目|当前项目)(?:的)?(?P<subject>[^，。:：]{1,40}?)(?:是|为|使用|采用)\s*(?P<value>[^。！？!?]{2,180})",
                statement,
                flags=re.I,
            ) or re.match(
                r"^(?:this|the current) project(?:'s)?\s+(?P<subject>[^,.!:]{1,40}?)\s+(?:is|uses)\s+(?P<value>[^.!?]{2,180})",
                statement,
                flags=re.I,
            )
            if project_match:
                subject = project_match.group("subject").strip()
                digest = sha256(subject.lower().encode("utf-8")).hexdigest()[:16]
                add(
                    content=statement,
                    key=f"project.fact.{digest}",
                    kind="fact",
                    confidence=0.90,
                    salience=0.84,
                    scope_type="project",
                )
                continue

            fact_match = re.match(
                r"^我的(?P<subject>[^，。:：]{1,20}?)(?:是|为|使用|采用)\s*(?P<value>[^。！？!?]{2,160})",
                statement,
                flags=re.I,
            )
            if fact_match and fact_match.group("subject").strip() in _FACT_SUBJECTS:
                subject = fact_match.group("subject").strip()
                digest = sha256(subject.lower().encode("utf-8")).hexdigest()[:16]
                add(
                    content=statement,
                    key=f"fact.{digest}",
                    kind="fact",
                    confidence=0.90,
                    salience=0.80,
                )

        return candidates

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
        if (
            not content
            or MemoryLearner._contains_secret(content)
            or MemoryLearner._contains_sensitive(content)
        ):
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
        return [
            {
                "content": content,
                "key": MemoryLearner._subject_memory_key(subject, kind=kind),
                "kind": kind,
                "confidence": 1.0,
                "salience": 0.9,
                "explicit": True,
                "sensitive": False,
                "scope_type": scope_type,
                "_learning_mode": "explicit",
            }
        ]

    @staticmethod
    def _subject_memory_key(subject: str, *, kind: str) -> str:
        """为同一个人主题生成跨学习模式稳定的冲突键。"""

        normalized = subject.strip().lower()
        if normalized in {"名字", "称呼", "name"}:
            return "profile.name"
        if normalized in {"职业", "岗位", "职位", "job", "occupation"}:
            return "profile.occupation"
        if normalized in {"时区", "常用时区", "默认时区", "所在地时区", "timezone"}:
            return "profile.timezone"
        digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"{kind}.{digest}"

    @staticmethod
    def _memory_subject(content: str) -> str | None:
        match = re.search(
            r"我的(?P<subject>[^，。,:：]{1,40}?)(?:是|为|:|：)", content, flags=re.I
        ) or re.search(
            r"my\s+(?P<subject>[a-z0-9 _-]{1,40}?)\s+(?:is|=|:)",
            content,
            flags=re.I,
        )
        return match.group("subject").strip().lower() if match else None

    @staticmethod
    def _contains_secret(text: str) -> bool:
        return any(pattern.search(text) for pattern in _SECRET_PATTERNS)

    @staticmethod
    def _contains_sensitive(text: str) -> bool:
        return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)

    @staticmethod
    def _candidate_status(
        *,
        confidence: float,
        explicit: bool,
        learning_mode: str,
    ) -> str:
        if explicit:
            return "active"
        if learning_mode == "proactive" and confidence >= 0.85:
            return "active"
        if confidence >= 0.60:
            return "pending"
        return "rejected"

    @staticmethod
    async def _has_duplicate(
        db: AsyncSession,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        scope_type: str,
        scope_id: str | None,
        content: str,
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
        conflict = await db.scalar(
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
        if conflict is not None:
            return conflict

        # 兼容旧版 explicit.<kind>.<hash> 键；同一“我的 X 是 Y”主题仍应被更正替代。
        subject = MemoryLearner._memory_subject(content)
        if subject is None:
            return None
        rows = (
            (
                await db.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.tenant_id == tenant_id,
                        UserMemory.workspace_id == workspace_id,
                        UserMemory.scope_type == scope_type,
                        UserMemory.scope_id == scope_id,
                        UserMemory.status == "active",
                        UserMemory.enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        return next(
            (row for row in rows if MemoryLearner._memory_subject(row.content) == subject),
            None,
        )

    @staticmethod
    async def _find_pending_candidate(
        db: AsyncSession,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        scope_type: str,
        scope_id: str | None,
        memory_key: str | None,
        content: str,
    ) -> MemoryCandidate | None:
        conditions = [
            MemoryCandidate.user_id == user_id,
            MemoryCandidate.tenant_id == tenant_id,
            MemoryCandidate.workspace_id == workspace_id,
            MemoryCandidate.scope_type == scope_type,
            MemoryCandidate.scope_id == scope_id,
            MemoryCandidate.content == content,
            MemoryCandidate.status == "pending",
        ]
        if memory_key:
            conditions.append(MemoryCandidate.memory_key == memory_key)
        return await db.scalar(
            select(MemoryCandidate).where(*conditions).order_by(MemoryCandidate.created_at.desc())
        )

    Project,
