from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.routers.databases import _dec
from infra.config.settings import get_settings
from infra.metadata.schema_inspector import build_schema_hint, load_schema_inspection
from infra.storage.database import db_session_dependency as get_db
from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.query_intents import build_structured_database_query
from infra.storage.models import DataSource, DataSourceSchema, User
from kernel.data_cognition.sql_dialect import detect_sql_dialect, render_time_window
from kernel.data_cognition.sql_postprocess import normalize_sql_for_dialect
from kernel.data_cognition.sql_planner import SQLPlanner
from kernel.data_cognition.sql_ranker import SQLRanker
from kernel.data_cognition.sql_reflector import SQLReflector
from kernel.data_cognition.sql_rewriter import SQLRewriter
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator
from kernel.data_cognition.semantic_layer import SemanticLayer
from kernel.data_cognition.types import CandidateSQL
from execution.data.sql_executor import SQLExecutor

router = APIRouter()


class DataQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8192)
    data_source_id: str
    dry_run: bool = False
    sql: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    offset: int | None = Field(default=None, ge=0)
    order_by: str | None = None
    order_dir: str | None = Field(default=None, pattern="^(asc|desc)$")
    filters: list[dict[str, object]] | None = None


@router.post("/data/query")
async def data_query(
    req: DataQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()

    r = await db.execute(
        select(DataSource).where(
            DataSource.id == req.data_source_id,
        )
    )
    source = r.scalar_one_or_none()
    if source is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="data source not found")

    inspection = await load_schema_inspection(db, req.data_source_id)
    schema_payload = inspection.schema_payload

    # Load semantic mappings
    rs = await db.execute(select(DataSourceSchema).where(DataSourceSchema.data_source_id == req.data_source_id))
    schema_row = rs.scalar_one_or_none()
    semantic_config = schema_row.semantic_mappings if schema_row else {}

    dialect = detect_sql_dialect(source.source_type)
    structured_query = build_structured_database_query(
        req.question,
        table_names=inspection.table_names,
        database_name=source.database,
        dialect=dialect,
    )

    # Fast path: structured intents (table_count, table_list, table_schema)
    if structured_query is not None and structured_query.intent in {"table_count", "table_list", "table_schema"} and structured_query.sql:
        validator = SQLValidator(default_limit=getattr(settings, "text2sql_default_limit", 100))
        try:
            safe_sql = validator.validate(normalize_sql_for_dialect(structured_query.sql, dialect))
        except SQLValidationError as exc:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"invalid sql: {exc}")

        if req.dry_run:
            return {"data_source_id": req.data_source_id, "sql": safe_sql, "rows": [], "summary": "dry_run", "confidence": 0.7, "schema": schema_payload}

        dsn = DBRouter().build_dsn(
            DBConnectionInfo(
                source_type=source.source_type, host=source.host, port=source.port,
                database=source.database, username=source.username, password=_dec(source.password_encrypted),
            )
        )
        rows = await SQLExecutor().run_on_dsn(dsn, safe_sql)
        return _build_response(req.data_source_id, safe_sql, rows, structured_query, schema_payload, 0.95)

    # Cognitive pipeline path
    schema_hint = build_schema_hint(schema_payload)
    sql = (req.sql or "").strip()

    # Step 1: Semantic resolution
    semantic_layer = SemanticLayer(semantic_config)
    semantic_ctx = semantic_layer.resolve(req.question, dialect)
    if not semantic_ctx.time_macros:
        time_intent = semantic_layer.extract_time_intent(req.question)
        if time_intent:
            semantic_ctx.time_macros.append(time_intent)

    # Step 2: SQL generation
    if not sql:
        if structured_query is not None:
            sql = structured_query.sql
        else:
            planned = await SQLPlanner().plan(req.question, schema_hint=schema_hint, dialect=dialect)
            sql = planned.sql

    # Step 3: Multi-candidate generation
    semantic_fragments = semantic_ctx.resolved_sql_fragments if semantic_ctx.resolved_sql_fragments else None
    candidates = await SQLPlanner().generate_candidates(
        req.question, schema_hint=schema_hint, dialect=dialect, n=4,
        semantic_fragments=semantic_fragments,
    )
    if sql and not any(c.sql.lower() == sql.lower() for c in candidates):
        candidates.insert(0, CandidateSQL(sql=sql, source_template="initial"))

    # Step 4: Rank
    ranked = SQLRanker().rank(candidates, semantic_ctx, schema_hint)
    best_sql = ranked[0].sql if ranked else sql

    # Step 5: Validate
    validator = SQLValidator(default_limit=getattr(settings, "text2sql_default_limit", 100))
    try:
        safe_sql = validator.validate(normalize_sql_for_dialect(best_sql, dialect))
    except SQLValidationError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"invalid sql: {exc}")

    if req.dry_run:
        return {
            "data_source_id": req.data_source_id, "sql": safe_sql, "rows": [],
            "summary": "dry_run", "confidence": 0.8, "schema": schema_payload,
            "ranked_candidates": len(ranked),
        }

    # Step 6: Execute with reflection loop
    dsn = DBRouter().build_dsn(
        DBConnectionInfo(
            source_type=source.source_type, host=source.host, port=source.port,
            database=source.database, username=source.username, password=_dec(source.password_encrypted),
        )
    )
    rows, final_sql = await _execute_with_reflection(safe_sql, dsn, validator, dialect, req.question, schema_hint, semantic_ctx)

    # Step 7: Build response with cognitive metadata
    confidence = 0.85
    if rows:
        confidence += 0.05
    if semantic_ctx.dimension_mappings:
        confidence += 0.05

    return {
        "data_source_id": req.data_source_id,
        "sql": final_sql,
        "rows": rows,
        "summary": _build_summary(rows, structured_query, inspection.table_names),
        "confidence": round(confidence, 2),
        "schema": schema_payload,
        "ranked_candidates": len(ranked),
        "semantic_mappings_count": len(semantic_ctx.dimension_mappings),
    }


async def _execute_with_reflection(safe_sql, dsn, validator, dialect, question, schema_hint, semantic_ctx):
    reflector = SQLReflector()
    current_sql = safe_sql
    max_rounds = reflector.MAX_REFLECTION_ROUNDS

    for attempt in range(max_rounds + 1):
        try:
            rows = await SQLExecutor().run_on_dsn(dsn, current_sql)
            validation = reflector.validate_result(current_sql, rows, question, semantic_ctx)
            if validation.passed or attempt >= max_rounds:
                return rows, current_sql
            current_sql = await reflector.reflect(current_sql, validation, question, schema_hint, dialect)
            current_sql = validator.validate(normalize_sql_for_dialect(current_sql, dialect))
        except Exception as exc:
            if attempt >= max_rounds:
                raise
            current_sql = await SQLRewriter().rewrite(current_sql, str(exc), schema_hint, dialect)
            current_sql = validator.validate(normalize_sql_for_dialect(current_sql, dialect))

    return [], current_sql


def _build_response(data_source_id, sql, rows, structured_query, schema_payload, confidence):
    if len(rows) == 1 and isinstance(rows[0], dict) and any(k in rows[0] for k in ["table_count", "count", "total"]):
        count_value = rows[0].get("table_count") or rows[0].get("count") or rows[0].get("total")
        summary = f"查询成功，结果为 {count_value}"
    elif structured_query and structured_query.intent == "table_list":
        table_names = [str(row.get("table_name") or row.get("name") or "").strip() for row in rows if isinstance(row, dict)]
        table_names = [name for name in table_names if name]
        summary = f"查询成功，共 {len(table_names)} 张表：{'、'.join(table_names[:20])}" if table_names else f"查询成功，返回 {len(rows)} 张表"
    elif structured_query and structured_query.intent == "table_schema" and structured_query.table_name:
        column_names = [str(row.get("column_name") or row.get("name") or "").strip() for row in rows if isinstance(row, dict)]
        column_names = [name for name in column_names if name]
        summary = f"查询成功，表 {structured_query.table_name} 的字段有：{'、'.join(column_names[:20])}" if column_names else f"查询成功，返回表 {structured_query.table_name} 的 {len(rows)} 个字段"
    else:
        summary = f"查询成功，返回 {len(rows)} 行"
    return {"data_source_id": data_source_id, "sql": sql, "rows": rows, "summary": summary, "confidence": confidence, "schema": schema_payload}


def _build_summary(rows, structured_query, table_names):
    if len(rows) == 1 and isinstance(rows[0], dict) and any(k in rows[0] for k in ["table_count", "count", "total"]):
        count_value = rows[0].get("table_count") or rows[0].get("count") or rows[0].get("total")
        return f"查询成功，结果为 {count_value}"
    if structured_query and structured_query.intent == "table_list":
        names = [str(row.get("table_name") or row.get("name") or "").strip() for row in rows if isinstance(row, dict)]
        names = [n for n in names if n]
        return f"查询成功，共 {len(names)} 张表" if names else f"查询成功，返回 {len(rows)} 张表"
    if structured_query and structured_query.intent == "table_schema" and structured_query.table_name:
        names = [str(row.get("column_name") or row.get("name") or "").strip() for row in rows if isinstance(row, dict)]
        names = [n for n in names if n]
        return f"查询成功，返回表 {structured_query.table_name} 的 {len(rows)} 个字段"
    return f"查询成功，返回 {len(rows)} 行"


class DataSchemaSyncRequest(BaseModel):
    data_source_id: str


@router.post("/data/schema/sync")
async def data_schema_sync(
    req: DataSchemaSyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from gateway.api_gateway.routers.databases import sync_schema as databases_sync_schema

    return await databases_sync_schema(
        database_id=req.data_source_id,
        current_user=current_user,
        db=db,
    )


@router.get("/data/schema")
async def data_schema(
    data_source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.execute(
        select(DataSource).where(
            DataSource.id == data_source_id,
        )
    )
    source = r.scalar_one_or_none()
    if source is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="data source not found")

    from infra.storage.models import DataSourceSchema

    rs = await db.execute(select(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source_id))
    schema_row = rs.scalar_one_or_none()
    if schema_row is None:
        return {"data_source_id": data_source_id, "schema": {"tables": []}, "synced": False}

    payload = json.loads(schema_row.schema_json or "{}")
    return {"data_source_id": data_source_id, "schema": payload, "synced": True}
