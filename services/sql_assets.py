"""SQL 资产解析、检索、查询草案生成与受控执行。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp, parse, parse_one
from sqlglot.errors import ParseError

from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.sql_executor import SQLExecutor
from infra.errors import AppException, ErrorCodes, NotFoundException, ValidationException
from infra.metadata.schema_inspector import build_schema_hint, load_schema_inspection
from infra.security.data_source_secrets import decrypt_data_source_secret
from infra.security.resource_scope import get_accessible_data_source
from infra.storage.models import (
    DataSource,
    Project,
    SchemaMetadata,
    SQLAsset,
    SQLAssetSource,
    SQLQueryCandidate,
    SQLQueryDraft,
)
from kernel.data_cognition.sql_dialect import detect_sql_dialect
from kernel.data_cognition.sql_planner import SQLPlanner
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_ASSET_STATEMENTS = 200
MAX_DRAFT_CANDIDATES = 5
PARSER_VERSION = "sqlglot-v1"


@dataclass(frozen=True)
class ParsedSQLAsset:
    statement_index: int
    normalized_sql: str
    sql_hash: str
    statement_type: str
    asset_type: str
    executable: bool
    tables: list[str]
    columns: list[str]
    parameters: dict[str, Any]
    lineage: dict[str, Any]
    validation_report: dict[str, Any]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sqlglot_dialect(dialect: str) -> str:
    normalized = str(dialect or "").strip().lower()
    if normalized in {"postgres", "postgresql", "pg"}:
        return "postgres"
    if normalized == "clickhouse":
        return "clickhouse"
    return "mysql"


def schema_fingerprint(schema_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        schema_payload or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return _hash_text(canonical)


def _statement_type(expression: Any) -> str:
    return type(expression).__name__.lower()


def _asset_type(expression: Any) -> str:
    if exp is not None and isinstance(expression, exp.Query):
        return "query"
    name = type(expression).__name__.lower()
    if name in {"insert", "update", "delete", "merge"}:
        return "etl"
    if name in {"create", "alter", "drop", "truncatetable"}:
        return "ddl"
    return "statement"


def _extract_parameters(expression: Any) -> dict[str, Any]:
    names: list[str] = []
    if exp is None:
        return {"names": names}
    parameter_types = tuple(
        item
        for item in (getattr(exp, "Placeholder", None), getattr(exp, "Parameter", None))
        if item
    )
    if parameter_types:
        for node in expression.walk():
            if isinstance(node, parameter_types):
                value = str(getattr(node, "name", "") or node.sql()).strip()
                if value and value not in names:
                    names.append(value)
    return {"names": names}


def _extract_tables_columns(expression: Any) -> tuple[list[str], list[str]]:
    if exp is None:
        return [], []
    tables = sorted(
        {
            str(node.name).strip()
            for node in expression.find_all(exp.Table)
            if str(node.name).strip()
        }
    )
    columns = sorted(
        {
            (f"{node.table}.{node.name}" if node.table else str(node.name)).strip()
            for node in expression.find_all(exp.Column)
            if str(node.name).strip()
        }
    )
    return tables, columns


def _lineage(expression: Any, tables: list[str], columns: list[str]) -> dict[str, Any]:
    write_tables: list[str] = []
    if exp is not None and not isinstance(expression, exp.Query):
        target = getattr(expression, "this", None)
        if isinstance(target, exp.Table) and target.name:
            write_tables.append(str(target.name))
        elif target is not None:
            target_table = next(iter(target.find_all(exp.Table)), None)
            if target_table is not None and target_table.name:
                write_tables.append(str(target_table.name))
    return {"read_tables": tables, "write_tables": write_tables, "columns": columns}


def _validate_schema_references(
    expression: Any,
    *,
    table_columns: dict[str, list[str]],
    sensitive_columns: set[tuple[str, str]] | None = None,
) -> tuple[list[str], list[str]]:
    if exp is None or not table_columns:
        return ["当前数据源尚未同步 Schema，无法完成表列静态校验"], []

    errors: list[str] = []
    warnings: list[str] = []
    table_lookup = {name.lower(): name for name in table_columns}
    cte_names = {
        str(cte.alias_or_name).strip().lower()
        for cte in expression.find_all(exp.CTE)
        if str(cte.alias_or_name).strip()
    }
    alias_lookup: dict[str, str] = {}
    referenced_tables: list[str] = []
    for table in expression.find_all(exp.Table):
        table_name = str(table.name or "").strip()
        if not table_name:
            continue
        if table_name.lower() in cte_names:
            alias_lookup[table_name.lower()] = table_name
            continue
        schema_name = str(table.db or "").strip().lower()
        if schema_name in {"information_schema", "pg_catalog", "system"}:
            continue
        actual = table_lookup.get(table_name.lower())
        if actual is None:
            errors.append(f"Schema 中不存在表：{table_name}")
            continue
        referenced_tables.append(actual)
        alias = str(table.alias or "").strip()
        if alias:
            alias_lookup[alias.lower()] = actual
        alias_lookup[table_name.lower()] = actual

    sensitive = {(table.lower(), column.lower()) for table, column in (sensitive_columns or set())}
    has_star = any(
        isinstance(selection, exp.Star)
        or (isinstance(selection, exp.Column) and isinstance(selection.this, exp.Star))
        for selection in getattr(expression, "selects", [])
    )
    if has_star and any(
        table.lower() in {item[0] for item in sensitive} for table in referenced_tables
    ):
        errors.append("查询包含 SELECT *，且涉及配置了敏感字段的表")

    for column in expression.find_all(exp.Column):
        column_name = str(column.name or "").strip()
        qualifier = str(column.table or "").strip().lower()
        if not column_name or column_name == "*":
            continue
        target_tables: list[str] = []
        if qualifier:
            actual = alias_lookup.get(qualifier)
            if actual and actual.lower() not in cte_names:
                target_tables = [actual]
        elif len(set(referenced_tables)) == 1:
            target_tables = [referenced_tables[0]]
        if not target_tables:
            continue
        for table_name in target_tables:
            known_columns = {item.lower() for item in table_columns.get(table_name, [])}
            if known_columns and column_name.lower() not in known_columns:
                errors.append(f"表 {table_name} 中不存在列：{column_name}")
            if (table_name.lower(), column_name.lower()) in sensitive:
                errors.append(f"查询直接引用敏感字段：{table_name}.{column_name}")
    return sorted(set(errors)), sorted(set(warnings))


def parse_sql_assets(
    source_text: str,
    *,
    dialect: str,
    table_columns: dict[str, list[str]] | None = None,
    sensitive_columns: set[tuple[str, str]] | None = None,
) -> list[ParsedSQLAsset]:
    """按方言解析多语句文件；本函数不建立数据库连接。"""

    if parse is None or exp is None:
        raise ValidationException("SQL AST 解析器不可用")
    text = str(source_text or "")
    if not text.strip():
        raise ValidationException("SQL 文件内容不能为空")
    try:
        statements = [
            item for item in parse(text, read=_sqlglot_dialect(dialect)) if item is not None
        ]
    except ParseError as exc:
        raise ValidationException(f"SQL 文件解析失败：{exc}") from exc
    if not statements:
        raise ValidationException("SQL 文件中没有可识别的语句")
    if len(statements) > MAX_ASSET_STATEMENTS:
        raise ValidationException(f"单个文件最多允许 {MAX_ASSET_STATEMENTS} 条 SQL 语句")

    parsed: list[ParsedSQLAsset] = []
    for index, statement in enumerate(statements, start=1):
        normalized = statement.sql(dialect=_sqlglot_dialect(dialect), pretty=True, comments=False)
        tables, columns = _extract_tables_columns(statement)
        executable = isinstance(statement, exp.Query)
        errors: list[str] = []
        warnings: list[str] = []
        safe_sql = normalized
        if executable:
            try:
                safe_sql = SQLValidator(default_limit=100, max_limit=500).validate(normalized)
                safe_expression = parse_one(safe_sql, read=_sqlglot_dialect(dialect))
                safe_sql = safe_expression.sql(
                    dialect=_sqlglot_dialect(dialect), pretty=True, comments=False
                )
                schema_errors, schema_warnings = _validate_schema_references(
                    safe_expression,
                    table_columns=table_columns or {},
                    sensitive_columns=sensitive_columns,
                )
                errors.extend(schema_errors)
                warnings.extend(schema_warnings)
            except (SQLValidationError, ParseError) as exc:
                errors.append(str(exc))
        else:
            warnings.append("非只读语句仅用于血缘参考，不允许发布为在线执行资产")
        parsed.append(
            ParsedSQLAsset(
                statement_index=index,
                normalized_sql=safe_sql,
                sql_hash=_hash_text(safe_sql),
                statement_type=_statement_type(statement),
                asset_type=_asset_type(statement),
                executable=executable and not errors,
                tables=tables,
                columns=columns,
                parameters=_extract_parameters(statement),
                lineage=_lineage(statement, tables, columns),
                validation_report={
                    "status": "pass" if not errors else "fail",
                    "errors": errors,
                    "warnings": warnings,
                    "parser_version": PARSER_VERSION,
                },
            )
        )
    return parsed


async def _sensitive_columns(db: AsyncSession, data_source_id: str) -> set[tuple[str, str]]:
    rows = (
        (
            await db.execute(
                select(SchemaMetadata).where(
                    SchemaMetadata.data_source_id == data_source_id,
                    SchemaMetadata.is_sensitive.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return {(row.table_name, row.column_name) for row in rows}


async def _validate_project_scope(
    db: AsyncSession,
    *,
    project_id: str | None,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    data_source_id: str,
) -> None:
    if not project_id:
        return
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
            Project.archived_at.is_(None),
        )
    )
    if project is None or data_source_id not in set(project.data_source_ids or []):
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="Project 未绑定该数据源")


async def create_sql_asset_source(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    data_source_id: str,
    filename: str,
    content_type: str,
    source_text: str,
    dialect: str,
    project_id: str | None = None,
) -> tuple[SQLAssetSource, list[SQLAsset], bool]:
    encoded = source_text.encode("utf-8")
    if len(encoded) > MAX_UPLOAD_BYTES:
        raise ValidationException(f"SQL 文件不能超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    content_hash = _hash_text(source_text)
    existing = await db.scalar(
        select(SQLAssetSource).where(
            SQLAssetSource.tenant_id == tenant_id,
            SQLAssetSource.workspace_id == workspace_id,
            SQLAssetSource.data_source_id == data_source_id,
            SQLAssetSource.content_sha256 == content_hash,
        )
    )
    if existing is not None:
        assets = list(
            (
                await db.execute(
                    select(SQLAsset)
                    .where(SQLAsset.source_id == existing.id)
                    .order_by(SQLAsset.statement_index)
                )
            )
            .scalars()
            .all()
        )
        return existing, assets, True

    inspection = await load_schema_inspection(db, data_source_id)
    fingerprint = schema_fingerprint(inspection.schema_payload)
    parsed = parse_sql_assets(
        source_text,
        dialect=dialect,
        table_columns=inspection.column_map,
        sensitive_columns=await _sensitive_columns(db, data_source_id),
    )
    version = (
        int(
            await db.scalar(
                select(SQLAssetSource.version)
                .where(
                    SQLAssetSource.tenant_id == tenant_id,
                    SQLAssetSource.workspace_id == workspace_id,
                    SQLAssetSource.data_source_id == data_source_id,
                    SQLAssetSource.filename == filename,
                )
                .order_by(SQLAssetSource.version.desc())
                .limit(1)
            )
            or 0
        )
        + 1
    )
    source = SQLAssetSource(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        data_source_id=data_source_id,
        filename=filename,
        content_type=content_type or "text/plain",
        source_text=source_text,
        content_sha256=content_hash,
        dialect=dialect,
        parser_version=PARSER_VERSION,
        status="parsed",
        statement_count=len(parsed),
        parse_report={},
        version=version,
    )
    db.add(source)
    await db.flush()
    parsed_hashes = {item.sql_hash for item in parsed}
    existing_hashes = set(
        (
            await db.execute(
                select(SQLAsset.sql_hash).where(
                    SQLAsset.tenant_id == tenant_id,
                    SQLAsset.workspace_id == workspace_id,
                    SQLAsset.data_source_id == data_source_id,
                    SQLAsset.sql_hash.in_(parsed_hashes),
                )
            )
        )
        .scalars()
        .all()
    )
    unique_parsed: list[ParsedSQLAsset] = []
    seen_hashes = set(existing_hashes)
    for item in parsed:
        if item.sql_hash in seen_hashes:
            continue
        seen_hashes.add(item.sql_hash)
        unique_parsed.append(item)
    source.parse_report = {
        "status": "parsed",
        "statement_count": len(parsed),
        "asset_count": len(unique_parsed),
        "duplicate_count": len(parsed) - len(unique_parsed),
        "executable_count": sum(1 for item in unique_parsed if item.executable),
        "invalid_count": sum(
            1 for item in unique_parsed if item.validation_report.get("status") == "fail"
        ),
    }
    assets = [
        SQLAsset(
            id=str(uuid.uuid4()),
            source_id=source.id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            data_source_id=data_source_id,
            statement_index=item.statement_index,
            title=f"{filename} / SQL {item.statement_index}",
            normalized_sql=item.normalized_sql,
            sql_hash=item.sql_hash,
            asset_type=item.asset_type,
            statement_type=item.statement_type,
            executable=item.executable,
            status="draft",
            dialect=dialect,
            tables=item.tables,
            columns=item.columns,
            lineage=item.lineage,
            parameters=item.parameters,
            validation_report=item.validation_report,
            schema_fingerprint=fingerprint,
        )
        for item in unique_parsed
    ]
    db.add_all(assets)
    await db.commit()
    return source, assets, False


def serialize_asset(asset: SQLAsset, *, include_sql: bool = True) -> dict[str, Any]:
    payload = {
        "id": asset.id,
        "source_id": asset.source_id,
        "title": asset.title,
        "description": asset.description,
        "asset_type": asset.asset_type,
        "statement_type": asset.statement_type,
        "executable": asset.executable,
        "status": asset.status,
        "dialect": asset.dialect,
        "tables": asset.tables or [],
        "columns": asset.columns or [],
        "tags": asset.tags or [],
        "lineage": asset.lineage or {},
        "validation_report": asset.validation_report or {},
        "schema_fingerprint": asset.schema_fingerprint,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }
    if include_sql:
        payload["sql"] = asset.normalized_sql
    return payload


def serialize_source(source: SQLAssetSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "filename": source.filename,
        "content_type": source.content_type,
        "content_sha256": source.content_sha256,
        "dialect": source.dialect,
        "status": source.status,
        "statement_count": source.statement_count,
        "parse_report": source.parse_report or {},
        "version": source.version,
        "project_id": source.project_id,
        "created_at": source.created_at,
    }


async def retrieve_sql_assets(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    data_source_id: str,
    question: str,
    dialect: str,
    project_id: str | None,
    limit: int = 5,
) -> list[SQLAsset]:
    stmt = select(SQLAsset).where(
        SQLAsset.tenant_id == tenant_id,
        SQLAsset.workspace_id == workspace_id,
        SQLAsset.data_source_id == data_source_id,
        SQLAsset.status == "published",
        SQLAsset.executable.is_(True),
        SQLAsset.dialect == dialect,
    )
    if project_id:
        stmt = stmt.where(or_(SQLAsset.project_id.is_(None), SQLAsset.project_id == project_id))
    else:
        stmt = stmt.where(SQLAsset.project_id.is_(None))
    rows = list((await db.execute(stmt.limit(100))).scalars().all())
    query_tokens = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        query_tokens.add(segment)
        query_tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))

    def relevance(asset: SQLAsset) -> int:
        searchable = " ".join(
            [
                asset.title,
                asset.description,
                " ".join(asset.tags or []),
                " ".join(asset.tables or []),
            ]
        ).lower()
        return sum(1 for token in query_tokens if token in searchable)

    relevant_rows = [asset for asset in rows if relevance(asset) > 0]
    relevant_rows.sort(
        key=lambda asset: (relevance(asset), str(asset.created_at or "")), reverse=True
    )
    return relevant_rows[: max(1, min(limit, 10))]


def _strip_model_sql(value: str) -> str:
    text = str(value or "").strip()
    fenced = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", text, flags=re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()
    return text


def _validated_candidate(
    sql: str,
    *,
    dialect: str,
    table_columns: dict[str, list[str]],
    sensitive_columns: set[tuple[str, str]],
) -> tuple[str, dict[str, Any], list[str], list[str]]:
    raw = _strip_model_sql(sql)
    if not raw:
        raise SQLValidationError("empty sql")
    expression = parse_one(raw, read=_sqlglot_dialect(dialect))
    normalized = expression.sql(dialect=_sqlglot_dialect(dialect), comments=False)
    safe_sql = SQLValidator(default_limit=100, max_limit=500).validate(normalized)
    safe_expression = parse_one(safe_sql, read=_sqlglot_dialect(dialect))
    safe_sql = safe_expression.sql(dialect=_sqlglot_dialect(dialect), pretty=True, comments=False)
    errors, warnings = _validate_schema_references(
        safe_expression,
        table_columns=table_columns,
        sensitive_columns=sensitive_columns,
    )
    if errors:
        raise SQLValidationError("；".join(errors))
    tables, columns = _extract_tables_columns(safe_expression)
    return safe_sql, {"status": "pass", "errors": [], "warnings": warnings}, tables, columns


async def generate_sql_query_draft(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    data_source: DataSource,
    question: str,
    supplied_sql: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    response_id: str | None = None,
    group_type: str = "alternative",
) -> tuple[SQLQueryDraft, list[SQLQueryCandidate]]:
    if group_type not in {"alternative", "batch"}:
        raise ValidationException("group_type 仅支持 alternative 或 batch")
    await _validate_project_scope(
        db,
        project_id=project_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=data_source.id,
    )
    inspection = await load_schema_inspection(db, data_source.id)
    dialect = detect_sql_dialect(data_source.source_type).name
    fingerprint = schema_fingerprint(inspection.schema_payload)
    assets = await retrieve_sql_assets(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=data_source.id,
        question=question,
        dialect=dialect,
        project_id=project_id,
    )
    asset_context = "\n\n".join(
        f"资产 {index + 1}（{asset.title}）：\n{asset.normalized_sql}"
        for index, asset in enumerate(assets[:3])
    )
    grounded_question = question
    if asset_context:
        grounded_question += (
            "\n以下是同一数据源内已审核发布的 SQL 资产。仅复用与问题相关的表、JOIN 和指标口径，"
            "不要照搬不匹配的过滤值：\n" + asset_context
        )
    raw_candidates: list[str]
    if supplied_sql and supplied_sql.strip():
        raw_candidates = [supplied_sql]
    else:
        planned = await SQLPlanner().generate_candidates(
            grounded_question,
            schema_hint=build_schema_hint(inspection.schema_payload, max_chars=8000),
            dialect=detect_sql_dialect(data_source.source_type),
            n=3,
        )
        raw_candidates = [candidate.sql for candidate in planned]

    sensitive = await _sensitive_columns(db, data_source.id)
    validated: list[tuple[str, dict[str, Any], list[str], list[str]]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw_sql in raw_candidates[:MAX_DRAFT_CANDIDATES]:
        try:
            item = _validated_candidate(
                raw_sql,
                dialect=dialect,
                table_columns=inspection.column_map,
                sensitive_columns=sensitive,
            )
        except (SQLValidationError, ParseError) as exc:
            errors.append(str(exc))
            continue
        sql_hash = _hash_text(item[0])
        if sql_hash in seen:
            continue
        seen.add(sql_hash)
        validated.append(item)
    if not validated:
        raise ValidationException(
            "未能生成通过安全校验的只读 SQL",
            details={"candidate_errors": errors[:5]},
        )

    draft = SQLQueryDraft(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        response_id=response_id,
        data_source_id=data_source.id,
        question=question,
        group_type=group_type,
        status="awaiting_confirmation",
        dialect=dialect,
        schema_fingerprint=fingerprint,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(draft)
    await db.flush()
    candidates: list[SQLQueryCandidate] = []
    asset_ids = [asset.id for asset in assets]
    for position, (sql, report, tables, columns) in enumerate(validated, start=1):
        candidate = SQLQueryCandidate(
            id=str(uuid.uuid4()),
            draft_id=draft.id,
            position=position,
            title=f"SQL 方案 {position}",
            description=(
                f"参考 {len(asset_ids)} 条已发布 SQL 资产生成"
                if asset_ids
                else "基于当前 Schema 生成"
            ),
            sql=sql,
            sql_hash=_hash_text(sql),
            asset_ids=asset_ids,
            tables=tables,
            columns=columns,
            assumptions=[],
            validation_report=report,
        )
        db.add(candidate)
        candidates.append(candidate)
    await db.commit()
    return draft, candidates


def serialize_candidate(
    candidate: SQLQueryCandidate, *, include_result: bool = True
) -> dict[str, Any]:
    payload = {
        "id": candidate.id,
        "position": candidate.position,
        "title": candidate.title,
        "description": candidate.description,
        "sql": candidate.sql,
        "sql_hash": candidate.sql_hash,
        "asset_ids": candidate.asset_ids or [],
        "tables": candidate.tables or [],
        "columns": candidate.columns or [],
        "assumptions": candidate.assumptions or [],
        "validation_report": candidate.validation_report or {},
        "selected": candidate.selected,
        "execution_status": candidate.execution_status,
        "row_count": candidate.row_count,
        "error_message": candidate.error_message,
        "executed_at": candidate.executed_at,
    }
    if include_result:
        payload["rows"] = candidate.result_rows or []
    return payload


def serialize_draft(draft: SQLQueryDraft, candidates: list[SQLQueryCandidate]) -> dict[str, Any]:
    return {
        "id": draft.id,
        "data_source_id": draft.data_source_id,
        "question": draft.question,
        "group_type": draft.group_type,
        "status": draft.status,
        "dialect": draft.dialect,
        "schema_fingerprint": draft.schema_fingerprint,
        "selected_candidate_ids": draft.selected_candidate_ids or [],
        "execution_summary": draft.execution_summary or {},
        "expires_at": draft.expires_at,
        "created_at": draft.created_at,
        "candidates": [serialize_candidate(item) for item in candidates],
    }


async def load_scoped_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    for_update: bool = False,
) -> tuple[SQLQueryDraft, list[SQLQueryCandidate]]:
    draft_stmt = select(SQLQueryDraft).where(
        SQLQueryDraft.id == draft_id,
        SQLQueryDraft.user_id == user_id,
        SQLQueryDraft.tenant_id == tenant_id,
        SQLQueryDraft.workspace_id == workspace_id,
    )
    if for_update:
        draft_stmt = draft_stmt.with_for_update()
    draft = await db.scalar(draft_stmt)
    if draft is None:
        raise NotFoundException("SQL 查询草案不存在")
    candidates = list(
        (
            await db.execute(
                select(SQLQueryCandidate)
                .where(SQLQueryCandidate.draft_id == draft.id)
                .order_by(SQLQueryCandidate.position)
            )
        )
        .scalars()
        .all()
    )
    return draft, candidates


async def execute_sql_query_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    candidate_ids: list[str] | None = None,
    execute_all: bool = False,
) -> dict[str, Any]:
    draft, candidates = await load_scoped_draft(
        db,
        draft_id=draft_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        for_update=True,
    )
    source = await get_accessible_data_source(
        db,
        user_id=user_id,
        tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
        data_source_id=draft.data_source_id,
        required_permission="query",
        active_only=True,
    )
    if source is None:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="无权执行该数据源查询")
    await _validate_project_scope(
        db,
        project_id=draft.project_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=draft.data_source_id,
    )
    if draft.expires_at and draft.expires_at < datetime.now(UTC):
        draft.status = "expired"
        await db.commit()
        raise ValidationException("SQL 查询草案已过期，请重新生成")

    current_schema = await load_schema_inspection(db, draft.data_source_id)
    current_fingerprint = schema_fingerprint(current_schema.schema_payload)
    if draft.schema_fingerprint != current_fingerprint:
        raise ValidationException(
            "数据源 Schema 已变化，请重新生成 SQL 草案",
            details={
                "reason": "schema_changed",
                "draft_fingerprint": draft.schema_fingerprint,
                "current_fingerprint": current_fingerprint,
            },
        )

    requested = {str(item) for item in (candidate_ids or []) if str(item)}
    selected = candidates if execute_all else [item for item in candidates if item.id in requested]
    if not execute_all and not requested:
        raise ValidationException("请选择需要执行的 SQL 候选")
    if not selected or (not execute_all and len(selected) != len(requested)):
        raise ValidationException("候选 SQL 不属于该草案")
    if len(selected) > MAX_DRAFT_CANDIDATES:
        raise ValidationException(f"单次最多执行 {MAX_DRAFT_CANDIDATES} 条 SQL")

    selected_ids = [item.id for item in selected]
    if draft.status == "executing":
        raise ValidationException("SQL 查询草案正在执行，请稍后查看结果")
    to_execute = [item for item in selected if item.execution_status == "pending"]
    if not to_execute:
        return serialize_draft(draft, candidates)

    sensitive = await _sensitive_columns(db, draft.data_source_id)
    for candidate in to_execute:
        if _hash_text(candidate.sql) != candidate.sql_hash:
            raise ValidationException(
                "候选 SQL 完整性校验失败",
                details={"reason": "sql_hash_mismatch", "candidate_id": candidate.id},
            )
        try:
            _validated_candidate(
                candidate.sql,
                dialect=draft.dialect,
                table_columns=current_schema.column_map,
                sensitive_columns=sensitive,
            )
        except (SQLValidationError, ParseError) as exc:
            raise ValidationException(f"候选 SQL 重新校验失败：{exc}") from exc

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
    draft.status = "executing"
    draft.selected_candidate_ids = sorted(
        set(draft.selected_candidate_ids or []).union(selected_ids)
    )
    for candidate in to_execute:
        candidate.selected = True
        candidate.execution_status = "executing"
    await db.commit()

    for candidate in to_execute:
        try:
            rows = await SQLExecutor().run_on_dsn(
                dsn, candidate.sql, source_type=source.source_type
            )
            candidate.result_rows = rows
            candidate.row_count = len(rows)
            candidate.execution_status = "completed"
            candidate.error_message = None
        except Exception as exc:  # noqa: BLE001 - 每条候选独立记录，允许部分失败
            candidate.result_rows = []
            candidate.row_count = 0
            candidate.execution_status = "failed"
            candidate.error_message = str(exc)[:2000]
        candidate.executed_at = datetime.now(UTC)
        await db.commit()

    selected_history = [
        item for item in candidates if item.id in set(draft.selected_candidate_ids or [])
    ]
    succeeded = sum(1 for item in selected_history if item.execution_status == "completed")
    failed = sum(1 for item in selected_history if item.execution_status == "failed")
    draft.status = "completed" if failed == 0 else "partially_failed" if succeeded else "failed"
    draft.execution_summary = {
        "requested": len(selected_history),
        "succeeded": succeeded,
        "failed": failed,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    await db.commit()
    return serialize_draft(draft, candidates)
