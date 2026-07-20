"""版本化聊天宪法与请求前置判定。"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import ChatConstitution, ChatConstitutionAudit

DEFAULT_CHAT_CONSTITUTION = """# OpenTrace 聊天宪法

1. 聊天应尊重法律法规、公共利益与用户安全，并采用分级分类、最小必要的治理方式。
2. 不回答政治、政党、国家领导人、选举、政权、领土主权、敏感历史或社会运动等敏感议题。
3. 不提供恐怖主义、极端主义、暴力伤害、自伤、违法犯罪、网络攻击或规避安全措施的实施指导。
4. 不生成涉及未成年人的性内容，不索取或泄露密码、令牌、身份证件、金融账户等高风险信息。
5. 不协助仇恨、骚扰、歧视或对个人和群体造成现实伤害的行为。
6. 命中宪法时应停止进入模型与工具执行，并以清晰、克制的统一提示告知用户。
7. 宪法修改必须由管理员完成，按工作区版本化、可回滚、可审计；审计只保留分类与内容哈希，不保存原始提问。
8. 管理员可在不可关闭的安全底线之外调整分类、提示语与自定义词表，并应在发布前使用判定测试降低误拦截。
"""

IMMUTABLE_PROHIBITED_CATEGORIES = frozenset(
    {
        "extremism_terrorism",
        "sexual_minors",
        "privacy_credentials",
        "safety_evasion",
    }
)

EDITABLE_CATEGORY_LABELS = {
    "political_sensitive": "政治、时政与敏感公共议题",
    "violence_harm": "暴力与现实伤害指导",
    "self_harm": "自伤与自杀实施方法",
    "illegal_activity": "违法犯罪与网络攻击",
    "hate_harassment": "仇恨、歧视与骚扰",
    "adult_sexual": "露骨成人性内容",
}

IMMUTABLE_CATEGORY_LABELS = {
    "extremism_terrorism": "恐怖主义与极端主义",
    "sexual_minors": "涉及未成年人的性内容",
    "privacy_credentials": "凭证、身份和金融账户",
    "safety_evasion": "绕过聊天宪法或安全规则",
}

DEFAULT_BLOCK_MESSAGE = "该内容有悖聊天宪法，无法进行问答。请调整问题后重试。"

DEFAULT_CHAT_RULES: dict[str, Any] = {
    "enabled": True,
    "prohibited_categories": [
        *sorted(IMMUTABLE_PROHIBITED_CATEGORIES),
        *EDITABLE_CATEGORY_LABELS.keys(),
    ],
    "custom_blocked_terms": [],
    "custom_allowed_terms": [],
    "block_message": DEFAULT_BLOCK_MESSAGE,
    "max_input_chars": 50000,
}


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.IGNORECASE) for value in values)


_CATEGORY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "political_sensitive": _patterns(
        r"(?:政治|政党|政府|国家领导人|选举|政权|意识形态|领土主权|国家统一|敏感历史|敏感事件|社会运动|抗议|示威|时政)",
        r"\b(?:politics|political|election|government|president|ruling party|regime|territorial sovereignty|protest)\b",
    ),
    "extremism_terrorism": _patterns(
        r"(?:恐怖主义|恐怖组织|极端主义|圣战).{0,20}(?:加入|招募|宣传|实施|制造|袭击|教程|方法)",
        r"(?:如何|怎么|步骤|教程).{0,20}(?:制造炸弹|发动恐袭|加入恐怖组织)",
        r"\b(?:terrorist|extremist).{0,30}(?:recruit|attack|bomb|propaganda|instructions?)\b",
    ),
    "violence_harm": _patterns(
        r"(?:如何|怎么|步骤|教程|方法).{0,24}(?:杀人|伤人|下毒|绑架|毁尸|制造武器|爆炸物)",
        r"(?:杀死|伤害|毒害|绑架).{0,20}(?:某人|一个人|他|她|对方|目标)",
        r"\b(?:how to|steps? to).{0,30}(?:kill|poison|kidnap|make (?:a )?weapon)\b",
    ),
    "self_harm": _patterns(
        r"(?:自杀|自残).{0,20}(?:方法|步骤|教程|成功率|无痛|工具)",
        r"(?:如何|怎么).{0,18}(?:自杀|自残|结束生命)",
        r"\b(?:suicide|self[- ]?harm).{0,25}(?:method|instructions?|painless|how to)\b",
    ),
    "illegal_activity": _patterns(
        r"(?:如何|怎么|步骤|教程|方法).{0,24}(?:制毒|贩毒|洗钱|诈骗|勒索|偷窃|入室盗窃|伪造证件|逃税)",
        r"(?:如何|怎么|步骤|教程).{0,28}(?:入侵|攻击|破解).{0,20}(?:网站|服务器|账户|邮箱|数据库|系统)",
        r"\b(?:how to|steps? to).{0,35}(?:launder money|commit fraud|phish|ransomware|hack (?:an? )?(?:account|server|website))\b",
    ),
    "privacy_credentials": _patterns(
        r"(?:密码|口令|令牌|密钥|身份证|护照|银行卡|信用卡|银行账号)\s*(?:是|为|[:：=])\s*\S+",
        r"\b(?:password|access token|api key|private key|passport|credit card|bank account)\s*(?:is|[:=])\s*\S+",
        r"\bsk-[A-Za-z0-9_-]{16,}\b",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    ),
    "sexual_minors": _patterns(
        r"(?:儿童|小学生|初中生|未成年|幼女|幼童).{0,20}(?:色情|裸照|性行为|性爱|性描写)",
        r"(?:色情|裸照|性行为|性爱|性描写).{0,20}(?:儿童|小学生|初中生|未成年|幼女|幼童)",
        r"\b(?:child|minor|underage).{0,20}(?:sexual|porn|nude|explicit)\b",
    ),
    "hate_harassment": _patterns(
        r"(?:如何|怎么|帮我).{0,20}(?:骚扰|跟踪|人肉|羞辱|威胁).{0,20}(?:某人|他|她|对方|同事|前任)",
        r"(?:某个|所有|这些).{0,12}(?:种族|民族|宗教|性别|残障|同性恋).{0,20}(?:都该死|应该消灭|低等|不是人)",
        r"\b(?:harass|stalk|dox|threaten).{0,25}(?:someone|my ex|coworker|them)\b",
    ),
    "adult_sexual": _patterns(
        r"(?:生成|写一段|详细描写|角色扮演).{0,18}(?:露骨色情|性爱过程|性行为细节)",
        r"\b(?:generate|write|roleplay).{0,25}(?:explicit sex|pornographic|sexual details)\b",
    ),
    "safety_evasion": _patterns(
        r"(?:忽略|绕过|违反|覆盖|禁用).{0,24}(?:聊天宪法|安全规则|系统规则|内容审核|过滤器)",
        r"(?:不要|不得).{0,12}(?:告诉|通知).{0,12}(?:用户|管理员).{0,12}(?:拦截|规则|审核)",
        r"\b(?:ignore|bypass|override|disable).{0,30}(?:chat constitution|safety rules?|content moderation|filter)\b",
    ),
}


@dataclass(frozen=True)
class EffectiveChatConstitution:
    id: str | None
    version: int
    content: str
    rules: dict[str, Any]
    created_by: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ChatConstitutionDecision:
    decision: str
    reason_code: str
    categories: tuple[str, ...] = ()


def _normalize_terms(value: Any, *, limit: int) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for item in value if isinstance(value, list) else []:
        term = str(item).strip()[:100]
        folded = term.casefold()
        if len(term) < 2 or folded in seen:
            continue
        terms.append(term)
        seen.add(folded)
        if len(terms) >= limit:
            break
    return terms


def normalize_chat_rules(value: dict[str, Any] | None) -> dict[str, Any]:
    supplied = dict(value or {})
    valid_categories = {*IMMUTABLE_PROHIBITED_CATEGORIES, *EDITABLE_CATEGORY_LABELS}
    prohibited = {
        str(item)
        for item in supplied.get(
            "prohibited_categories", DEFAULT_CHAT_RULES["prohibited_categories"]
        )
        if str(item) in valid_categories
    }
    prohibited.update(IMMUTABLE_PROHIBITED_CATEGORIES)
    message = str(supplied.get("block_message") or DEFAULT_BLOCK_MESSAGE).strip()
    if not 10 <= len(message) <= 300:
        message = DEFAULT_BLOCK_MESSAGE
    return {
        "enabled": bool(supplied.get("enabled", True)),
        "prohibited_categories": sorted(prohibited),
        "custom_blocked_terms": _normalize_terms(supplied.get("custom_blocked_terms"), limit=200),
        "custom_allowed_terms": _normalize_terms(supplied.get("custom_allowed_terms"), limit=100),
        "block_message": message,
        "max_input_chars": min(
            100000,
            max(500, int(supplied.get("max_input_chars", 50000))),
        ),
    }


def _constitution_terms(content: str, labels: tuple[str, ...]) -> list[str]:
    label_pattern = "|".join(re.escape(label) for label in labels)
    terms: list[str] = []
    for match in re.finditer(
        rf"(?im)^\s*(?:[-*]\s*)?(?:{label_pattern})\s*[:：]\s*(?P<terms>[^\n]+)$",
        content,
    ):
        terms.extend(
            part.strip()
            for part in re.split(r"[,，、;；]", match.group("terms"))
            if 1 < len(part.strip()) <= 100
        )
    return terms


def evaluate_chat_constitution(
    content: str,
    *,
    constitution: EffectiveChatConstitution,
) -> ChatConstitutionDecision:
    text = str(content or "").strip()
    rules = constitution.rules
    if not text:
        return ChatConstitutionDecision("allow", "empty_input")
    if len(text) > int(rules["max_input_chars"]):
        return ChatConstitutionDecision("block", "input_too_long", ("input_limit",))

    categories = tuple(
        sorted(
            category
            for category, patterns in _CATEGORY_PATTERNS.items()
            if any(pattern.search(text) for pattern in patterns)
        )
    )
    immutable_blocked = tuple(
        category for category in categories if category in IMMUTABLE_PROHIBITED_CATEGORIES
    )
    if immutable_blocked:
        return ChatConstitutionDecision(
            "block",
            f"prohibited_category:{immutable_blocked[0]}",
            immutable_blocked,
        )
    if not rules["enabled"]:
        return ChatConstitutionDecision("allow", "constitution_disabled", categories)

    lowered = text.casefold()
    allowed_terms = [
        *rules["custom_allowed_terms"],
        *_constitution_terms(constitution.content, ("允许问答词", "允许词", "例外词")),
    ]
    if any(term.casefold() in lowered for term in allowed_terms):
        return ChatConstitutionDecision("allow", "allowed_term_exception", categories)

    prohibited = set(rules["prohibited_categories"])
    blocked = tuple(category for category in categories if category in prohibited)
    if blocked:
        return ChatConstitutionDecision("block", f"prohibited_category:{blocked[0]}", blocked)

    blocked_terms = [
        *rules["custom_blocked_terms"],
        *_constitution_terms(constitution.content, ("禁止问答词", "禁止词", "不得回答")),
    ]
    if any(term.casefold() in lowered for term in blocked_terms):
        return ChatConstitutionDecision("block", "constitution_blocked_term", ("custom",))
    return ChatConstitutionDecision("allow", "constitution_allowed", categories)


async def load_effective_chat_constitution(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
) -> EffectiveChatConstitution:
    row = await db.scalar(
        select(ChatConstitution)
        .where(
            ChatConstitution.tenant_id == tenant_id,
            ChatConstitution.workspace_id == workspace_id,
            ChatConstitution.is_active.is_(True),
        )
        .order_by(ChatConstitution.version.desc())
    )
    if row is None:
        return EffectiveChatConstitution(
            id=None,
            version=0,
            content=DEFAULT_CHAT_CONSTITUTION,
            rules=normalize_chat_rules(DEFAULT_CHAT_RULES),
        )
    try:
        rules = json.loads(row.rules_json or "{}")
    except (TypeError, ValueError):
        rules = {}
    return EffectiveChatConstitution(
        id=row.id,
        version=row.version,
        content=row.content,
        rules=normalize_chat_rules(rules),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def add_chat_constitution_audit(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    constitution_version: int,
    decision: ChatConstitutionDecision,
    content: str,
    source: str,
    actor_user_id: str | None = None,
    subject_user_id: str | None = None,
    request_id: str | None = None,
) -> ChatConstitutionAudit:
    """只记录分类、长度与不可逆摘要，不持久化用户原始提问。"""

    row = ChatConstitutionAudit(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        subject_user_id=subject_user_id,
        request_id=request_id,
        constitution_version=constitution_version,
        decision=decision.decision,
        reason_code=decision.reason_code,
        categories_json=json.dumps(list(decision.categories), ensure_ascii=False),
        content_hash=sha256(str(content or "").encode("utf-8")).hexdigest(),
        content_length=len(str(content or "")),
        source=source,
    )
    db.add(row)
    return row
