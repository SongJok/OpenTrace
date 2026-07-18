"""
Admin router — system management endpoints.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from evolution.learning.learning import learning_engine
from gateway.api_gateway.routers.auth import (
    _generate_temp_password,
    _hash,
    get_current_user,
)
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.notifications.mailer import notify_user_approved, schedule_email_notification
from infra.observability.logger import get_logger
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import MemoryConstitution, MemoryConstitutionAudit, User
from memory.constitution import (
    EDITABLE_CATEGORY_LABELS,
    IMMUTABLE_PROHIBITED_CATEGORIES,
    EffectiveMemoryConstitution,
    MemoryConstitutionDecision,
    add_memory_constitution_audit,
    load_effective_memory_constitution,
    normalize_memory_rules,
    quarantine_noncompliant_memories,
)
from tools.registry.registry import registry

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


@router.get("/admin/tools")
async def list_tools(current_user: User = Depends(get_current_admin_user)) -> dict:
    """List all registered tools."""
    return {"tools": registry.list_all()}


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
    await db.execute(
        select(MemoryConstitution.id)
        .where(
            MemoryConstitution.tenant_id == tenant_id,
            MemoryConstitution.workspace_id == workspace_id,
            MemoryConstitution.is_active.is_(True),
        )
        .with_for_update()
    )
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
    rules = normalize_memory_rules(payload.rules.model_dump())
    row = MemoryConstitution(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        version=current_version + 1,
        content=payload.content.strip(),
        rules_json=json.dumps(rules, ensure_ascii=False),
        is_active=True,
        created_by=current_user.id,
    )
    db.add(row)
    await db.flush()
    effective = EffectiveMemoryConstitution(
        id=row.id,
        version=row.version,
        content=row.content,
        rules=rules,
        created_by=row.created_by,
        created_at=row.created_at,
    )
    quarantined_count, scan_limited = await quarantine_noncompliant_memories(
        db,
        constitution=effective,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
    )
    add_memory_constitution_audit(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        constitution_version=row.version,
        decision=MemoryConstitutionDecision("allow", "constitution_published"),
        content=row.content,
        source="constitution_update",
        actor_user_id=current_user.id,
    )
    await db.commit()
    response = _constitution_payload(effective)
    response.update(
        {
            "quarantined_count": quarantined_count,
            "scan_limited": scan_limited,
            "effective_immediately": True,
        }
    )
    return response


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
            }
            for row in rows
        ]
    }


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
