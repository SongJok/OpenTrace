"""
Analytical Skills CRUD API — manage analytical_skills knowledge assets.

Endpoints:
  GET  /api/v1/analytical-skills — list skills (filter by skill_type, status)
  POST /api/v1/analytical-skills — create skill
  GET  /api/v1/analytical-skills/{skill_id} — get single skill
  PUT  /api/v1/analytical-skills/{skill_id} — update skill
  DELETE /api/v1/analytical-skills/{skill_id} — delete skill
  POST /api/v1/analytical-skills/{skill_id}/activate — activate a skill
  POST /api/v1/analytical-skills/{skill_id}/deprecate — deprecate a skill
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.admin import get_current_admin_user
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import AnalyticalSkill, User

router = APIRouter()


# ── Pydantic Schemas ─────────────────────────────────────────────────

class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    skill_type: str = Field(..., min_length=1, max_length=50)
    description: str | None = None
    required_intent_types: list[str] = Field(default_factory=list)
    required_metric_count: int = Field(default=1)
    required_dimension_count: int = Field(default=0)
    plan_template: dict = Field(default_factory=dict)
    sql_template: str | None = None
    visualization_hint: str | None = None
    parameters_schema: dict | None = None
    examples: dict | None = None


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    skill_type: str | None = None
    description: str | None = None
    required_intent_types: list[str] | None = None
    required_metric_count: int | None = None
    required_dimension_count: int | None = None
    plan_template: dict | None = None
    sql_template: str | None = None
    visualization_hint: str | None = None
    parameters_schema: dict | None = None
    examples: dict | None = None


# ── Routes ──────────────────────────────────────────────────────────

@router.get("/analytical-skills")
async def list_skills(
    skill_type: str = Query(default=""),
    status: str = Query(default="active"),
    search: str = Query(default=""),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List analytical skills with optional filtering."""
    from sqlalchemy import and_

    conditions = []
    if skill_type:
        conditions.append(AnalyticalSkill.skill_type == skill_type)
    if status:
        conditions.append(AnalyticalSkill.status == status)
    if search:
        conditions.append(AnalyticalSkill.name.ilike(f"%{search}%"))

    query = select(AnalyticalSkill)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(AnalyticalSkill.name.asc()).offset(offset).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [_skill_to_dict(s) for s in items],
        "total": len(items),
    }


@router.get("/analytical-skills/{skill_id}")
async def get_skill(
    skill_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single analytical skill."""
    result = await db.execute(
        select(AnalyticalSkill).where(AnalyticalSkill.id == skill_id)
    )
    skill = result.scalar()
    if not skill:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"skill": _skill_to_dict(skill)}


@router.post("/analytical-skills")
async def create_skill(
    req: SkillCreateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new analytical skill."""
    skill = AnalyticalSkill(
        name=req.name,
        skill_type=req.skill_type,
        description=req.description,
        required_intent_types=req.required_intent_types,
        required_metric_count=req.required_metric_count,
        required_dimension_count=req.required_dimension_count,
        plan_template=req.plan_template,
        sql_template=req.sql_template,
        visualization_hint=req.visualization_hint,
        parameters_schema=req.parameters_schema,
        examples=req.examples,
        status="active",
        version=1,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return {"skill": _skill_to_dict(skill)}


@router.put("/analytical-skills/{skill_id}")
async def update_skill(
    skill_id: str,
    req: SkillUpdateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an analytical skill (creates new version)."""
    result = await db.execute(
        select(AnalyticalSkill).where(AnalyticalSkill.id == skill_id)
    )
    existing = result.scalar()
    if not existing:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")

    update_data = req.dict(exclude_unset=True, exclude_none=True)

    if existing.status == "active" and update_data:
        # Create new version
        new_version = (existing.version or 1) + 1
        skill = AnalyticalSkill(
            name=update_data.get("name", existing.name),
            skill_type=update_data.get("skill_type", existing.skill_type),
            description=update_data.get("description", existing.description),
            required_intent_types=update_data.get("required_intent_types", existing.required_intent_types),
            required_metric_count=update_data.get("required_metric_count", existing.required_metric_count),
            required_dimension_count=update_data.get("required_dimension_count", existing.required_dimension_count),
            plan_template=update_data.get("plan_template", existing.plan_template),
            sql_template=update_data.get("sql_template", existing.sql_template),
            visualization_hint=update_data.get("visualization_hint", existing.visualization_hint),
            parameters_schema=update_data.get("parameters_schema", existing.parameters_schema),
            examples=update_data.get("examples", existing.examples),
            status="active",
            version=new_version,
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return {"skill": _skill_to_dict(skill), "versioned": True}

    # Deprecated: update in-place
    for key, val in update_data.items():
        setattr(existing, key, val)
    existing.version = (existing.version or 1) + 1
    await db.commit()
    await db.refresh(existing)
    return {"skill": _skill_to_dict(existing), "versioned": False}


@router.delete("/analytical-skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an analytical skill."""
    result = await db.execute(
        select(AnalyticalSkill).where(AnalyticalSkill.id == skill_id)
    )
    skill = result.scalar()
    if not skill:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    await db.delete(skill)
    await db.commit()
    return {"deleted": True, "skill_id": skill_id}


@router.post("/analytical-skills/{skill_id}/activate")
async def activate_skill(
    skill_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activate an analytical skill."""
    result = await db.execute(
        select(AnalyticalSkill).where(AnalyticalSkill.id == skill_id)
    )
    skill = result.scalar()
    if not skill:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")

    skill.status = "active"
    await db.commit()
    await db.refresh(skill)
    return {"skill": _skill_to_dict(skill)}


@router.post("/analytical-skills/{skill_id}/deprecate")
async def deprecate_skill(
    skill_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deprecate an analytical skill."""
    result = await db.execute(
        select(AnalyticalSkill).where(AnalyticalSkill.id == skill_id)
    )
    skill = result.scalar()
    if not skill:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")

    skill.status = "deprecated"
    await db.commit()
    await db.refresh(skill)
    return {"skill": _skill_to_dict(skill)}


@router.post("/analytical-skills/seed")
async def seed_default_skills(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Seed the database with default analytical skill templates."""
    defaults = _get_default_skills()
    created = 0

    for tmpl in defaults:
        # Check if already exists
        result = await db.execute(
            select(AnalyticalSkill).where(AnalyticalSkill.name == tmpl["name"])
        )
        if result.scalar():
            continue

        skill = AnalyticalSkill(
            name=tmpl["name"],
            skill_type=tmpl["skill_type"],
            description=tmpl.get("description", ""),
            required_intent_types=tmpl.get("required_intent_types", []),
            required_metric_count=tmpl.get("required_metric_count", 1),
            required_dimension_count=tmpl.get("required_dimension_count", 0),
            plan_template=tmpl.get("plan_template", {}),
            sql_template=tmpl.get("sql_template", ""),
            visualization_hint=tmpl.get("visualization_hint", ""),
            parameters_schema=tmpl.get("parameters_schema", {}),
            examples=tmpl.get("examples", {}),
            status="active",
            version=1,
        )
        db.add(skill)
        created += 1

    await db.commit()
    return {"seeded": created, "total_templates": len(defaults)}


def _get_default_skills() -> list[dict]:
    """Return built-in analytical skill templates."""
    return [
        {
            "name": "同比环比分析",
            "skill_type": "comparison",
            "description": "对比当前周期与上一个/去年同期周期的指标变化",
            "required_intent_types": ["comparison"],
            "required_metric_count": 1,
            "required_dimension_count": 1,
            "visualization_hint": "grouped_bar",
            "sql_template": "SELECT dim, metric_current, metric_compare, (metric_current - metric_compare) / metric_compare * 100 AS change_pct FROM ...",
            "plan_template": {
                "steps": [
                    {"id": "calc_current_period", "agent": "data", "params": {"time_window": "$time_window"}},
                    {"id": "calc_compare_period", "agent": "data", "params": {"time_window": "$comparison_period"}},
                    {"id": "compute_change", "agent": "statistical", "depends_on": ["calc_current_period", "calc_compare_period"]},
                    {"id": "generate_insight", "agent": "insight", "depends_on": ["compute_change"]},
                    {"id": "suggest_chart", "agent": "visualization", "depends_on": ["compute_change"]},
                ],
                "parameters": {
                    "time_window": {"default": "last_30_days"},
                    "comparison_period": {"default": "same_period_last_year"},
                },
            },
        },
        {
            "name": "趋势分析",
            "skill_type": "trend",
            "description": "分析指标随时间的变化趋势，检测上升/下降/异常点",
            "required_intent_types": ["trend"],
            "required_metric_count": 1,
            "required_dimension_count": 1,
            "visualization_hint": "line",
            "sql_template": "SELECT time_dim, metric_value FROM ... ORDER BY time_dim",
            "plan_template": {
                "steps": [
                    {"id": "fetch_time_series", "agent": "data", "params": {"time_window": "$time_window"}},
                    {"id": "detect_trend", "agent": "statistical", "depends_on": ["fetch_time_series"]},
                    {"id": "generate_insight", "agent": "insight", "depends_on": ["detect_trend"]},
                    {"id": "suggest_chart", "agent": "visualization", "depends_on": ["detect_trend"]},
                ],
                "parameters": {"time_window": {"default": "last_90_days"}},
            },
        },
        {
            "name": "漏斗分析",
            "skill_type": "funnel",
            "description": "分析用户从初始步骤到最终转化的各环节转化率",
            "required_intent_types": ["funnel"],
            "required_metric_count": 1,
            "required_dimension_count": 2,
            "visualization_hint": "funnel",
            "sql_template": "SELECT step, COUNT(DISTINCT user_id) AS users FROM ... GROUP BY step ORDER BY step",
            "plan_template": {
                "steps": [
                    {"id": "calc_funnel_steps", "agent": "data"},
                    {"id": "compute_conversion", "agent": "statistical", "depends_on": ["calc_funnel_steps"]},
                    {"id": "generate_insight", "agent": "insight", "depends_on": ["compute_conversion"]},
                    {"id": "suggest_chart", "agent": "visualization", "depends_on": ["compute_conversion"]},
                ],
            },
        },
        {
            "name": "排名分析",
            "skill_type": "ranking",
            "description": "对维度进行指标排名，识别TOP/BOTTOM N",
            "required_intent_types": ["ranking"],
            "required_metric_count": 1,
            "required_dimension_count": 1,
            "visualization_hint": "horizontal_bar",
            "sql_template": "SELECT dim, metric FROM ... ORDER BY metric DESC LIMIT N",
            "plan_template": {
                "steps": [
                    {"id": "fetch_ranking", "agent": "data", "params": {"limit": "$top_n"}},
                    {"id": "compute_stats", "agent": "statistical", "depends_on": ["fetch_ranking"]},
                    {"id": "generate_insight", "agent": "insight", "depends_on": ["compute_stats"]},
                    {"id": "suggest_chart", "agent": "visualization", "depends_on": ["compute_stats"]},
                ],
                "parameters": {"top_n": {"default": "10"}},
            },
        },
        {
            "name": "分布分析",
            "skill_type": "composition",
            "description": "分析指标在各维度上的分布情况",
            "required_intent_types": ["composition", "distribution"],
            "required_metric_count": 1,
            "required_dimension_count": 1,
            "visualization_hint": "pie",
            "plan_template": {
                "steps": [
                    {"id": "fetch_distribution", "agent": "data"},
                    {"id": "compute_pct", "agent": "statistical", "depends_on": ["fetch_distribution"]},
                    {"id": "suggest_chart", "agent": "visualization", "depends_on": ["compute_pct"]},
                ],
            },
        },
    ]


def _skill_to_dict(s: AnalyticalSkill) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "skill_type": s.skill_type,
        "description": s.description,
        "required_intent_types": s.required_intent_types,
        "required_metric_count": s.required_metric_count,
        "required_dimension_count": s.required_dimension_count,
        "plan_template": s.plan_template,
        "sql_template": s.sql_template,
        "visualization_hint": s.visualization_hint,
        "parameters_schema": s.parameters_schema,
        "examples": s.examples,
        "version": s.version,
        "status": s.status,
        "created_at": str(s.created_at) if s.created_at else None,
    }
