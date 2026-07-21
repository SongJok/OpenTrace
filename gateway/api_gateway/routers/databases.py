from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from execution.data.database_hosts import (
    is_allowed_database_host,
    is_docker_internal_database_host,
    normalize_database_host,
)
from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.sql_executor import SQLExecutor
from gateway.api_gateway.resource_scope import (
    accessible_data_sources_statement,
    get_accessible_data_source,
    normalized_tenant_scope,
)
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.security.data_source_secrets import (
    decrypt_data_source_secret,
    encrypt_data_source_secret,
)
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    DataQueryLog,
    DataSource,
    DataSourceSchema,
    MetricDefinition,
    TableRelationship,
    User,
)

router = APIRouter()


SUPPORTED_SOURCE_TYPES = {"mysql", "clickhouse", "doris", "postgres"}


async def _owned_data_source(
    db: AsyncSession,
    request: Request,
    current_user: User,
    database_id: str,
    required_permission: str = "view",
) -> DataSource | None:
    tenant_md = build_tenant_metadata(request, user_id=current_user.id)
    return await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=tenant_md,
        data_source_id=database_id,
        required_permission=required_permission,
    )


class DataSourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source_type: str = Field(..., pattern="^(mysql|clickhouse|doris|postgres)$")
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=255)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=4096)


class DataSourceUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source_type: str = Field(..., pattern="^(mysql|clickhouse|doris|postgres)$")
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=255)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=4096)


def _schema_name(source_type: str, database: str) -> str:
    t = (source_type or "").lower()
    if t == "postgres":
        return "public"
    if t == "clickhouse":
        return database or "default"
    return database or "information_schema"


def _schema_sql(source_type: str, schema_name: str) -> tuple[str, str]:
    t = (source_type or "").lower()
    if t == "clickhouse":
        tables_sql = (
            "SELECT name AS table_name FROM system.tables "
            f"WHERE database = '{schema_name}' "
            "ORDER BY name"
        )
        cols_sql = (
            "SELECT table AS table_name, name AS column_name, type AS data_type FROM system.columns "
            f"WHERE database = '{schema_name}' "
            "ORDER BY table, position"
        )
        return tables_sql, cols_sql
    if t == "doris":
        tables_sql = (
            "SELECT TABLE_NAME AS table_name, TABLE_COMMENT AS table_comment FROM information_schema.tables "
            f"WHERE table_schema = '{schema_name}' "
            "ORDER BY TABLE_NAME"
        )
        cols_sql = (
            "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, DATA_TYPE AS data_type, COLUMN_COMMENT AS column_comment FROM information_schema.columns "
            f"WHERE table_schema = '{schema_name}' "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        return tables_sql, cols_sql
    if t == "postgres":
        tables_sql = (
            "SELECT c.relname AS table_name, "
            "obj_description(c.oid) AS table_comment "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = '{schema_name}' AND c.relkind = 'r' "
            "ORDER BY c.relname"
        )
        cols_sql = (
            "SELECT c.relname AS table_name, a.attname AS column_name, "
            "pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type, "
            "col_description(a.attrelid, a.attnum) AS column_comment "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid "
            f"WHERE n.nspname = '{schema_name}' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped "
            "ORDER BY c.relname, a.attnum"
        )
        return tables_sql, cols_sql
    # MySQL
    tables_sql = (
        "SELECT table_name AS table_name, table_comment AS table_comment FROM information_schema.tables "
        f"WHERE table_schema = '{schema_name}' "
        "ORDER BY table_name"
    )
    cols_sql = (
        "SELECT table_name AS table_name, column_name AS column_name, data_type AS data_type, column_comment AS column_comment FROM information_schema.columns "
        f"WHERE table_schema = '{schema_name}' "
        "ORDER BY table_name, ordinal_position"
    )
    return tables_sql, cols_sql


def _normalize_comment_row(row: dict[str, object]) -> str:
    comment = row.get("column_comment") or row.get("table_comment") or row.get("comment")
    return str(comment or "")


def _validate_database_host(host: str) -> str:
    sanitized = normalize_database_host(host)
    if not sanitized:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="host 不能为空")
    if is_docker_internal_database_host(sanitized):
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="仅支持本机或外部链接的数据库地址，不能使用 Docker 内部主机名",
        )
    if is_allowed_database_host(sanitized):
        return sanitized
    raise AppException(
        ErrorCodes.PARAM_INVALID.code,
        message="仅支持本机或外部链接的数据库地址，请填写 localhost、127.0.0.1、host.docker.internal、IP 或可解析域名",
    )


async def _check_connection(source: DataSource) -> tuple[bool, str | None]:
    try:
        dsn = DBRouter().build_dsn(
            DBConnectionInfo(
                source_type=source.source_type,
                host=source.host,
                port=source.port,
                database=source.database,
                username=source.username,
                password=decrypt_data_source_secret(source.password_encrypted),
            )
        )
        return (
            bool(
                await SQLExecutor().run_on_dsn(
                    dsn, "SELECT 1 AS ok", source_type=source.source_type
                )
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


@router.post("/databases")
async def create_database(
    http_request: Request,
    req: DataSourceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host = _validate_database_host(req.host)
    tenant_md = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(tenant_md)
    row = DataSource(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        name=req.name,
        source_type=req.source_type,
        host=host,
        port=req.port,
        database=req.database,
        username=req.username,
        password_encrypted=encrypt_data_source_secret(req.password),
        status="active",
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "created": True}


@router.patch("/databases/{database_id}")
async def update_database(
    http_request: Request,
    database_id: str,
    req: DataSourceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    host = _validate_database_host(req.host)
    x = await _owned_data_source(db, http_request, current_user, database_id, "edit")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")
    x.name = req.name
    x.source_type = req.source_type
    x.host = host
    x.port = req.port
    x.database = req.database
    x.username = req.username
    x.password_encrypted = encrypt_data_source_secret(req.password)
    x.status = "active"
    await db.commit()
    return {"id": x.id, "updated": True}


@router.get("/databases")
async def list_databases(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_md = build_tenant_metadata(http_request, user_id=current_user.id)
    r = await db.execute(
        accessible_data_sources_statement(
            user_id=current_user.id,
            tenant_metadata=tenant_md,
        ).order_by(DataSource.created_at.desc())
    )
    items = r.scalars().all()
    payloads = []
    for x in items:
        schema_row = None
        try:
            schema_row = await db.scalar(
                select(DataSourceSchema).where(DataSourceSchema.data_source_id == x.id)
            )
        except Exception:
            schema_row = None
        schema_payload = {}
        if schema_row is not None:
            try:
                schema_payload = json.loads(schema_row.schema_json or "{}")
            except Exception:
                schema_payload = {}
        payloads.append(
            {
                "id": x.id,
                "name": x.name,
                "type": x.source_type,
                "host": x.host,
                "port": x.port,
                "database": x.database,
                "username": x.username,
                "status": x.status,
                "updated_at": x.updated_at.isoformat() if x.updated_at else None,
                "created_at": x.created_at.isoformat() if x.created_at else None,
                "synced_at": schema_payload.get("synced_at"),
                "table_count": schema_payload.get("table_count", 0),
                "owned": x.user_id == current_user.id,
                "last_schema_sync_at": (
                    schema_row.updated_at.isoformat()
                    if schema_row and getattr(schema_row, "updated_at", None)
                    else None
                ),
            }
        )
    return {"items": payloads}


@router.get("/databases/{database_id}")
async def get_database(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    x = await _owned_data_source(db, http_request, current_user, database_id, "view")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")
    return {
        "id": x.id,
        "name": x.name,
        "type": x.source_type,
        "host": x.host,
        "port": x.port,
        "database": x.database,
        "username": x.username,
        "status": x.status,
    }


@router.delete("/databases/{database_id}")
async def delete_database(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    x = await _owned_data_source(db, http_request, current_user, database_id, "edit")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")
    await db.execute(delete(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id))
    await db.execute(delete(DataSource).where(DataSource.id == x.id))
    await db.commit()
    return {"deleted": True}


@router.post("/databases/{database_id}/test-connection")
async def test_connection(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    x = await _owned_data_source(db, http_request, current_user, database_id, "query")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    try:
        ok, error = await _check_connection(x)
        x.status = "active" if ok else "error"
        await db.commit()
        return {"ok": ok, "status": x.status, "error": error}
    except Exception as exc:  # pragma: no cover - defensive persistence guard
        return {"ok": False, "status": "error", "error": str(exc)}


@router.get("/databases/{database_id}/workbench")
async def database_workbench(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    source = await _owned_data_source(db, http_request, current_user, database_id, "view")
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="database not found")
    schema_row = await db.scalar(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    try:
        schema = json.loads(schema_row.schema_json or "{}") if schema_row else {}
    except (TypeError, json.JSONDecodeError):
        schema = {}
    relationships = int(
        await db.scalar(
            select(func.count(TableRelationship.id)).where(
                TableRelationship.data_source_id == database_id
            )
        )
        or 0
    )
    verified_relationships = int(
        await db.scalar(
            select(func.count(TableRelationship.id)).where(
                TableRelationship.data_source_id == database_id,
                TableRelationship.is_verified.is_(True),
            )
        )
        or 0
    )
    metrics = int(
        await db.scalar(
            select(func.count(MetricDefinition.id)).where(
                MetricDefinition.data_source_id == database_id
            )
        )
        or 0
    )
    published_metrics = int(
        await db.scalar(
            select(func.count(MetricDefinition.id)).where(
                MetricDefinition.data_source_id == database_id,
                MetricDefinition.status == "published",
            )
        )
        or 0
    )
    queries = int(
        await db.scalar(
            select(func.count(DataQueryLog.id)).where(DataQueryLog.data_source_id == database_id)
        )
        or 0
    )
    successful = int(
        await db.scalar(
            select(func.count(DataQueryLog.id)).where(
                DataQueryLog.data_source_id == database_id,
                DataQueryLog.success.is_(True),
            )
        )
        or 0
    )
    checks = {
        "connection": source.status == "active",
        "schema": bool(schema.get("tables")),
        "relationships": relationships > 0 and relationships == verified_relationships,
        "metrics": metrics > 0 and published_metrics > 0,
    }
    return {
        "source": {
            "id": source.id,
            "name": source.name,
            "status": source.status,
            "owned": source.user_id == current_user.id,
        },
        "health_score": round(sum(25 for ok in checks.values() if ok)),
        "checks": checks,
        "schema": {
            "table_count": int(schema.get("table_count") or len(schema.get("tables") or [])),
            "synced_at": schema.get("synced_at"),
        },
        "relationships": {"total": relationships, "verified": verified_relationships},
        "metrics": {"total": metrics, "published": published_metrics},
        "queries": {
            "total": queries,
            "successful": successful,
            "success_rate": round(successful / queries, 4) if queries else None,
        },
    }


@router.post("/databases/{database_id}/validate")
async def validate_database_workbench(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    source = await _owned_data_source(db, http_request, current_user, database_id, "query")
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="database not found")
    ok, error = await _check_connection(source)
    source.status = "active" if ok else "error"
    await db.commit()
    overview = await database_workbench(http_request, database_id, current_user, db)
    overview["checks"]["connection"] = ok
    overview["health_score"] = sum(25 for passed in overview["checks"].values() if passed)
    return {**overview, "validated": True, "connection_error": error}


@router.post("/databases/{database_id}/sync-schema")
async def sync_schema(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    x = await _owned_data_source(db, http_request, current_user, database_id, "edit")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    dsn = DBRouter().build_dsn(
        DBConnectionInfo(
            source_type=x.source_type,
            host=x.host,
            port=x.port,
            database=x.database,
            username=x.username,
            password=decrypt_data_source_secret(x.password_encrypted),
        )
    )

    schema_name = _schema_name(x.source_type, x.database)
    tables_sql, cols_sql = _schema_sql(x.source_type, schema_name)

    tables_rows = await SQLExecutor().run_on_dsn(dsn, tables_sql, source_type=x.source_type)
    cols_rows = await SQLExecutor().run_on_dsn(dsn, cols_sql, source_type=x.source_type)

    table_columns: dict[str, list[dict]] = {}
    for c in cols_rows:
        t = str(c.get("table_name", ""))
        if not t:
            continue
        table_columns.setdefault(t, []).append(
            {
                "name": c.get("column_name"),
                "type": c.get("data_type"),
                "comment": _normalize_comment_row(c),
            }
        )

    payload = {
        "schema": schema_name,
        "tables": [
            {
                "name": t.get("table_name"),
                "comment": str(t.get("table_comment") or t.get("comment") or ""),
                "columns": table_columns.get(str(t.get("table_name", "")), []),
            }
            for t in tables_rows
        ],
        "table_count": len(tables_rows),
        "synced_at": int(time.time()),
    }

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    s = rs.scalar_one_or_none()
    if s is None:
        s = DataSourceSchema(
            id=str(uuid.uuid4()),
            data_source_id=database_id,
            schema_json=json.dumps(payload, ensure_ascii=False),
        )
        db.add(s)
    else:
        s.schema_json = json.dumps(payload, ensure_ascii=False)
    await db.commit()

    # Auto-extract semantic mappings from schema comments
    extracted = _auto_extract_semantics_from_schema(payload)
    if extracted["dimensions"] or extracted["metrics"]:
        s.semantic_mappings = {
            "dimensions": extracted["dimensions"],
            "metrics": extracted["metrics"],
            "time_macros": (
                s.semantic_mappings.get("time_macros", []) if s.semantic_mappings else []
            ),
        }
        await db.commit()

    return {
        "synced": True,
        "data_source_id": database_id,
        "table_count": len(tables_rows),
        "auto_extracted_dimensions": len(extracted["dimensions"]),
        "auto_extracted_metrics": len(extracted["metrics"]),
    }


class DatabaseQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8192)
    sql: str | None = None
    stream: bool = False


class DatabaseAnalysisRequest(BaseModel):
    metric: str = Field(default="count")
    table: str | None = None
    date_column: str | None = None
    value_column: str | None = None
    period_days: int = Field(default=30, ge=1, le=365)


class SemanticMappingUpdate(BaseModel):
    dimensions: dict[str, dict] = Field(default_factory=dict)
    metrics: dict[str, str] = Field(default_factory=dict)
    time_macros: list[dict] = Field(default_factory=list)


@router.post("/databases/{database_id}/query")
async def query_database(
    http_request: Request,
    database_id: str,
    req: DatabaseQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from gateway.api_gateway.routers.data import DataQueryRequest, data_query

    x = await _owned_data_source(db, http_request, current_user, database_id, "query")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    t0 = time.monotonic()
    ok = True
    err = None
    out = None
    try:
        out = await data_query(
            DataQueryRequest(
                question=req.question, data_source_id=database_id, dry_run=False, sql=req.sql
            ),
            current_user=current_user,
            db=db,
            http_request=http_request,
        )
        return out
    except Exception as exc:  # noqa: BLE001
        ok = False
        err = str(exc)
        raise
    finally:
        log_entry = DataQueryLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            data_source_id=database_id,
            query_text=req.question,
            generated_sql=(out or {}).get("sql") if isinstance(out, dict) else req.sql,
            execution_time=int((time.monotonic() - t0) * 1000),
            row_count=len((out or {}).get("rows", [])) if isinstance(out, dict) else 0,
            success=ok,
            error_message=err,
        )
        # Enrich with cognitive pipeline metadata if available
        if isinstance(out, dict):
            cognitive_meta = {
                "confidence": out.get("confidence"),
                "ranked_candidates": out.get("ranked_candidates"),
                "semantic_mappings_count": out.get("semantic_mappings_count"),
            }
            log_entry.feedback_metadata = {k: v for k, v in cognitive_meta.items() if v is not None}
        db.add(log_entry)
        await db.commit()


@router.get("/databases/{database_id}/schema")
async def get_database_schema(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    x = await _owned_data_source(db, http_request, current_user, database_id, "view")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    s = rs.scalar_one_or_none()
    if s is None:
        return {"data_source_id": database_id, "schema": {"tables": []}}
    try:
        payload = json.loads(s.schema_json or "{}")
    except Exception:
        payload = {"tables": []}
    return {"data_source_id": database_id, "schema": payload}


@router.post("/databases/{database_id}/analysis")
async def analyze_database(
    http_request: Request,
    database_id: str,
    req: DatabaseAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    x = await _owned_data_source(db, http_request, current_user, database_id, "query")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    s = rs.scalar_one_or_none()
    schema_payload = json.loads(s.schema_json or "{}") if s else {"tables": []}
    tables = schema_payload.get("tables") or []

    table_name = req.table or (tables[0]["name"] if tables else None)
    if not table_name:
        return {
            "database_id": database_id,
            "summary": "未找到可分析的数据表，请先同步 Schema",
            "charts": [],
            "tables": [],
            "insights": ["先执行一次同步 Schema 再分析"],
            "analysis_plan": {},
        }

    columns = []
    for t in tables:
        if t.get("name") == table_name:
            columns = t.get("columns") or []
            break

    col_names = [str(c.get("name", "")) for c in columns]
    date_col = req.date_column or next(
        (
            c
            for c in col_names
            if any(k in c.lower() for k in ["date", "time", "created", "updated"])
        ),
        None,
    )
    value_col = req.value_column or next(
        (
            c
            for c in col_names
            if any(k in c.lower() for k in ["amount", "total", "price", "revenue", "value"])
        ),
        None,
    )

    metric_expr = "COUNT(*)"
    if req.metric in {"sum", "avg"} and value_col:
        metric_expr = f"{req.metric.upper()}({value_col})"

    from kernel.data_cognition.sql_dialect import detect_sql_dialect, render_time_window

    dialect = detect_sql_dialect(x.source_type)
    where_clause = render_time_window(dialect, date_col, req.period_days)
    trend_sql = f"SELECT {metric_expr} AS metric_value FROM {table_name}{where_clause} LIMIT 1"

    dsn = DBRouter().build_dsn(
        DBConnectionInfo(
            source_type=x.source_type,
            host=x.host,
            port=x.port,
            database=x.database,
            username=x.username,
            password=decrypt_data_source_secret(x.password_encrypted),
        )
    )
    rows = await SQLExecutor().run_on_dsn(dsn, trend_sql, source_type=x.source_type)

    value = rows[0].get("metric_value") if rows else 0
    summary = f"近 {req.period_days} 天 {table_name} 的 {req.metric} 结果为 {value}"

    return {
        "database_id": database_id,
        "summary": summary,
        "charts": [
            {
                "type": "metric",
                "title": f"{table_name} / {req.metric}",
                "value": value,
            }
        ],
        "tables": [
            {
                "title": "分析结果",
                "columns": ["metric_value"],
                "rows": rows,
                "sql": trend_sql,
            }
        ],
        "insights": [
            f"主表：{table_name}",
            f"指标：{req.metric}",
            f"窗口：近 {req.period_days} 天",
        ],
        "analysis_plan": {
            "type": "metric_or_trend",
            "metric": req.metric,
            "table": table_name,
            "date_column": date_col,
            "value_column": value_col,
        },
    }


@router.get("/databases/{database_id}/semantic")
async def get_semantic_config(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get semantic mappings for a data source."""
    x = await _owned_data_source(db, http_request, current_user, database_id)
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    s = rs.scalar_one_or_none()
    semantic = s.semantic_mappings if s else {}
    return {
        "data_source_id": database_id,
        "semantic_mappings": semantic,
    }


@router.put("/databases/{database_id}/semantic")
async def update_semantic_config(
    http_request: Request,
    database_id: str,
    req: SemanticMappingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update semantic mappings for a data source."""
    x = await _owned_data_source(db, http_request, current_user, database_id, "edit")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    s = rs.scalar_one_or_none()
    if s is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="schema not synced yet, please sync schema first"
        )

    s.semantic_mappings = {
        "dimensions": req.dimensions,
        "metrics": req.metrics,
        "time_macros": req.time_macros,
    }
    await db.commit()
    return {"data_source_id": database_id, "updated": True}


def _auto_extract_semantics_from_schema(schema_payload: dict) -> dict:
    """Automatically extract semantic mappings from table/column comments."""
    dimensions: dict[str, dict] = {}
    metrics: dict[str, str] = {}

    # Keywords that suggest a dimension (categorical attribute)
    dimension_keywords = {
        "等级": "tier",
        "状态": "status",
        "类型": "type",
        "分类": "category",
        "渠道": "channel",
        "来源": "source",
        "平台": "platform",
        "性别": "gender",
        "地区": "region",
        "城市": "city",
        "角色": "role",
        "级别": "level",
        "标签": "tag",
        "level": "level",
        "status": "status",
        "type": "type",
        "category": "category",
        "tier": "tier",
        "role": "role",
    }

    # Keywords that suggest a metric (aggregatable value)
    metric_keywords = {
        "数量": "COUNT(*)",
        "总数": "COUNT(*)",
        "用户数": "COUNT(DISTINCT user_id)",
        "订单数": "COUNT(*)",
        "金额": "SUM(amount)",
        "收入": "SUM(revenue)",
        "成本": "SUM(cost)",
        "利润": "SUM(profit)",
        "平均值": "AVG(value)",
        "count": "COUNT(*)",
        "amount": "SUM(amount)",
        "revenue": "SUM(revenue)",
        "cost": "SUM(cost)",
        "total": "COUNT(*)",
        "average": "AVG(value)",
    }

    # Keywords for date/time columns
    date_keywords = ["date", "time", "created", "updated", "注册", "创建", "更新"]

    for table in schema_payload.get("tables", []):
        table_name = table.get("name", "")
        table_comment = (table.get("comment") or "").lower()

        # Check table-level semantic
        for kw, col_name in dimension_keywords.items():
            if kw in (table.get("comment") or "").lower():
                dim_key = table_comment.replace("表", "").strip() or table_name
                if dim_key not in dimensions:
                    dimensions[dim_key] = {"column": col_name, "table": table_name, "value_map": {}}

        for col in table.get("columns", []):
            col_name = col.get("name", "")
            col_comment = (col.get("comment") or "").lower()

            # Dimension extraction
            for kw, mapped_col in dimension_keywords.items():
                if kw in col_comment and col_name:
                    dim_key = col_comment.replace("字段", "").replace("列", "").strip() or col_name
                    dimensions[dim_key] = {"column": col_name, "table": table_name, "value_map": {}}

            # Metric extraction
            for kw, expr in metric_keywords.items():
                if kw in col_comment and col_name:
                    metric_key = (
                        col_comment.replace("字段", "").replace("列", "").strip() or col_name
                    )
                    metrics[metric_key] = (
                        expr.replace("amount", col_name)
                        .replace("value", col_name)
                        .replace("revenue", col_name)
                        .replace("cost", col_name)
                    )

            # Date column hint in time_macros
            if any(kw in col_comment for kw in date_keywords):
                pass  # Will be configured manually or via time_macros

    return {"dimensions": dimensions, "metrics": metrics, "time_macros": []}


@router.post("/databases/{database_id}/semantic/auto-extract")
async def auto_extract_semantic(
    http_request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Auto-extract semantic mappings from table/column comments."""
    x = await _owned_data_source(db, http_request, current_user, database_id, "edit")
    if x is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="database not found")

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == database_id)
    )
    s = rs.scalar_one_or_none()
    if s is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="schema not synced yet, please sync schema first"
        )

    schema_payload = json.loads(s.schema_json or "{}") if s else {}
    extracted = _auto_extract_semantics_from_schema(schema_payload)

    # Merge with existing semantic mappings
    existing = s.semantic_mappings or {}
    merged = {
        "dimensions": {**existing.get("dimensions", {}), **extracted["dimensions"]},
        "metrics": {**existing.get("metrics", {}), **extracted["metrics"]},
        "time_macros": existing.get("time_macros", []),
    }
    s.semantic_mappings = merged
    await db.commit()

    return {
        "data_source_id": database_id,
        "extracted": extracted,
        "merged": merged,
        "dimension_count": len(merged["dimensions"]),
        "metric_count": len(merged["metrics"]),
    }
