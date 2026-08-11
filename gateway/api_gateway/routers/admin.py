"""
Admin router — system management endpoints.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from evolution.learning.learning import learning_engine
from gateway.api_gateway.routers.auth import (
    _generate_temp_password,
    _hash,
    get_current_user,
)
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from governance.chat_constitution import (
    EDITABLE_CATEGORY_LABELS as CHAT_EDITABLE_CATEGORY_LABELS,
)
from governance.chat_constitution import (
    IMMUTABLE_CATEGORY_LABELS as CHAT_IMMUTABLE_CATEGORY_LABELS,
)
from governance.chat_constitution import (
    IMMUTABLE_PROHIBITED_CATEGORIES as CHAT_IMMUTABLE_PROHIBITED_CATEGORIES,
)
from governance.chat_constitution import (
    ChatConstitutionDecision,
    EffectiveChatConstitution,
    add_chat_constitution_audit,
    evaluate_chat_constitution,
    load_effective_chat_constitution,
    normalize_chat_rules,
)
from infra.errors import AppException, ErrorCodes
from infra.notifications.mailer import notify_user_approved, schedule_email_notification
from infra.observability.logger import get_logger
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    ChatConstitution,
    ChatConstitutionAudit,
    MemoryConstitution,
    MemoryConstitutionAudit,
    User,
)
from memory.constitution import (
    EDITABLE_CATEGORY_LABELS,
    IMMUTABLE_PROHIBITED_CATEGORIES,
    EffectiveMemoryConstitution,
    MemoryConstitutionDecision,
    add_memory_constitution_audit,
    load_effective_memory_constitution,
    normalize_memory_rules,
    preview_memory_constitution_impact,
    quarantine_noncompliant_memories,
)

logger = get_logger(__name__)
router = APIRouter()


class MemoryConstitutionRulesRequest(BaseModel):
    prohibited_categories: list[str] = Field(default_factory=list, max_length=20)
    allowed_proactive_kinds: list[str] = Field(default_factory=list, max_length=10)
    custom_blocked_terms: list[str] = Field(default_factory=list, max_length=100)
    min_proactive_confidence: float = Field(default=0.85, ge=0.6, le=1.0)
    proactive_activation_observations: int = Field(default=1, ge=1, le=3)
    retention_days: int = Field(default=365, ge=1, le=3650)
    max_memory_chars: int = Field(default=2000, ge=200, le=10000)


class MemoryConstitutionUpdateRequest(BaseModel):
    content: str = Field(min_length=80, max_length=12000)
    rules: MemoryConstitutionRulesRequest
    expected_version: int | None = Field(default=None, ge=0)


class MemoryConstitutionRestoreRequest(BaseModel):
    expected_version: int = Field(ge=0)


class ChatConstitutionRulesRequest(BaseModel):
    enabled: bool = True
    prohibited_categories: list[str] = Field(default_factory=list, max_length=20)
    custom_blocked_terms: list[str] = Field(default_factory=list, max_length=200)
    custom_allowed_terms: list[str] = Field(default_factory=list, max_length=100)
    block_message: str = Field(min_length=10, max_length=300)
    max_input_chars: int = Field(default=50000, ge=500, le=100000)


class ChatConstitutionUpdateRequest(BaseModel):
    content: str = Field(min_length=80, max_length=12000)
    rules: ChatConstitutionRulesRequest
    expected_version: int | None = Field(default=None, ge=0)


class ChatConstitutionPreviewRequest(ChatConstitutionUpdateRequest):
    sample_input: str = Field(min_length=1, max_length=100000)


class ChatConstitutionRestoreRequest(BaseModel):
    expected_version: int = Field(ge=0)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_bcrypt_length(cls, password: str) -> str:
        if len(password.encode("utf-8")) > 72:
            raise ValueError("新密码不能超过 72 个字节")
        return password


def _admin_scope(request: Request, user: User) -> tuple[str, str]:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return (
        str(metadata.get("tenant_id") or "default"),
        str(metadata.get("workspace_id") or "default"),
    )


def _constitution_payload(constitution: EffectiveMemoryConstitution) -> dict[str, Any]:
    return {
        "id": constitution.id,
        "version": constitution.version,
        "content": constitution.content,
        "rules": constitution.rules,
        "created_by": constitution.created_by,
        "created_at": (constitution.created_at.isoformat() if constitution.created_at else None),
        "immutable_categories": sorted(IMMUTABLE_PROHIBITED_CATEGORIES),
        "editable_categories": EDITABLE_CATEGORY_LABELS,
    }


async def _lock_memory_constitution_scope(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
) -> None:
    # 同一工作区串行发布，避免两个管理员同时生成相同版本或留下多个活动版本。
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": f"memory_constitution:{tenant_id}:{workspace_id}"},
    )


async def _publish_memory_constitution(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    actor_user_id: str,
    content: str,
    rules: dict[str, Any],
    expected_version: int | None,
    reason_code: str,
    source: str,
) -> dict[str, Any]:
    await _lock_memory_constitution_scope(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    current = await load_effective_memory_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if expected_version is not None and expected_version != current.version:
        raise AppException(
            ErrorCodes.RESOURCE_EXISTS.code,
            message=(
                f"记忆宪法已由其他管理员更新：当前 v{current.version}，"
                f"提交基于 v{expected_version}，请刷新后重试"
            ),
        )
    normalized_content = content.strip()
    normalized_rules = normalize_memory_rules(rules)
    if normalized_content == current.content.strip() and normalized_rules == current.rules:
        response = _constitution_payload(current)
        response.update(
            {
                "quarantined_count": 0,
                "scan_limited": False,
                "effective_immediately": True,
                "unchanged": True,
            }
        )
        return response

    current_version = int(
        await db.scalar(
            select(func.max(MemoryConstitution.version)).where(
                MemoryConstitution.tenant_id == tenant_id,
                MemoryConstitution.workspace_id == workspace_id,
            )
        )
        or 0
    )
    await db.execute(
        update(MemoryConstitution)
        .where(
            MemoryConstitution.tenant_id == tenant_id,
            MemoryConstitution.workspace_id == workspace_id,
            MemoryConstitution.is_active.is_(True),
        )
        .values(is_active=False)
    )
    row = MemoryConstitution(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        version=current_version + 1,
        content=normalized_content,
        rules_json=json.dumps(normalized_rules, ensure_ascii=False),
        is_active=True,
        created_by=actor_user_id,
    )
    db.add(row)
    await db.flush()
    effective = EffectiveMemoryConstitution(
        id=row.id,
        version=row.version,
        content=row.content,
        rules=normalized_rules,
        created_by=row.created_by,
        created_at=row.created_at,
    )
    quarantined_count, scan_limited = await quarantine_noncompliant_memories(
        db,
        constitution=effective,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
    )
    add_memory_constitution_audit(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        constitution_version=row.version,
        decision=MemoryConstitutionDecision("allow", reason_code),
        content=row.content,
        source=source,
        actor_user_id=actor_user_id,
    )
    await db.commit()
    response = _constitution_payload(effective)
    response.update(
        {
            "quarantined_count": quarantined_count,
            "scan_limited": scan_limited,
            "effective_immediately": True,
            "unchanged": False,
        }
    )
    return response


def _chat_constitution_payload(
    constitution: EffectiveChatConstitution,
) -> dict[str, Any]:
    return {
        "id": constitution.id,
        "version": constitution.version,
        "content": constitution.content,
        "rules": constitution.rules,
        "created_by": constitution.created_by,
        "created_at": (constitution.created_at.isoformat() if constitution.created_at else None),
        "immutable_categories": sorted(CHAT_IMMUTABLE_PROHIBITED_CATEGORIES),
        "immutable_category_labels": CHAT_IMMUTABLE_CATEGORY_LABELS,
        "editable_categories": CHAT_EDITABLE_CATEGORY_LABELS,
    }


async def _lock_chat_constitution_scope(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": f"chat_constitution:{tenant_id}:{workspace_id}"},
    )


async def _publish_chat_constitution(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    actor_user_id: str,
    content: str,
    rules: dict[str, Any],
    expected_version: int | None,
    reason_code: str,
    source: str,
) -> dict[str, Any]:
    await _lock_chat_constitution_scope(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    current = await load_effective_chat_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if expected_version is not None and expected_version != current.version:
        raise AppException(
            ErrorCodes.RESOURCE_EXISTS.code,
            message=(
                f"聊天宪法已由其他管理员更新：当前 v{current.version}，"
                f"提交基于 v{expected_version}，请刷新后重试"
            ),
        )
    normalized_content = content.strip()
    normalized_rules = normalize_chat_rules(rules)
    if normalized_content == current.content.strip() and normalized_rules == current.rules:
        response = _chat_constitution_payload(current)
        response.update({"effective_immediately": True, "unchanged": True})
        return response

    current_version = int(
        await db.scalar(
            select(func.max(ChatConstitution.version)).where(
                ChatConstitution.tenant_id == tenant_id,
                ChatConstitution.workspace_id == workspace_id,
            )
        )
        or 0
    )
    await db.execute(
        update(ChatConstitution)
        .where(
            ChatConstitution.tenant_id == tenant_id,
            ChatConstitution.workspace_id == workspace_id,
            ChatConstitution.is_active.is_(True),
        )
        .values(is_active=False)
    )
    row = ChatConstitution(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        version=current_version + 1,
        content=normalized_content,
        rules_json=json.dumps(normalized_rules, ensure_ascii=False),
        is_active=True,
        created_by=actor_user_id,
    )
    db.add(row)
    await db.flush()
    effective = EffectiveChatConstitution(
        id=row.id,
        version=row.version,
        content=row.content,
        rules=normalized_rules,
        created_by=row.created_by,
        created_at=row.created_at,
    )
    add_chat_constitution_audit(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        constitution_version=row.version,
        decision=ChatConstitutionDecision("allow", reason_code),
        content=row.content,
        source=source,
        actor_user_id=actor_user_id,
    )
    await db.commit()
    response = _chat_constitution_payload(effective)
    response.update({"effective_immediately": True, "unchanged": False})
    return response


# ---------------------------------------------------------------------------
# Admin auth dependency
# ---------------------------------------------------------------------------
async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "admin" and not current_user.is_superuser:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="管理员权限不足")
    return current_user


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------
@router.get("/admin/users")
async def list_users(
    status: str | None = Query(None),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all users, optionally filtered by status."""
    stmt = select(User).order_by(User.created_at.desc())
    if status:
        stmt = stmt.where(User.status == status)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "status": u.status,
                "role": u.role,
                "is_superuser": u.is_superuser,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ]
    }


@router.post("/admin/users/{user_id}/approve")
async def approve_user(
    user_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve a pending user — generate password and send email."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="User not found")
    if user.status != "pending":
        raise AppException(ErrorCodes.USER_ALREADY_PROCESSED.code)

    password = _generate_temp_password()
    user.hashed_password = _hash(password)
    user.status = "active"
    user.approved_at = datetime.now(UTC)
    user.approved_by = current_user.id
    await db.commit()

    schedule_email_notification(
        notify_user_approved(user.email, password),
        kind="user_approved",
        recipient=user.email,
    )

    logger.info("User approved", user_id=user.id, by=current_user.email)
    return {"message": "用户已通过审核"}


@router.post("/admin/users/{user_id}/disable")
async def disable_user(
    user_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Disable a user account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="User not found")
    user.status = "disabled"
    await db.commit()
    logger.info("User disabled", user_id=user.id, by=current_user.email)
    return {"message": "用户已被禁用"}


@router.post("/admin/users/{user_id}/enable")
async def enable_user(
    user_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-enable a disabled user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="User not found")
    if user.status != "disabled":
        raise AppException(ErrorCodes.USER_ALREADY_PROCESSED.code)
    user.status = "active"
    await db.commit()
    logger.info("User enabled", user_id=user.id, by=current_user.email)
    return {"message": "用户已启用"}


@router.post("/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    req: ResetPasswordRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="User not found")
    if user.status == "pending":
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="待审核用户尚未激活，请先完成审核",
        )

    user.hashed_password = _hash(req.new_password)
    await db.commit()
    logger.info("User password reset", user_id=user.id, by=current_user.email)
    return {"message": "用户密码已重置"}


@router.post("/admin/learning/cycle")
async def run_learning_cycle(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Trigger a learning cycle manually."""
    cycle = await learning_engine.run_cycle()
    return {
        "cycle_id": cycle.cycle_id,
        "examples_processed": cycle.examples_processed,
        "avg_score": round(cycle.avg_score, 4),
        "strategy_updates": cycle.strategy_updates,
    }


@router.get("/admin/strategy")
async def get_strategy(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return current learned strategy."""
    strategy = await learning_engine.load_strategy()
    return {"strategy": strategy}


@router.get("/admin/bandit/stats")
async def get_bandit_stats(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return RL bandit arm statistics and total pulls."""
    from kernel.policy.rl_engine import rl_policy_engine

    stats = rl_policy_engine.bandit.get_stats()
    return {
        "total_pulls": rl_policy_engine.bandit._total_pulls,
        "arms": stats,
    }


@router.post("/admin/bandit/reset")
async def reset_bandit(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Reset bandit arm statistics (for testing / retraining)."""
    from kernel.policy.bandit import BanditPolicy
    from kernel.policy.rl_engine import rl_policy_engine

    rl_policy_engine.bandit = BanditPolicy(mode="ucb1")
    return {"status": "bandit reset"}


@router.get("/admin/memory/patterns")
async def get_memory_patterns(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return all evolved memory patterns and skills."""
    from memory.evolution.evolution import MemoryEvolution

    evo = MemoryEvolution()
    patterns, skills = await evo.load_all()
    return {
        "patterns": [
            {
                "id": p.pattern_id,
                "description": p.description,
                "strategy": p.strategy,
                "weight": p.weight,
            }
            for p in patterns
        ],
        "skills": [
            {
                "id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "triggers": s.trigger_conditions,
                "weight": s.weight,
            }
            for s in skills
        ],
    }


@router.get("/admin/memory/weak")
async def get_weak_memories(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return memory IDs below reinforcement threshold (candidates for pruning)."""
    from memory.evolution.evolution import MemoryReinforcement

    pruned = await MemoryReinforcement().prune_weak(threshold=0.1)
    return {"weak_memory_ids": pruned, "count": len(pruned)}


@router.get("/admin/memory/constitution")
async def get_memory_constitution(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取当前工作区实时生效的记忆宪法。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    constitution = await load_effective_memory_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    return _constitution_payload(constitution)


@router.put("/admin/memory/constitution")
async def update_memory_constitution(
    request: Request,
    payload: MemoryConstitutionUpdateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建新版本，并在同一事务中隔离已不合规的活动记忆。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    return await _publish_memory_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        content=payload.content,
        rules=payload.rules.model_dump(),
        expected_version=payload.expected_version,
        reason_code="constitution_published",
        source="constitution_update",
    )


@router.post("/admin/memory/constitution/preview")
async def preview_memory_constitution(
    request: Request,
    payload: MemoryConstitutionUpdateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """发布前只读评估影响，不写宪法、不隔离记忆、不产生审计。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    current = await load_effective_memory_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    proposed = EffectiveMemoryConstitution(
        id=None,
        version=current.version + 1,
        content=payload.content.strip(),
        rules=normalize_memory_rules(payload.rules.model_dump()),
        created_by=current_user.id,
    )
    impact = await preview_memory_constitution_impact(
        db,
        constitution=proposed,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    return {
        "current_version": current.version,
        "proposed_version": proposed.version,
        **impact,
    }


@router.get("/admin/memory/constitution/history")
async def list_memory_constitution_history(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _admin_scope(request, current_user)
    rows = list(
        (
            await db.execute(
                select(MemoryConstitution)
                .where(
                    MemoryConstitution.tenant_id == tenant_id,
                    MemoryConstitution.workspace_id == workspace_id,
                )
                .order_by(MemoryConstitution.version.desc())
                .limit(20)
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "version": row.version,
                "is_active": row.is_active,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "summary": next(
                    (line.strip("# ") for line in row.content.splitlines() if line.strip()),
                    "记忆宪法",
                )[:100],
            }
            for row in rows
        ]
    }


@router.post("/admin/memory/constitution/history/{version}/restore")
async def restore_memory_constitution(
    version: int,
    request: Request,
    payload: MemoryConstitutionRestoreRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """以历史内容创建一个新版本，不修改不可变历史记录。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    target = await db.scalar(
        select(MemoryConstitution).where(
            MemoryConstitution.tenant_id == tenant_id,
            MemoryConstitution.workspace_id == workspace_id,
            MemoryConstitution.version == version,
        )
    )
    if target is None:
        raise AppException(
            ErrorCodes.RESOURCE_NOT_FOUND.code,
            message=f"记忆宪法历史版本 v{version} 不存在",
        )
    try:
        target_rules = json.loads(target.rules_json or "{}")
    except (TypeError, ValueError):
        target_rules = {}
    return await _publish_memory_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        content=target.content,
        rules=target_rules,
        expected_version=payload.expected_version,
        reason_code="constitution_restored",
        source="constitution_restore",
    )


@router.get("/admin/memory/constitution/audits")
async def list_memory_constitution_audits(
    request: Request,
    decision: str | None = Query(default=None, pattern="^(allow|review|block)$"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _admin_scope(request, current_user)
    query = select(MemoryConstitutionAudit).where(
        MemoryConstitutionAudit.tenant_id == tenant_id,
        MemoryConstitutionAudit.workspace_id == workspace_id,
    )
    if decision:
        query = query.where(MemoryConstitutionAudit.decision == decision)
    rows = list(
        (
            await db.execute(query.order_by(MemoryConstitutionAudit.created_at.desc()).limit(limit))
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "subject_user_id": row.subject_user_id,
                "response_id": row.response_id,
                "memory_id": row.memory_id,
                "candidate_id": row.candidate_id,
                "constitution_version": row.constitution_version,
                "decision": row.decision,
                "reason_code": row.reason_code,
                "categories": json.loads(row.categories_json or "[]"),
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/admin/chat/constitution")
async def get_chat_constitution(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """读取当前工作区实时生效的聊天宪法。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    constitution = await load_effective_chat_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    return _chat_constitution_payload(constitution)


@router.put("/admin/chat/constitution")
async def update_chat_constitution(
    request: Request,
    payload: ChatConstitutionUpdateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建立即生效的新聊天宪法版本。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    return await _publish_chat_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        content=payload.content,
        rules=payload.rules.model_dump(),
        expected_version=payload.expected_version,
        reason_code="chat_constitution_published",
        source="constitution_update",
    )


@router.post("/admin/chat/constitution/preview")
async def preview_chat_constitution(
    request: Request,
    payload: ChatConstitutionPreviewRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """用样例输入只读测试待发布规则，不记录样例原文。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    current = await load_effective_chat_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    proposed = EffectiveChatConstitution(
        id=None,
        version=current.version + 1,
        content=payload.content.strip(),
        rules=normalize_chat_rules(payload.rules.model_dump()),
        created_by=current_user.id,
    )
    decision = evaluate_chat_constitution(
        payload.sample_input,
        constitution=proposed,
    )
    return {
        "current_version": current.version,
        "proposed_version": proposed.version,
        "decision": decision.decision,
        "reason_code": decision.reason_code,
        "categories": list(decision.categories),
        "block_message": proposed.rules["block_message"],
    }


@router.get("/admin/chat/constitution/history")
async def list_chat_constitution_history(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _admin_scope(request, current_user)
    rows = list(
        (
            await db.execute(
                select(ChatConstitution)
                .where(
                    ChatConstitution.tenant_id == tenant_id,
                    ChatConstitution.workspace_id == workspace_id,
                )
                .order_by(ChatConstitution.version.desc())
                .limit(20)
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "version": row.version,
                "is_active": row.is_active,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "summary": next(
                    (line.strip("# ") for line in row.content.splitlines() if line.strip()),
                    "聊天宪法",
                )[:100],
            }
            for row in rows
        ]
    }


@router.post("/admin/chat/constitution/history/{version}/restore")
async def restore_chat_constitution(
    version: int,
    request: Request,
    payload: ChatConstitutionRestoreRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """以历史内容创建新版本，保留不可变历史。"""

    tenant_id, workspace_id = _admin_scope(request, current_user)
    target = await db.scalar(
        select(ChatConstitution).where(
            ChatConstitution.tenant_id == tenant_id,
            ChatConstitution.workspace_id == workspace_id,
            ChatConstitution.version == version,
        )
    )
    if target is None:
        raise AppException(
            ErrorCodes.RESOURCE_NOT_FOUND.code,
            message=f"聊天宪法历史版本 v{version} 不存在",
        )
    try:
        target_rules = json.loads(target.rules_json or "{}")
    except (TypeError, ValueError):
        target_rules = {}
    return await _publish_chat_constitution(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        content=target.content,
        rules=target_rules,
        expected_version=payload.expected_version,
        reason_code="chat_constitution_restored",
        source="constitution_restore",
    )


@router.get("/admin/chat/constitution/audits")
async def list_chat_constitution_audits(
    request: Request,
    decision: str | None = Query(default=None, pattern="^(allow|block)$"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _admin_scope(request, current_user)
    query = select(ChatConstitutionAudit).where(
        ChatConstitutionAudit.tenant_id == tenant_id,
        ChatConstitutionAudit.workspace_id == workspace_id,
    )
    if decision:
        query = query.where(ChatConstitutionAudit.decision == decision)
    rows = list(
        (
            await db.execute(query.order_by(ChatConstitutionAudit.created_at.desc()).limit(limit))
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "subject_user_id": row.subject_user_id,
                "request_id": row.request_id,
                "constitution_version": row.constitution_version,
                "decision": row.decision,
                "reason_code": row.reason_code,
                "categories": json.loads(row.categories_json or "[]"),
                "content_length": row.content_length,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/admin/gateway/health")
async def gateway_health(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return ModelGateway circuit-breaker status per role."""
    from model.model_gateway.gateway import LLMRole, get_model_gateway

    gw = get_model_gateway()
    status = {}
    for role in LLMRole:
        cb = gw._circuit_breakers.get(role.value)
        if cb:
            status[role.value] = {
                "state": cb.state,
                "failures": cb.failure_count,
                "last_failure": cb.last_failure_time,
            }
        else:
            status[role.value] = {"state": "closed", "failures": 0}
    return {"circuit_breakers": status}


@router.get("/admin/meta/policies")
async def get_meta_policies(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return all meta-learning policy candidates and the active one."""
    from evolution.meta_learning.meta_learner import meta_learner

    await meta_learner._load_policies()
    policies = [
        {
            "id": p.policy_id,
            "name": p.name,
            "score": round(p.score, 4),
            "generation": p.generation,
            "is_active": p.is_active,
            "eval_count": p.eval_count,
        }
        for p in meta_learner._policies
    ]
    active_rules = await meta_learner.get_active_rules()
    return {"policies": policies, "active_rules": active_rules}


@router.post("/admin/meta/cycle")
async def run_meta_cycle(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Manually trigger a meta-learning evolution cycle."""
    from evolution.meta_learning.meta_learner import meta_learner

    result = await meta_learner.run_cycle(performance_data=[])
    return result


@router.get("/admin/market/agents")
async def list_market_agents(current_user: User = Depends(get_current_admin_user)) -> dict:
    """Return all registered agents and their reputation."""
    from agent_runtime.market.market import agent_market

    return {"agents": agent_market.list_agents()}


@router.post("/admin/selfplay/run")
async def run_self_play(
    n: int = 3,
    difficulty: float = 0.6,
    current_user: User = Depends(get_current_admin_user),
) -> dict:
    """Run N self-play episodes and feed results into the learning loop."""
    from evolution.self_play.self_play import self_play

    episodes = await self_play.run_batch(n=n, difficulty=difficulty)
    learn_result = await self_play.learn(episodes)
    return {
        "episodes": [
            {
                "id": ep.episode_id,
                "domain": ep.domain,
                "reward": round(ep.reward, 3),
                "action": ep.action,
                "task": ep.task[:80],
            }
            for ep in episodes
        ],
        "learn": learn_result,
    }
