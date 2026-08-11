"""SQL 资产解析、检索、查询草案生成与受控执行。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp, parse, parse_one
from sqlglot.errors import OptimizeError, ParseError, SchemaError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.sql_executor import SQLExecutor
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes, NotFoundException, ValidationException
from infra.metadata.schema_inspector import build_schema_hint, load_schema_inspection
from infra.security.data_source_secrets import decrypt_data_source_secret
from infra.security.resource_scope import get_accessible_data_source
from infra.storage.models import (
    DataSource,
    MetricDefinition,
    MetricLineage,
    Project,
    SchemaMetadata,
    SQLAsset,
    SQLAssetSource,
    SQLQueryCandidate,
    SQLQueryDraft,
    TableRelationship,
)
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator

if TYPE_CHECKING:
    from data_agent.contracts import DataSourceDecision

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_BATCH_UPLOAD_FILES = 100
MAX_BATCH_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ASSET_STATEMENTS = 200
MAX_DRAFT_CANDIDATES = 5
MAX_RESULT_BYTES = 512 * 1024
EXECUTION_STALE_AFTER = timedelta(minutes=5)
PARSER_VERSION = "sqlglot-v1"

_ASSET_STATUS_TRANSITIONS = {
    "draft": {"draft", "published", "rejected"},
    "published": {"published", "deprecated"},
    "deprecated": {"deprecated", "published"},
    "rejected": {"rejected", "draft"},
}
CORPUS_ROLES = {"retrieval", "evaluation", "quarantine"}
QUALITY_STATUSES = {"unverified", "verified", "failed", "deprecated"}


@dataclass(frozen=True)
class ParsedSQLAsset:
    statement_index: int
    normalized_sql: str
    sql_hash: str
    structure_hash: str
    statement_type: str
    asset_type: str
    executable: bool
    tables: list[str]
    columns: list[str]
    parameters: dict[str, Any]
    lineage: dict[str, Any]
    title: str
    description: str
    tags: list[str]
    knowledge_metadata: dict[str, Any]
    domain: str
    owner: str
    risk_flags: list[str]
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


def _legacy_schema_fingerprint(schema_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        schema_payload or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return _hash_text(canonical)


def _normalized_schema_structure(
    schema_payload: dict[str, Any],
    sensitive_columns: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    payload = schema_payload if isinstance(schema_payload, dict) else {}
    tables = payload.get("tables")
    if not isinstance(tables, list):
        nested = payload.get("schema")
        tables = nested.get("tables") if isinstance(nested, dict) else []
    if not isinstance(tables, list):
        tables = []

    sensitive = {
        (str(table).strip().lower(), str(column).strip().lower())
        for table, column in (sensitive_columns or set())
    }
    normalized_tables: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name") or "").strip().lower()
        if not table_name:
            continue
        normalized_columns: list[dict[str, Any]] = []
        columns = table.get("columns")
        if isinstance(columns, list):
            for column in columns:
                if not isinstance(column, dict):
                    continue
                column_name = str(column.get("name") or "").strip().lower()
                if not column_name:
                    continue
                column_type = re.sub(
                    r"\s+",
                    "",
                    str(column.get("type") or column.get("data_type") or "").lower(),
                )
                is_sensitive = bool(
                    column.get("is_sensitive")
                    or column.get("sensitive")
                    or (table_name, column_name) in sensitive
                )
                normalized_columns.append(
                    {
                        "name": column_name,
                        "type": column_type,
                        "sensitive": is_sensitive,
                    }
                )
        normalized_columns.sort(key=lambda item: (item["name"], item["type"]))
        normalized_tables.append({"name": table_name, "columns": normalized_columns})

    if not normalized_tables:
        for key in ("table_names", "tables_names", "names"):
            names = payload.get(key)
            if isinstance(names, list):
                normalized_tables.extend(
                    {"name": str(name).strip().lower(), "columns": []}
                    for name in names
                    if str(name).strip()
                )
                break
    normalized_tables.sort(key=lambda item: item["name"])
    schema_name = payload.get("schema")
    if isinstance(schema_name, dict):
        schema_name = schema_name.get("name")
    return {
        "schema": str(schema_name or "").strip().lower(),
        "tables": normalized_tables,
    }


def schema_fingerprint(
    schema_payload: dict[str, Any],
    sensitive_columns: set[tuple[str, str]] | None = None,
) -> str:
    """仅对影响 SQL 正确性与数据安全的 Schema 结构生成指纹。"""

    canonical = json.dumps(
        _normalized_schema_structure(schema_payload, sensitive_columns),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _hash_text(canonical)


def schema_fingerprint_matches(
    stored_fingerprint: str | None,
    schema_payload: dict[str, Any],
    sensitive_columns: set[tuple[str, str]] | None = None,
) -> bool:
    if not stored_fingerprint:
        return False
    return stored_fingerprint in {
        schema_fingerprint(schema_payload, sensitive_columns),
        _legacy_schema_fingerprint(schema_payload),
    }


def validate_asset_status_transition(current_status: str, target_status: str) -> None:
    allowed = _ASSET_STATUS_TRANSITIONS.get(str(current_status), {str(current_status)})
    if target_status not in allowed:
        raise ValidationException(f"SQL 资产状态不能从 {current_status} 变更为 {target_status}")


def _bounded_result_rows(
    rows: list[dict[str, Any]], *, max_bytes: int = MAX_RESULT_BYTES
) -> tuple[list[dict[str, Any]], bool]:
    """按 JSON 字节预算保存完整行，避免单个结果撑大数据库和 API 响应。"""

    budget = max(2, int(max_bytes))
    used = 2
    bounded: list[dict[str, Any]] = []
    for row in rows:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        delimiter = 1 if bounded else 0
        if used + delimiter + len(encoded) > budget:
            break
        bounded.append(row)
        used += delimiter + len(encoded)
    return bounded, len(bounded) < len(rows)


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


_DOCUMENTATION_KEY_ALIASES = {
    "title": "title",
    "name": "title",
    "标题": "title",
    "description": "description",
    "summary": "description",
    "logic": "description",
    "说明": "description",
    "描述": "description",
    "逻辑": "description",
    "tags": "tags",
    "tag": "tags",
    "标签": "tags",
    "questions": "questions",
    "question": "questions",
    "examples": "questions",
    "问题": "questions",
    "metrics": "metrics",
    "metric": "metrics",
    "指标": "metrics",
    "dimensions": "dimensions",
    "dimension": "dimensions",
    "维度": "dimensions",
    "joins": "joins",
    "join": "joins",
    "关联": "joins",
    "time-column": "time_columns",
    "time_column": "time_columns",
    "time-columns": "time_columns",
    "时间字段": "time_columns",
    "grain": "grain",
    "粒度": "grain",
    "parameters": "documented_parameters",
    "params": "documented_parameters",
    "参数": "documented_parameters",
    "filters": "filters",
    "filter": "filters",
    "过滤": "filters",
    "assumptions": "assumptions",
    "assumption": "assumptions",
    "假设": "assumptions",
    "domain": "domain",
    "业务域": "domain",
    "owner": "owner",
    "负责人": "owner",
}


def _comment_lines(expression: Any) -> list[str]:
    comments: list[str] = []
    seen: set[str] = set()
    for node in expression.walk():
        for raw in getattr(node, "comments", None) or []:
            value = str(raw or "").strip()
            if value and value not in seen:
                seen.add(value)
                comments.append(value)
    lines: list[str] = []
    for comment in comments:
        for raw_line in comment.splitlines():
            line = re.sub(r"^\s*\*\s?", "", raw_line).strip()
            if line:
                lines.append(line)
    return lines


def _split_documentation_values(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            item.strip() for item in re.split(r"[,，;；|]", str(value or "")) if item.strip()
        )
    )


def _parse_named_expressions(value: str, *, formula_key: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in re.split(r"[;；\n]", str(value or "")):
        text = item.strip()
        if not text:
            continue
        if "=" not in text:
            items.append({"name": text, formula_key: ""})
            continue
        name, expression = text.split("=", 1)
        items.append({"name": name.strip(), formula_key: expression.strip()})
    return [item for item in items if item["name"]]


def _parse_dimensions(value: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _parse_named_expressions(value, formula_key="column_ref"):
        reference = item.get("column_ref", "")
        table_name, _, column_name = reference.rpartition(".")
        result.append(
            {
                "name": item["name"],
                "table": table_name,
                "column": column_name or reference,
            }
        )
    return result


def _parse_joins(value: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in re.split(r"[;；\n]", str(value or "")):
        text = item.strip()
        if "=" not in text:
            continue
        left, right = (part.strip() for part in text.split("=", 1))
        left_table, _, left_column = left.rpartition(".")
        right_table, _, right_column = right.rpartition(".")
        if all((left_table, left_column, right_table, right_column)):
            result.append(
                {
                    "left_table": left_table,
                    "left_column": left_column,
                    "right_table": right_table,
                    "right_column": right_column,
                    "join_type": "INNER",
                }
            )
    return result


def _filter_policy(value: str, *, intrinsic: bool = False) -> str:
    """区分指标固有条件与只在用户明确提及时才能复用的上下文条件。"""

    if intrinsic:
        return "required"
    text = str(value or "").strip().lower()
    if re.search(
        r"(?:^|[.\s(])(?:[a-z_][a-z0-9_]*_at|[a-z_][a-z0-9_]*_date|"
        r"created_at|updated_at|paid_at|date|time)(?:\s|[<>=])",
        text,
    ) or re.search(r"\b20\d{2}[-/]\d{1,2}(?:[-/]\d{1,2})?\b", text):
        return "explicit_only"
    if re.search(r"(?:^|[.\s(])(?:[a-z_][a-z0-9_]*_id)\s*=\s*", text):
        return "explicit_only"
    if re.search(r"(?:^|[.\s(])(?:status|state|is_test|is_demo|is_dummy|test_flag)\b", text):
        return "required"
    return "contextual"


def _extract_ast_knowledge(expression: Any) -> dict[str, Any]:
    """从已解析 SQL 提取可审计的指标、过滤、JOIN、粒度和时间字段候选。

    这里记录的是 SQL 中已经存在的事实，不把模型猜测混入资产知识。后续
    生成 SQL 时可以据此组合指标和 JOIN；固定过滤条件会单独标记为候选，
    避免把历史查询的日期或状态值静默带入新问题。
    """

    def physical_table_name(table: Any) -> str:
        name = str(table.name or "").strip()
        database = str(table.db or "").strip()
        return f"{database}.{name}" if database and name else name

    cte_names = {
        str(cte.alias_or_name or "").strip().lower()
        for cte in expression.find_all(exp.CTE)
        if str(cte.alias_or_name or "").strip()
    }
    table_aliases = {
        str(table.alias_or_name or "").strip(): physical_table_name(table)
        for table in expression.find_all(exp.Table)
        if str(table.alias_or_name or "").strip() and physical_table_name(table)
    }
    scopes = {id(scope.expression): scope for scope in traverse_scope(expression)}

    def resolve_column(scope: Any, column: Any, seen: set[tuple[int, str]]) -> set[str]:
        if scope is None:
            return set()
        qualifier = str(column.table or "").strip()
        column_name = str(column.name or "").strip()
        identity = (id(scope), f"{qualifier}.{column_name}")
        if not column_name or identity in seen:
            return set()
        seen.add(identity)
        sources = dict(getattr(scope, "sources", {}) or {})
        source = sources.get(qualifier) if qualifier else None
        if source is None and not qualifier and len(sources) == 1:
            source = next(iter(sources.values()))
        if isinstance(source, exp.Table):
            table_name = physical_table_name(source)
            return {f"{table_name}.{column_name}"} if table_name else set()
        source_expression = getattr(source, "expression", None)
        if isinstance(source_expression, exp.Select):
            for projection in source_expression.selects:
                if str(projection.alias_or_name or "").strip() != column_name:
                    continue
                formula = projection.this if isinstance(projection, exp.Alias) else projection
                resolved: set[str] = set()
                for dependency in formula.find_all(exp.Column):
                    resolved.update(resolve_column(source, dependency, seen))
                return resolved
        fallback_table = table_aliases.get(qualifier, qualifier)
        return {f"{fallback_table}.{column_name}"} if fallback_table else {column_name}

    joins: list[dict[str, str]] = []
    for join in expression.find_all(exp.Join):
        on_expression = join.args.get("on")
        if on_expression is None:
            continue
        for equality in on_expression.find_all(exp.EQ):
            left = equality.this
            right = equality.expression
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                continue
            if not all((left.table, left.name, right.table, right.name)):
                continue
            joins.append(
                {
                    "left_table": table_aliases.get(str(left.table), str(left.table)),
                    "left_column": str(left.name),
                    "right_table": table_aliases.get(str(right.table), str(right.table)),
                    "right_column": str(right.name),
                    "join_type": str(
                        join.args.get("side") or join.args.get("kind") or "INNER"
                    ).upper(),
                }
            )

    metrics: list[dict[str, str]] = []
    metric_rules: list[dict[str, Any]] = []
    dimensions: list[dict[str, str]] = []
    filters: list[str] = []
    filter_contracts: list[dict[str, str]] = []
    grains: list[str] = []

    def expression_sql(node: Any) -> str:
        return str(node.sql(comments=False)).strip() if node is not None else ""

    def unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    def metric_name(formula_expression: Any, aggregate: Any) -> str:
        explicit = str(getattr(formula_expression, "alias_or_name", "") or "").strip()
        if explicit:
            return explicit
        aggregate_name = type(aggregate).__name__.lower()
        argument = getattr(aggregate, "this", None)
        if isinstance(argument, exp.Column):
            suffix = str(argument.name or "").strip()
            return f"{aggregate_name}_{suffix}" if suffix else f"{aggregate_name}_value"
        if isinstance(argument, exp.Distinct):
            column = next(argument.find_all(exp.Column), None)
            suffix = str(column.name or "").strip() if column is not None else "value"
            return f"{aggregate_name}_distinct_{suffix}"
        if isinstance(argument, exp.Star) or aggregate_name == "count":
            return "count_rows"
        return aggregate_name

    for query in expression.find_all(exp.Select):
        local_tables = sorted(
            {
                physical_table_name(table)
                for table in query.find_all(exp.Table)
                if physical_table_name(table)
                and str(table.name or "").strip().lower() not in cte_names
            }
        )
        query_filters: list[str] = []
        for clause_name in ("where", "having"):
            clause = query.args.get(clause_name)
            if clause is not None:
                value = expression_sql(getattr(clause, "this", clause))
                if value:
                    query_filters.append(value)
                    filters.append(value)
                    filter_contracts.append(
                        {
                            "expression": value,
                            "policy": _filter_policy(value),
                            "source": clause_name,
                        }
                    )
        group = query.args.get("group")
        if group is not None:
            group_columns = [
                column for column in group.find_all(exp.Column) if str(column.name or "").strip()
            ]
            for column in group_columns:
                dimensions.append(
                    {
                        "name": str(column.alias_or_name or column.name),
                        "table": str(column.table or ""),
                        "column": str(column.name or ""),
                    }
                )
            if len(group_columns) == 1:
                grains.append(str(group_columns[0].name or "").strip())
            elif group_columns:
                grains.append("、".join(str(column.name or "").strip() for column in group_columns))

        for selection in query.selects:
            aggregate = next(
                (node for node in selection.walk() if isinstance(node, exp.AggFunc)), None
            )
            if aggregate is None:
                continue
            formula_expression = selection.this if isinstance(selection, exp.Alias) else selection
            formula = expression_sql(formula_expression)
            name = metric_name(selection, aggregate)
            if not formula or not name:
                continue
            metric_filters = list(query_filters)
            for filter_node in formula_expression.find_all(exp.Filter):
                condition = expression_sql(
                    getattr(filter_node.args.get("expression"), "this", None)
                )
                if condition:
                    metric_filters.append(condition)
                    filter_contracts.append(
                        {
                            "expression": condition,
                            "policy": "required",
                            "source": "metric_filter",
                        }
                    )
            for case_node in formula_expression.find_all(exp.Case):
                for branch in case_node.args.get("ifs") or []:
                    condition = expression_sql(branch.args.get("this"))
                    if condition:
                        metric_filters.append(condition)
                        filter_contracts.append(
                            {
                                "expression": condition,
                                "policy": "required",
                                "source": "case_when",
                            }
                        )
            source_columns: list[str] = []
            query_scope = scopes.get(id(query))
            for column in formula_expression.find_all(exp.Column):
                source_columns.extend(resolve_column(query_scope, column, set()))
            source_columns = sorted(set(source_columns))
            source_tables = (
                sorted(
                    {
                        reference.rsplit(".", 1)[0]
                        for reference in source_columns
                        if "." in reference
                    }
                )
                or local_tables
            )
            metrics.append({"name": name, "formula": formula})
            metric_rules.append(
                {
                    "name": name,
                    "formula": formula,
                    "aggregation": type(aggregate).__name__.upper(),
                    "source_columns": source_columns,
                    "source_tables": source_tables,
                    "filters": unique(metric_filters),
                    "filter_contracts": [
                        item
                        for item in filter_contracts
                        if item["expression"] in set(metric_filters)
                    ],
                    "grain": grains[-1] if grains else "",
                }
            )

    time_columns = sorted(
        {
            f"{column.table}.{column.name}" if column.table else str(column.name)
            for column in expression.find_all(exp.Column)
            if re.search(r"(^|_)(at|time|date|day|month|year)($|_)", str(column.name), re.I)
        }
    )
    return {
        "joins": joins,
        "metrics": metrics,
        "metric_rules": metric_rules,
        "dimensions": dimensions,
        "time_columns": time_columns,
        "filters": unique(filters),
        "filter_contracts": list(
            {
                (item["expression"], item["policy"], item["source"]): item
                for item in filter_contracts
            }.values()
        ),
        "grains": unique(grains),
    }


def _merge_named_metadata(
    primary: list[dict[str, Any]], inferred: list[dict[str, Any]], *, key: str
) -> list[dict[str, Any]]:
    merged = list(primary)
    positions = {
        str(item.get(key) or "").strip().lower(): index for index, item in enumerate(merged)
    }
    for item in inferred:
        identity = str(item.get(key) or "").strip().lower()
        if not identity:
            continue
        if identity in positions:
            current = dict(merged[positions[identity]])
            for field, value in item.items():
                if field not in current or not current[field]:
                    current[field] = value
                elif isinstance(current[field], list) and isinstance(value, list):
                    current[field] = list(dict.fromkeys([*current[field], *value]))
            merged[positions[identity]] = current
        else:
            positions[identity] = len(merged)
            merged.append(item)
    return merged


def _extract_asset_documentation(expression: Any) -> dict[str, Any]:
    """从 SQL 注释读取结构化知识；普通说明也会进入 description。"""

    raw_values: dict[str, list[str]] = {}
    narrative: list[str] = []
    active_key: str | None = None
    for line in _comment_lines(expression):
        match = re.match(r"^@([^:：]+)\s*[:：]\s*(.*)$", line)
        if match:
            normalized_key = _DOCUMENTATION_KEY_ALIASES.get(match.group(1).strip().lower())
            if normalized_key:
                active_key = normalized_key
                raw_values.setdefault(normalized_key, []).append(match.group(2).strip())
                continue
        if active_key == "description" and raw_values.get(active_key):
            raw_values[active_key][-1] = f"{raw_values[active_key][-1]}\n{line}".strip()
        else:
            active_key = None
            narrative.append(line)

    title = " ".join(raw_values.get("title", [])).strip()
    descriptions = [value for value in raw_values.get("description", []) if value]
    if narrative:
        descriptions.extend(narrative)
        if not title:
            title = narrative[0][:255]
    description = "\n".join(dict.fromkeys(descriptions)).strip()
    tags = _split_documentation_values(",".join(raw_values.get("tags", [])))
    questions = _split_documentation_values("；".join(raw_values.get("questions", [])))
    metrics: list[dict[str, str]] = []
    for value in raw_values.get("metrics", []):
        metrics.extend(_parse_named_expressions(value, formula_key="formula"))
    dimensions: list[dict[str, str]] = []
    for value in raw_values.get("dimensions", []):
        dimensions.extend(_parse_dimensions(value))
    joins: list[dict[str, str]] = []
    for value in raw_values.get("joins", []):
        joins.extend(_parse_joins(value))
    time_columns = _split_documentation_values(",".join(raw_values.get("time_columns", [])))
    documented_parameters = _split_documentation_values(
        ",".join(raw_values.get("documented_parameters", []))
    )
    assumptions = _split_documentation_values("；".join(raw_values.get("assumptions", [])))
    inferred = _extract_ast_knowledge(expression)
    metrics = _merge_named_metadata(metrics, inferred["metrics"], key="name")
    # 保留兼容的简短 metrics 结构；规则使用独立副本承载来源、过滤和粒度契约。
    metric_rules = _merge_named_metadata(
        [dict(item) for item in metrics], inferred.get("metric_rules", []), key="name"
    )
    dimensions = _merge_named_metadata(dimensions, inferred["dimensions"], key="name")
    join_keys = {
        (
            item.get("left_table"),
            item.get("left_column"),
            item.get("right_table"),
            item.get("right_column"),
        )
        for item in joins
    }
    joins.extend(
        item
        for item in inferred["joins"]
        if (
            item.get("left_table"),
            item.get("left_column"),
            item.get("right_table"),
            item.get("right_column"),
        )
        not in join_keys
    )
    time_columns = list(dict.fromkeys([*time_columns, *inferred["time_columns"]]))
    filters = _split_documentation_values("；".join(raw_values.get("filters", [])))
    filters = list(dict.fromkeys([*filters, *inferred.get("filters", [])]))
    documented_filter_contracts = [
        {"expression": value, "policy": "required", "source": "sql_comments"}
        for value in _split_documentation_values("；".join(raw_values.get("filters", [])))
    ]
    filter_contracts = list(
        {
            (
                str(item.get("expression") or ""),
                str(item.get("policy") or "contextual"),
                str(item.get("source") or "ast"),
            ): item
            for item in [*(inferred.get("filter_contracts") or []), *documented_filter_contracts]
            if str(item.get("expression") or "").strip()
        }.values()
    )
    # 文档中的过滤口径是资产作者显式声明的指标条件，复制到每条指标契约。
    for rule in metric_rules:
        if not isinstance(rule, dict):
            continue
        rule_contracts = list(rule.get("filter_contracts") or [])
        known = {str(item.get("expression") or "") for item in rule_contracts}
        for item in documented_filter_contracts:
            if item["expression"] not in known:
                rule_contracts.append(item)
        rule["filter_contracts"] = rule_contracts
        rule["filters"] = list(
            dict.fromkeys(
                [
                    *(
                        str(value).strip()
                        for value in rule.get("filters") or []
                        if str(value).strip()
                    ),
                    *(item["expression"] for item in documented_filter_contracts),
                ]
            )
        )
    inferred_grains = inferred.get("grains") or []
    grain = " ".join(raw_values.get("grain", [])).strip() or (
        inferred_grains[0] if inferred_grains else ""
    )
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "knowledge_metadata": {
            "questions": questions,
            "metrics": metrics,
            "metric_rules": metric_rules,
            "dimensions": dimensions,
            "joins": joins,
            "time_columns": time_columns,
            "grain": grain,
            "documented_parameters": documented_parameters,
            "filters": filters,
            "filter_contracts": filter_contracts,
            "assumptions": assumptions,
            "source": "sql_comments",
            "ast_inferred": True,
        },
        "domain": " ".join(raw_values.get("domain", [])).strip()[:100],
        "owner": " ".join(raw_values.get("owner", [])).strip()[:255],
    }


def _sql_structure_hash(expression: Any, *, dialect: str) -> str:
    """用 AST 字面量归一化识别同一模板，避免仅靠 SQL 字符串去重。"""

    literal_types = tuple(
        item
        for item in (
            getattr(exp, "Literal", None),
            getattr(exp, "Boolean", None),
        )
        if item
    )
    normalized = expression.copy().transform(
        lambda node: (
            exp.Placeholder() if literal_types and isinstance(node, literal_types) else node
        )
    )
    canonical = normalized.sql(
        dialect=_sqlglot_dialect(dialect), pretty=False, comments=False, normalize=True
    )
    return _hash_text(canonical)


def _risk_flags(expression: Any, *, description: str = "") -> list[str]:
    flags: set[str] = set()
    if not isinstance(expression, exp.Query):
        flags.add("write_or_ddl")
    if isinstance(expression, exp.Query) and expression.args.get("limit") is None:
        flags.add("missing_limit")
    if any(
        isinstance(selection, exp.Star)
        or (isinstance(selection, exp.Column) and isinstance(selection.this, exp.Star))
        for query in expression.find_all(exp.Select)
        for selection in query.selects
    ):
        flags.add("select_star")
    for literal in expression.find_all(exp.Literal):
        value = str(literal.this or "")
        if literal.is_string and re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", value):
            flags.add("hardcoded_date")
    for equality in expression.find_all(exp.EQ):
        sides = (equality.this, equality.expression)
        if any(
            isinstance(side, exp.Column) and str(side.name).lower().endswith("_id")
            for side in sides
        ) and any(isinstance(side, exp.Literal) for side in sides):
            flags.add("hardcoded_id")
    searchable = f"{description}\n{expression.sql(comments=False)}".lower()
    if re.search(r"(^|[^a-z])(test|demo|dummy)([^a-z]|$)|测试|演示", searchable):
        flags.add("test_condition")
    return sorted(flags)


def _extract_tables_columns(expression: Any) -> tuple[list[str], list[str]]:
    if exp is None:
        return [], []
    table_aliases = {
        str(table.alias_or_name or "").strip(): (
            f"{str(table.db).strip()}.{str(table.name).strip()}"
            if str(table.db or "").strip()
            else str(table.name).strip()
        )
        for table in expression.find_all(exp.Table)
        if str(table.alias_or_name or "").strip() and str(table.name or "").strip()
    }
    tables = sorted(
        {
            (
                f"{str(node.db).strip()}.{str(node.name).strip()}"
                if str(node.db or "").strip()
                else str(node.name).strip()
            )
            for node in expression.find_all(exp.Table)
            if str(node.name).strip()
        }
    )
    columns = sorted(
        {
            (
                f"{table_aliases.get(str(node.table), str(node.table))}.{node.name}"
                if node.table
                else str(node.name)
            ).strip()
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
            write_tables.append(
                f"{target.db}.{target.name}" if str(target.db or "").strip() else str(target.name)
            )
        elif target is not None:
            target_table = next(iter(target.find_all(exp.Table)), None)
            if target_table is not None and target_table.name:
                write_tables.append(
                    f"{target_table.db}.{target_table.name}"
                    if str(target_table.db or "").strip()
                    else str(target_table.name)
                )
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
    unqualified_matches: dict[str, list[str]] = {}
    for name in table_columns:
        unqualified_matches.setdefault(name.rsplit(".", 1)[-1].lower(), []).append(name)
    cte_names = {
        str(cte.alias_or_name).strip().lower()
        for cte in expression.find_all(exp.CTE)
        if str(cte.alias_or_name).strip()
    }
    referenced_tables: list[str] = []
    for table in expression.find_all(exp.Table):
        table_name = str(table.name or "").strip()
        if not table_name:
            continue
        if table_name.lower() in cte_names:
            continue
        schema_name = str(table.db or "").strip().lower()
        if schema_name in {"information_schema", "pg_catalog", "system"}:
            continue
        qualified_name = f"{schema_name}.{table_name}" if schema_name else table_name
        actual = (
            table_lookup.get(qualified_name.lower())
            if schema_name
            else table_lookup.get(table_name.lower())
        )
        if actual is None and not schema_name:
            matches = unqualified_matches.get(table_name.lower(), [])
            if len(matches) == 1:
                actual = matches[0]
            elif len(matches) > 1:
                errors.append(f"存在同名跨库表，请使用 database.table：{table_name}")
                continue
        if actual is None:
            errors.append(f"Schema 中不存在表：{qualified_name}")
            continue
        referenced_tables.append(actual)

    sensitive = {(table.lower(), column.lower()) for table, column in (sensitive_columns or set())}
    has_star = any(
        isinstance(selection, exp.Star)
        or (isinstance(selection, exp.Column) and isinstance(selection.this, exp.Star))
        for selection in getattr(expression, "selects", [])
    )

    # 按每个 SELECT 的可见来源解析字段，避免 CTE 或派生表绕过校验。
    missing_metadata = [
        table_name
        for table_name in dict.fromkeys(referenced_tables)
        if not table_columns.get(table_name)
    ]
    warnings.extend(
        f"表 {table_name} 缺少列元数据，已跳过字段级静态校验" for table_name in missing_metadata
    )
    qualified = None
    if not errors and not missing_metadata:
        try:
            # sqlglot 的列展开按裸表名工作；跨库物理键在上面的引用校验中已完成，
            # 这里将唯一的 database.table 映射到裸表名供字段级校验使用。
            qualify_schema: dict[str, dict[str, str]] = {}
            for physical_name, columns in table_columns.items():
                bare_name = physical_name.rsplit(".", 1)[-1]
                target = qualify_schema.setdefault(bare_name, {})
                target.update({column_name: "UNKNOWN" for column_name in columns})
            qualified = qualify(
                expression.copy(),
                schema=cast(dict[str, object], qualify_schema),
                allow_partial_qualification=False,
                validate_qualify_columns=True,
                expand_stars=True,
                quote_identifiers=False,
                identify=False,
            )
        except (OptimizeError, SchemaError) as exc:
            message = str(exc)
            match = re.search(r"(?:Column|column) ['\"]([^'\"]+)['\"]", message)
            if match is None:
                match = re.search(r"Unknown column:\s*([^\s]+)", message, flags=re.I)
            column_name = match.group(1) if match else ""
            if column_name:
                matching_tables = [
                    table_name
                    for table_name in dict.fromkeys(referenced_tables)
                    if column_name.lower()
                    in {item.lower() for item in table_columns.get(table_name, [])}
                ]
                if len(matching_tables) > 1:
                    errors.append(f"未限定列存在歧义：{column_name}")
                else:
                    errors.append(f"Schema 中不存在列：{column_name}")
            else:
                errors.append(f"Schema 静态校验失败：{message}")

    if qualified is None and missing_metadata and not errors and sensitive:
        # 字段清单不完整时仍按可解析的物理表别名执行敏感字段兜底校验。
        for scope in traverse_scope(expression):
            fallback_aliases: dict[str, str] = {}
            local_tables: set[str] = set()
            fallback_scope: Any = scope
            while fallback_scope is not None:
                for alias, (_, source) in fallback_scope.selected_sources.items():
                    if isinstance(source, exp.Table):
                        actual = table_lookup.get(str(source.name or "").lower())
                        if actual:
                            fallback_aliases.setdefault(str(alias).lower(), actual)
                            if fallback_scope is scope:
                                local_tables.add(actual)
                fallback_scope = fallback_scope.parent
            for column in scope.columns:
                column_name = str(column.name or "").strip().lower()
                qualifier = str(column.table or "").strip().lower()
                fallback_table_name = fallback_aliases.get(qualifier)
                if not qualifier and len(local_tables) == 1:
                    fallback_table_name = next(iter(local_tables))
                if (
                    fallback_table_name
                    and (
                        fallback_table_name.lower(),
                        column_name,
                    )
                    in sensitive
                ):
                    errors.append(f"查询直接引用敏感字段：{fallback_table_name}.{column.name}")
            scope_has_star = any(
                isinstance(selection, exp.Star)
                or (isinstance(selection, exp.Column) and isinstance(selection.this, exp.Star))
                for selection in getattr(scope.expression, "selects", [])
            )
            if scope_has_star and any(
                table_name.lower() in {item[0] for item in sensitive} for table_name in local_tables
            ):
                errors.append("查询包含 SELECT *，且涉及配置了敏感字段的表")

    if qualified is not None:
        # 逐级合并父作用域，覆盖相关子查询对外层表的字段引用。
        sensitive_reference_found = False
        for scope in traverse_scope(qualified):
            qualified_aliases: dict[str, str] = {}
            qualified_scope: Any = scope
            while qualified_scope is not None:
                for alias, (_, source) in qualified_scope.selected_sources.items():
                    if isinstance(source, exp.Table):
                        actual = table_lookup.get(str(source.name or "").lower())
                        if actual:
                            qualified_aliases.setdefault(str(alias).lower(), actual)
                qualified_scope = qualified_scope.parent
            for column in scope.columns:
                column_name = str(column.name or "").strip().lower()
                qualifier = str(column.table or "").strip().lower()
                qualified_table_name = qualified_aliases.get(qualifier)
                if (
                    qualified_table_name
                    and (
                        qualified_table_name.lower(),
                        column_name,
                    )
                    in sensitive
                ):
                    sensitive_reference_found = True
                    errors.append(f"查询直接引用敏感字段：{qualified_table_name}.{column.name}")
        if has_star and sensitive_reference_found:
            errors.append("查询包含 SELECT *，且涉及配置了敏感字段的表")
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
        documentation = _extract_asset_documentation(statement)
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
            # ETL/DDL 只做知识学习，仍必须证明所有读写表和字段属于当前数据源。
            # 失败语句保留在隔离区供审计，但不会进入知识晋升或线上检索。
            schema_errors, schema_warnings = _validate_schema_references(
                statement,
                table_columns=table_columns or {},
                sensitive_columns=sensitive_columns,
            )
            errors.extend(schema_errors)
            warnings.extend(schema_warnings)
            warnings.append("非只读语句仅用于血缘参考，不允许发布为在线执行资产")
        parsed.append(
            ParsedSQLAsset(
                statement_index=index,
                normalized_sql=safe_sql,
                sql_hash=_hash_text(safe_sql),
                structure_hash=_sql_structure_hash(statement, dialect=dialect),
                statement_type=_statement_type(statement),
                asset_type=_asset_type(statement),
                executable=executable and not errors,
                tables=tables,
                columns=columns,
                parameters=_extract_parameters(statement),
                lineage=_lineage(statement, tables, columns),
                title=documentation["title"],
                description=documentation["description"],
                tags=documentation["tags"],
                knowledge_metadata=documentation["knowledge_metadata"],
                domain=documentation["domain"],
                owner=documentation["owner"],
                risk_flags=_risk_flags(statement, description=documentation["description"]),
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


async def evaluate_data_source_schema_fingerprint(
    db: AsyncSession,
    *,
    data_source_id: str,
    schema_payload: dict[str, Any],
    stored_fingerprint: str | None,
) -> tuple[bool, str]:
    sensitive = await _sensitive_columns(db, data_source_id)
    return (
        schema_fingerprint_matches(stored_fingerprint, schema_payload, sensitive),
        schema_fingerprint(schema_payload, sensitive),
    )


async def promote_sql_asset_knowledge(
    db: AsyncSession,
    *,
    asset: SQLAsset,
    user_id: str,
) -> dict[str, int]:
    """把范围校验通过的 SQL 事实转成待审核知识候选，不直接发布指标或关系。

    ETL 也可以调用本函数学习其中的 SELECT、聚合和 JOIN，但 ETL 本身始终
    保持 quarantine/executable=False，不能成为检索模板或执行候选。
    """

    metadata = asset.knowledge_metadata or {}
    stats = {"metrics_created": 0, "relationships_created": 0, "annotations_suggested": 0}
    source_ref = f"sql_asset:{asset.id}"
    inspection = await load_schema_inspection(db, asset.data_source_id)
    physical_columns = inspection.column_map

    def valid_reference(table_name: str, column_name: str) -> bool:
        if column_name in set(physical_columns.get(table_name, [])):
            return True
        unqualified = [
            columns
            for physical_table, columns in physical_columns.items()
            if physical_table.rsplit(".", 1)[-1] == table_name
        ]
        return len(unqualified) == 1 and column_name in set(unqualified[0])

    metric_candidates = metadata.get("metric_rules") or metadata.get("metrics") or []
    for metric in metric_candidates:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name") or "").strip()
        formula = str(metric.get("formula") or "").strip()
        if not name or not formula:
            continue
        existing = await db.scalar(
            select(MetricDefinition).where(
                MetricDefinition.data_source_id == asset.data_source_id,
                MetricDefinition.name == name,
                MetricDefinition.status.in_(["draft", "published"]),
            )
        )
        if existing is not None:
            continue
        underlying_columns = sorted(
            {
                *(
                    str(column).strip()
                    for column in metric.get("source_columns") or []
                    if str(column).strip()
                ),
                *(
                    match.group(0)
                    for match in re.finditer(
                        r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\b", formula
                    )
                    if (
                        not metric.get("source_columns")
                        or match.group(0).split(".", 1)[0].lower()
                        in {
                            str(table).lower()
                            for table in [
                                *(getattr(asset, "tables", None) or []),
                                *physical_columns.keys(),
                            ]
                        }
                    )
                ),
            }
        )
        if any("." not in reference for reference in underlying_columns):
            # 多表查询中的裸字段无法安全归属到某一张物理表，留给人工审核。
            continue
        if underlying_columns and any(
            not valid_reference(*reference.rsplit(".", 1)) for reference in underlying_columns
        ):
            continue
        metric_id = str(uuid.uuid4())
        metric_filters = [
            str(item).strip() for item in metric.get("filters") or [] if str(item).strip()
        ]
        logic_parts = [asset.description.strip() if asset.description else ""]
        if metric_filters:
            logic_parts.append("过滤条件：" + "；".join(dict.fromkeys(metric_filters)))
        if str(metric.get("grain") or "").strip():
            logic_parts.append("查询粒度：" + str(metric["grain"]).strip())
        if str(metric.get("aggregation") or "").strip():
            logic_parts.append("聚合方式：" + str(metric["aggregation"]).strip())
        db.add(
            MetricDefinition(
                id=metric_id,
                data_source_id=asset.data_source_id,
                name=name,
                aliases=[],
                formula=formula,
                underlying_columns=underlying_columns,
                agg_function=str(metric.get("aggregation") or "").strip() or None,
                business_definition="；".join(part for part in logic_parts if part) or None,
                tags=asset.tags or [],
                status="draft",
                version=1,
                created_by=user_id,
            )
        )
        for column in underlying_columns:
            db.add(
                MetricLineage(
                    id=str(uuid.uuid4()),
                    metric_id=metric_id,
                    depends_on_column=column,
                    transformation=formula,
                    lineage_type="sql_asset_inferred",
                )
            )
        stats["metrics_created"] += 1

    for relationship in metadata.get("joins") or []:
        if not isinstance(relationship, dict):
            continue
        left_table = str(relationship.get("left_table") or "").strip()
        left_column = str(relationship.get("left_column") or "").strip()
        right_table = str(relationship.get("right_table") or "").strip()
        right_column = str(relationship.get("right_column") or "").strip()
        if not all((left_table, left_column, right_table, right_column)):
            continue
        if not valid_reference(left_table, left_column) or not valid_reference(
            right_table, right_column
        ):
            continue
        existing = await db.scalar(
            select(TableRelationship).where(
                TableRelationship.data_source_id == asset.data_source_id,
                TableRelationship.left_table == left_table,
                TableRelationship.left_column == left_column,
                TableRelationship.right_table == right_table,
                TableRelationship.right_column == right_column,
            )
        )
        if existing is not None:
            continue
        db.add(
            TableRelationship(
                id=str(uuid.uuid4()),
                data_source_id=asset.data_source_id,
                left_table=left_table,
                left_column=left_column,
                right_table=right_table,
                right_column=right_column,
                join_type=str(relationship.get("join_type") or "LEFT").upper(),
                is_verified=False,
            )
        )
        stats["relationships_created"] += 1

    from services.schema_annotations import suggest_column_annotation

    for dimension in metadata.get("dimensions") or []:
        if not isinstance(dimension, dict):
            continue
        name = str(dimension.get("name") or "").strip()
        table_name = str(dimension.get("table") or "").strip()
        column_name = str(dimension.get("column") or "").strip()
        if not all((name, table_name, column_name)):
            continue
        if not valid_reference(table_name, column_name):
            continue
        outcome = await suggest_column_annotation(
            db,
            data_source_id=asset.data_source_id,
            table_name=table_name,
            column_name=column_name,
            candidate={
                "business_name": name,
                "business_description": asset.description or None,
                "aliases": [name],
                "tags": asset.tags or [],
                "semantic_type": "dimension",
                "is_dimension_column": True,
            },
            source="sql_asset",
            confidence=0.9,
            source_ref=source_ref,
            fingerprint=asset.schema_fingerprint,
        )
        if outcome in {"created", "updated", "conflict"}:
            stats["annotations_suggested"] += 1

    for reference in metadata.get("time_columns") or []:
        table_name, _, column_name = str(reference or "").strip().rpartition(".")
        if not table_name or not column_name:
            continue
        if not valid_reference(table_name, column_name):
            continue
        outcome = await suggest_column_annotation(
            db,
            data_source_id=asset.data_source_id,
            table_name=table_name,
            column_name=column_name,
            candidate={
                "business_description": asset.description or None,
                "semantic_type": "time",
                "is_time_column": True,
                "time_grain": str(metadata.get("grain") or "").strip() or None,
            },
            source="sql_asset",
            confidence=0.9,
            source_ref=source_ref,
            fingerprint=asset.schema_fingerprint,
        )
        if outcome in {"created", "updated", "conflict"}:
            stats["annotations_suggested"] += 1
    return stats


async def learn_quarantined_etl_assets(
    db: AsyncSession,
    *,
    assets: list[SQLAsset],
    user_id: str,
) -> dict[str, int]:
    """从范围合法的 ETL 学习待审核知识，同时保持隔离和不可执行。"""

    totals = {
        "assets_learned": 0,
        "metrics_created": 0,
        "relationships_created": 0,
        "annotations_suggested": 0,
    }
    for asset in assets:
        metadata = asset.verification_metadata or {}
        if (
            asset.asset_type != "etl"
            or asset.corpus_role != "quarantine"
            or asset.executable
            or (asset.validation_report or {}).get("status") != "pass"
            or metadata.get("knowledge_learning_mode") == "etl_read_only_extract"
        ):
            continue
        stats = await promote_sql_asset_knowledge(db, asset=asset, user_id=user_id)
        totals["assets_learned"] += 1
        for key, value in stats.items():
            totals[key] = int(totals.get(key) or 0) + int(value or 0)
        asset.verification_metadata = {
            **metadata,
            "knowledge_learning": stats,
            "knowledge_learning_mode": "etl_read_only_extract",
            "knowledge_learning_at": datetime.now(UTC).isoformat(),
        }
    return totals


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
    corpus_role: str = "retrieval",
    domain: str | None = None,
    owner: str | None = None,
) -> tuple[SQLAssetSource, list[SQLAsset], bool]:
    if corpus_role not in CORPUS_ROLES:
        raise ValidationException("corpus_role 仅支持 retrieval、evaluation 或 quarantine")
    encoded = source_text.encode("utf-8")
    if len(encoded) > MAX_UPLOAD_BYTES:
        raise ValidationException(f"SQL 文件不能超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    await _validate_project_scope(
        db,
        project_id=project_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=data_source_id,
    )

    # 同一数据源的上传在事务内串行化，消除“先查再插”的内容去重和版本号竞争。
    await db.scalar(select(DataSource.id).where(DataSource.id == data_source_id).with_for_update())
    content_hash = _hash_text(source_text)
    source_scope = [
        SQLAssetSource.tenant_id == tenant_id,
        SQLAssetSource.workspace_id == workspace_id,
        SQLAssetSource.data_source_id == data_source_id,
        SQLAssetSource.content_sha256 == content_hash,
        (
            SQLAssetSource.project_id == project_id
            if project_id
            else SQLAssetSource.project_id.is_(None)
        ),
    ]
    existing = await db.scalar(select(SQLAssetSource).where(*source_scope))
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
    sensitive = await _sensitive_columns(db, data_source_id)
    fingerprint = schema_fingerprint(inspection.schema_payload, sensitive)
    parsed = parse_sql_assets(
        source_text,
        dialect=dialect,
        table_columns=inspection.column_map,
        sensitive_columns=sensitive,
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
                    (
                        SQLAssetSource.project_id == project_id
                        if project_id
                        else SQLAssetSource.project_id.is_(None)
                    ),
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
    parsed_structure_hashes = {item.structure_hash for item in parsed}
    existing_rows = (
        await db.execute(
            select(SQLAsset.sql_hash, SQLAsset.structure_hash).where(
                SQLAsset.tenant_id == tenant_id,
                SQLAsset.workspace_id == workspace_id,
                SQLAsset.data_source_id == data_source_id,
                (
                    SQLAsset.project_id == project_id
                    if project_id
                    else SQLAsset.project_id.is_(None)
                ),
                or_(
                    SQLAsset.sql_hash.in_(parsed_hashes),
                    SQLAsset.structure_hash.in_(parsed_structure_hashes),
                ),
            )
        )
    ).all()
    existing_hashes = {str(row[0]) for row in existing_rows}
    existing_structure_hashes = {str(row[1]) for row in existing_rows}
    unique_parsed: list[ParsedSQLAsset] = []
    seen_hashes = set(existing_hashes)
    seen_structure_hashes = set(existing_structure_hashes)
    exact_duplicate_count = 0
    structure_duplicate_count = 0
    for item in parsed:
        if item.sql_hash in seen_hashes:
            exact_duplicate_count += 1
            continue
        if item.structure_hash in seen_structure_hashes:
            structure_duplicate_count += 1
            continue
        seen_hashes.add(item.sql_hash)
        seen_structure_hashes.add(item.structure_hash)
        unique_parsed.append(item)
    source.parse_report = {
        "status": "parsed",
        "statement_count": len(parsed),
        "asset_count": len(unique_parsed),
        "duplicate_count": len(parsed) - len(unique_parsed),
        "exact_duplicate_count": exact_duplicate_count,
        "structure_duplicate_count": structure_duplicate_count,
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
            title=item.title or f"{filename} / SQL {item.statement_index}",
            description=item.description,
            normalized_sql=item.normalized_sql,
            sql_hash=item.sql_hash,
            structure_hash=item.structure_hash,
            asset_type=item.asset_type,
            statement_type=item.statement_type,
            executable=item.executable,
            status="draft",
            corpus_role=(
                corpus_role if item.asset_type == "query" and item.executable else "quarantine"
            ),
            quality_status="unverified",
            domain=(item.domain or str(domain or "").strip() or None),
            owner=(item.owner or str(owner or "").strip() or None),
            dialect=dialect,
            tables=item.tables,
            columns=item.columns,
            lineage=item.lineage,
            parameters=item.parameters,
            tags=item.tags,
            knowledge_metadata=item.knowledge_metadata,
            risk_flags=item.risk_flags,
            verification_metadata={},
            retrieval_count=0,
            validation_report=item.validation_report,
            schema_fingerprint=fingerprint,
        )
        for item in unique_parsed
    ]
    db.add_all(assets)
    # ETL 只要通过当前数据源 Schema 校验，就自动产生待审核知识；查询资产
    # 仍遵循人工发布后再晋升的治理门槛。
    learning_stats = await learn_quarantined_etl_assets(db, assets=assets, user_id=user_id)
    source.parse_report["knowledge_learning"] = learning_stats
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
        "corpus_role": asset.corpus_role,
        "quality_status": asset.quality_status,
        "domain": asset.domain,
        "owner": asset.owner,
        "structure_hash": asset.structure_hash,
        "dialect": asset.dialect,
        "tables": asset.tables or [],
        "columns": asset.columns or [],
        "tags": asset.tags or [],
        "knowledge_metadata": asset.knowledge_metadata or {},
        "risk_flags": asset.risk_flags or [],
        "verification_metadata": asset.verification_metadata or {},
        "last_verified_at": asset.last_verified_at,
        "retrieval_count": asset.retrieval_count,
        "lineage": asset.lineage or {},
        "validation_report": asset.validation_report or {},
        "schema_fingerprint": asset.schema_fingerprint,
        "project_id": asset.project_id,
        "approved_by": asset.approved_by,
        "approved_at": asset.approved_at,
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
    include_draft_reference: bool = False,
    available_tables: list[str] | None = None,
) -> list[SQLAsset]:
    # 默认路径保持严格的线上执行资产语义；参考模式才额外读取历史草案。
    # 草案只进入知识上下文，最终候选仍需重新通过当前 Schema 和只读校验。
    if include_draft_reference:
        stmt = select(SQLAsset).where(
            SQLAsset.tenant_id == tenant_id,
            SQLAsset.workspace_id == workspace_id,
            SQLAsset.data_source_id == data_source_id,
            SQLAsset.dialect == dialect,
        )
    else:
        stmt = select(SQLAsset).where(
            SQLAsset.tenant_id == tenant_id,
            SQLAsset.workspace_id == workspace_id,
            SQLAsset.data_source_id == data_source_id,
            SQLAsset.status == "published",
            SQLAsset.corpus_role == "retrieval",
            SQLAsset.quality_status == "verified",
            SQLAsset.executable.is_(True),
            SQLAsset.dialect == dialect,
        )
    if project_id:
        stmt = stmt.where(or_(SQLAsset.project_id.is_(None), SQLAsset.project_id == project_id))
    else:
        stmt = stmt.where(SQLAsset.project_id.is_(None))
    rows = list((await db.execute(stmt.limit(500))).scalars().all())

    known_tables = {
        str(table).strip().lower() for table in (available_tables or []) if str(table).strip()
    }
    known_bare_tables: dict[str, set[str]] = {}
    for table in known_tables:
        known_bare_tables.setdefault(table.rsplit(".", 1)[-1], set()).add(table)

    def uses_current_schema(asset: SQLAsset) -> bool:
        """参考资产的表必须能在本回合 Schema 中证明属于当前数据源。"""
        if not known_tables:
            return True
        for raw_table in asset.tables or []:
            table = str(raw_table or "").strip().lower()
            if not table:
                continue
            if "." in table:
                if table not in known_tables:
                    return False
            elif table not in known_tables and len(known_bare_tables.get(table, set())) != 1:
                return False
        return True

    def reference_eligible(asset: SQLAsset) -> bool:
        # ETL、DDL、DML、Schema 失败和敏感字段资产永不进入检索参考。
        if (
            asset.asset_type != "query"
            or not bool(asset.executable)
            or (asset.validation_report or {}).get("status") != "pass"
            or not uses_current_schema(asset)
        ):
            return False
        published = (
            asset.status == "published"
            and asset.corpus_role == "retrieval"
            and asset.quality_status == "verified"
        )
        draft_reference = (
            include_draft_reference
            and asset.status in {"draft", "published"}
            and asset.corpus_role == "retrieval"
            and asset.quality_status in {"unverified", "verified"}
        )
        return published or draft_reference

    rows = [asset for asset in rows if reference_eligible(asset)]
    query_tokens = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        query_tokens.add(segment)
        query_tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))

    def relevance(asset: SQLAsset) -> float:
        knowledge = asset.knowledge_metadata or {}
        semantic = " ".join(
            [
                asset.title,
                asset.description,
                str(asset.domain or ""),
                " ".join(asset.tags or []),
                json.dumps(knowledge, ensure_ascii=False),
            ]
        ).lower()
        schema = " ".join([*(asset.tables or []), *(asset.columns or [])]).lower()
        sql = asset.normalized_sql.lower()
        semantic_hits = sum(1 for token in query_tokens if token in semantic)
        schema_hits = sum(1 for token in query_tokens if token in schema)
        sql_hits = sum(1 for token in query_tokens if token in sql)
        question_examples = " ".join(knowledge.get("questions") or []).lower()
        example_hits = sum(1 for token in query_tokens if token in question_examples)
        # 关键词、业务语义、Schema 三路加权；评测集在 SQL 条件层已经物理隔离。
        return semantic_hits * 3.0 + example_hits * 2.0 + schema_hits * 1.5 + sql_hits * 0.25

    scored_rows = [(asset, relevance(asset)) for asset in rows]
    relevant_rows = [asset for asset, score in scored_rows if score > 0]
    relevant_rows.sort(
        key=lambda asset: (relevance(asset), str(asset.created_at or "")), reverse=True
    )
    if include_draft_reference and not relevant_rows:
        # 没有词面命中时仍提供同一数据源的少量历史 SQL，避免因无表注释而完全失去业务口径。
        # 这里仅是参考上下文，不会改变候选生成与执行校验边界。
        relevant_rows = sorted(
            rows,
            key=lambda asset: (
                asset.status == "published",
                asset.quality_status == "verified",
                str(asset.created_at or ""),
            ),
            reverse=True,
        )
    selected = relevant_rows[: max(1, min(limit, 10))]
    for asset in selected:
        asset.retrieval_count = int(asset.retrieval_count or 0) + 1
    return selected


def _strip_model_sql(value: str) -> str:
    text = str(value or "").strip()
    fenced = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", text, flags=re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()
    return text


def _split_sql_statements(value: str, *, dialect: str) -> list[str]:
    """将模型或用户输入拆成候选语句，避免多语句输入被静默截断。"""

    raw = _strip_model_sql(value)
    if not raw:
        return []
    try:
        expressions = [
            item for item in parse(raw, read=_sqlglot_dialect(dialect)) if item is not None
        ]
    except ParseError:
        return [raw]
    if not expressions:
        return [raw]
    return [item.sql(dialect=_sqlglot_dialect(dialect), comments=False) for item in expressions]


def build_query_plan(
    question: str,
    assets: list[SQLAsset],
    *,
    clarification_context: str | None = None,
    governed_metrics: list[MetricDefinition] | None = None,
) -> dict[str, Any]:
    """先把问题映射成可审计计划，再让模型编译 SQL。"""

    effective_question = " ".join(
        item
        for item in (str(question or "").strip(), str(clarification_context or "").strip())
        if item
    )
    metadata = [asset.knowledge_metadata or {} for asset in assets[:5]]

    def unique(values: list[str], limit: int = 20) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))[:limit]

    metric_names = unique(
        [
            str(metric.get("name") or "").strip()
            for item in metadata
            for metric in item.get("metrics") or []
            if isinstance(metric, dict)
        ]
    )
    governed_metric_names = unique(
        [
            str(metric.name or "").strip()
            for metric in governed_metrics or []
            if str(metric.name or "").strip()
        ]
    )
    metric_names = unique([*governed_metric_names, *metric_names])
    metric_aliases = {
        str(metric.name or "").strip(): [
            str(alias).strip() for alias in (metric.aliases or []) if str(alias).strip()
        ]
        for metric in governed_metrics or []
        if str(metric.name or "").strip()
    }
    metric_contracts_all: list[dict[str, Any]] = []
    for metric in governed_metrics or []:
        name = str(metric.name or "").strip()
        formula = str(metric.formula or "").strip()
        if not name or not formula:
            continue
        source_columns = [
            str(value).strip() for value in (metric.underlying_columns or []) if str(value).strip()
        ]
        metric_contracts_all.append(
            {
                "name": name,
                "formula": formula,
                "aggregation": str(metric.agg_function or "").strip(),
                "source_columns": list(dict.fromkeys(source_columns)),
                "source_tables": list(
                    dict.fromkeys(
                        value.rsplit(".", 1)[0] for value in source_columns if "." in value
                    )
                ),
                "filters": [],
                "filter_contracts": [],
                "grain": "",
                "source_asset_id": None,
                "source_metric_id": str(metric.id),
                "authority": "published_metric",
            }
        )
    for asset in assets[:5]:
        knowledge = asset.knowledge_metadata or {}
        rules = knowledge.get("metric_rules") or knowledge.get("metrics") or []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("name") or "").strip()
            formula = str(rule.get("formula") or "").strip()
            if not name or not formula:
                continue
            source_columns = [
                str(value).strip()
                for value in rule.get("source_columns") or []
                if str(value).strip()
            ]
            source_tables = [
                str(value).strip()
                for value in rule.get("source_tables") or []
                if str(value).strip()
            ]
            if not source_tables:
                source_tables = list(
                    dict.fromkeys(
                        value.rsplit(".", 1)[0] for value in source_columns if "." in value
                    )
                )
            filter_contracts = [
                {
                    "expression": str(item.get("expression") or "").strip(),
                    "policy": str(item.get("policy") or "contextual").strip(),
                    "source": str(item.get("source") or "asset").strip(),
                }
                for item in rule.get("filter_contracts") or []
                if isinstance(item, dict) and str(item.get("expression") or "").strip()
            ]
            if not filter_contracts:
                filter_contracts = [
                    {
                        "expression": str(value).strip(),
                        "policy": _filter_policy(str(value)),
                        "source": "metric_rule",
                    }
                    for value in rule.get("filters") or []
                    if str(value).strip()
                ]
            metric_contracts_all.append(
                {
                    "name": name,
                    "formula": formula,
                    "aggregation": str(rule.get("aggregation") or "").strip(),
                    "source_columns": list(dict.fromkeys(source_columns)),
                    "source_tables": list(dict.fromkeys(source_tables)),
                    "filters": list(
                        dict.fromkeys(
                            [
                                str(value).strip()
                                for value in rule.get("filters") or []
                                if str(value).strip()
                            ]
                            + [item["expression"] for item in filter_contracts]
                        )
                    ),
                    "filter_contracts": filter_contracts,
                    "grain": str(rule.get("grain") or "").strip(),
                    "source_asset_id": asset.id,
                    "authority": "sql_asset",
                }
            )

    # 同名指标优先使用已发布定义；相同公式的多条资产合并来源，冲突则显式
    # 暴露给 QueryPlan，后续追问而不是静默选择一条口径。
    def formula_signature(value: str) -> str:
        return re.sub(
            r"\s+",
            "",
            re.sub(r"\b[a-z_][a-z0-9_]*\.", "", str(value or "").lower()),
        )

    grouped_contracts: dict[str, dict[str, Any]] = {}
    metric_conflicts: dict[str, list[str]] = {}
    for contract in metric_contracts_all:
        key = contract["name"].lower()
        current = grouped_contracts.get(key)
        if current is None:
            grouped_contracts[key] = contract
            continue
        if (
            current.get("authority") != "published_metric"
            and contract.get("authority") == "published_metric"
        ):
            grouped_contracts[key] = contract
            continue
        if formula_signature(current["formula"]) != formula_signature(contract["formula"]):
            metric_conflicts.setdefault(current["name"], []).append(contract["formula"])
            continue
        current["source_columns"] = list(
            dict.fromkeys(
                [*(current.get("source_columns") or []), *(contract.get("source_columns") or [])]
            )
        )
        current["source_tables"] = list(
            dict.fromkeys(
                [*(current.get("source_tables") or []), *(contract.get("source_tables") or [])]
            )
        )
        current["filter_contracts"] = list(
            {
                (
                    item.get("expression"),
                    item.get("policy"),
                    item.get("source"),
                ): item
                for item in [
                    *(current.get("filter_contracts") or []),
                    *(contract.get("filter_contracts") or []),
                ]
            }.values()
        )
        current["filters"] = list(
            dict.fromkeys([*(current.get("filters") or []), *(contract.get("filters") or [])])
        )
    metric_contracts_all = list(grouped_contracts.values())
    dimension_names = unique(
        [
            str(dimension.get("name") or "").strip()
            for item in metadata
            for dimension in item.get("dimensions") or []
            if isinstance(dimension, dict)
        ]
    )
    selected_metrics = [
        name
        for name in metric_names
        if name.lower() in effective_question.lower()
        or any(
            alias.lower() in effective_question.lower() for alias in metric_aliases.get(name, [])
        )
    ]
    selected_dimensions = [
        name for name in dimension_names if name.lower() in effective_question.lower()
    ]
    required_tables = unique([table for asset in assets[:5] for table in (asset.tables or [])])
    required_columns = unique(
        [column for asset in assets[:5] for column in (asset.columns or [])], 50
    )
    joins = unique(
        [
            (
                f"{join.get('left_table')}.{join.get('left_column')}="
                f"{join.get('right_table')}.{join.get('right_column')}"
            )
            for item in metadata
            for join in item.get("joins") or []
            if isinstance(join, dict)
            and all(
                join.get(key)
                for key in ("left_table", "left_column", "right_table", "right_column")
            )
        ]
    )
    all_filters = unique(
        [
            str(value).strip()
            for item in metadata
            for value in [
                *(item.get("filters") or []),
                *(
                    filter_value
                    for rule in item.get("metric_rules") or []
                    if isinstance(rule, dict)
                    for filter_value in rule.get("filters") or []
                ),
            ]
        ]
    )
    effective_question_lower = effective_question.lower()

    def filter_tokens(value: str) -> set[str]:
        tokens = set(re.findall(r"[a-zA-Z0-9_]+", str(value or "").lower()))
        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", str(value or "")):
            tokens.add(segment)
            tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
        return {token for token in tokens if token}

    # 历史资产中的状态、日期和 ID 是上下文证据，不是新问题的默认条件。
    # 只有问题文本明确出现过滤值/字段时，才把它提升为本次计划的过滤条件。
    selected_metric_names = [
        name
        for name in metric_names
        if name.lower() in effective_question_lower
        or any(alias.lower() in effective_question_lower for alias in metric_aliases.get(name, []))
    ]
    contract_names = selected_metric_names or metric_names[:5]
    selected_contracts = [
        dict(contract) for contract in metric_contracts_all if contract["name"] in contract_names
    ]
    # 只有问题中明确点名的指标需要覆盖检查；单指标资产在没有别名时也默认要求覆盖。
    require_contracts = bool(selected_metric_names) or len(selected_contracts) == 1
    for contract in selected_contracts:
        contract["enforcement"] = "required" if require_contracts else "advisory"
    required_filters = unique(
        [
            str(item.get("expression") or "").strip()
            for contract in selected_contracts
            if contract.get("enforcement") == "required"
            for item in contract.get("filter_contracts") or []
            if item.get("policy") == "required"
        ]
    )
    explicit_filters = [
        value
        for value in all_filters
        if any(
            token in effective_question_lower for token in filter_tokens(value) if len(token) >= 2
        )
    ]
    filters = unique([*required_filters, *explicit_filters])
    assumptions = unique(
        [str(value).strip() for item in metadata for value in item.get("assumptions") or []]
    )
    domains = [str(asset.domain or "").strip() for asset in assets if asset.domain]
    intent = "detail_query"
    if re.search(
        r"多少|数量|合计|总计|平均|趋势|同比|环比|排名|top\s*\d*", effective_question, re.I
    ):
        intent = "aggregate_query"

    time_range: dict[str, Any] = {}
    relative = re.search(r"最近\s*(\d+)\s*(天|日|周|月|年)", effective_question)
    if relative:
        time_range = {
            "type": "last_n",
            "value": int(relative.group(1)),
            "unit": relative.group(2),
        }
    elif re.search(r"本月|当月", effective_question):
        time_range = {"type": "current_month", "timezone": "Asia/Shanghai"}
    elif re.search(r"今天|今日", effective_question):
        time_range = {"type": "today", "timezone": "Asia/Shanghai"}

    clarification_question = ""
    missing_entities: list[str] = []
    selected_conflicts = [name for name in contract_names if name in metric_conflicts]
    if selected_conflicts:
        clarification_question = (
            "指标“"
            + "、".join(selected_conflicts)
            + "”存在多个已学习公式，请明确采用哪个业务口径后再生成 SQL。"
        )
        missing_entities = ["metric_definition"]
    elif len(effective_question) < 4:
        clarification_question = "请补充需要查询的指标、时间范围和分组维度。"
        missing_entities = ["metric", "time_range", "dimensions"]
    elif (
        re.search(r"收入", effective_question)
        and not re.search(r"净收入|毛收入|实收|应收|退款|gmv|销售收入", effective_question, re.I)
        and not selected_metrics
    ):
        clarification_question = "“收入”采用什么口径：实收、应收、GMV，还是扣除退款后的净收入？"
        missing_entities = ["metric_definition"]
    elif re.search(r"最近(?!\s*\d|一天|一周|一月|一年)", effective_question):
        clarification_question = "“最近”具体指多少天、周或月？"
        missing_entities = ["time_range"]

    return {
        "intent": intent,
        "domain": domains[0] if domains else "",
        "metrics": selected_metrics or metric_names[:5],
        "metric_contracts": selected_contracts,
        "metric_conflicts": {
            name: formulas for name, formulas in metric_conflicts.items() if name in contract_names
        },
        "dimensions": selected_dimensions or dimension_names[:8],
        "filters": filters,
        "available_filters": all_filters,
        "required_filters": required_filters,
        "filter_contracts": list(
            {
                (item.get("expression"), item.get("policy"), item.get("source")): item
                for contract in selected_contracts
                for item in contract.get("filter_contracts") or []
            }.values()
        ),
        "filter_policy": "指标固有条件自动复用；日期、ID 和上下文条件仅在用户明确提及时复用",
        "time_range": time_range,
        "required_tables": required_tables,
        "required_columns": required_columns,
        "joins": joins,
        "assumptions": assumptions,
        "retrieved_asset_ids": [asset.id for asset in assets[:5]],
        "needs_clarification": bool(clarification_question),
        "clarification_question": clarification_question,
        "missing_entities": missing_entities,
    }


def build_relevant_schema_hint(
    schema_payload: dict[str, Any],
    *,
    preferred_tables: list[str],
    question: str,
    max_chars: int,
) -> str:
    """优先放入计划命中的表，同时保留其余 Schema 作为受预算回退。"""

    payload = dict(schema_payload or {})
    tables = payload.get("tables")
    if not isinstance(tables, list):
        nested = payload.get("schema")
        tables = nested.get("tables") if isinstance(nested, dict) else None
    if not isinstance(tables, list):
        return build_schema_hint(schema_payload, max_chars=max_chars)
    preferred = {name.lower() for name in preferred_tables}
    tokens = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))

    def priority(table: Any) -> tuple[int, str]:
        if not isinstance(table, dict):
            return (3, "")
        name = str(table.get("name") or "").lower()
        searchable = json.dumps(table, ensure_ascii=False).lower()
        if name in preferred or name.rsplit(".", 1)[-1] in preferred:
            return (0, name)
        if any(token in searchable for token in tokens):
            return (1, name)
        return (2, name)

    payload["tables"] = sorted(tables, key=priority)
    return build_schema_hint(payload, max_chars=max_chars)


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
    expressions = [item for item in parse(raw, read=_sqlglot_dialect(dialect)) if item is not None]
    if len(expressions) != 1:
        raise SQLValidationError("one SQL candidate must contain exactly one statement")
    expression = expressions[0]
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


def _canonical_sql_fragment(value: str, *, dialect: str) -> str:
    """去掉表别名后归一化 SQL 片段，用于指标公式/过滤的可解释比对。"""

    try:
        expression = parse_one(str(value or "").strip(), read=_sqlglot_dialect(dialect))
    except (ParseError, OptimizeError):
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def strip_qualifier(node: Any) -> Any:
        if isinstance(node, exp.Column):
            return exp.column(str(node.name or ""))
        return node

    normalized = expression.transform(strip_qualifier)
    return normalized.sql(
        dialect=_sqlglot_dialect(dialect), pretty=False, comments=False, normalize=True
    )


def _predicate_fragments(expression: Any, *, dialect: str) -> set[str]:
    fragments: set[str] = set()

    def add(node: Any) -> None:
        if node is None:
            return
        fragments.add(_canonical_sql_fragment(node.sql(comments=False), dialect=dialect))
        if isinstance(node, exp.And):
            add(node.this)
            add(node.expression)

    for query in expression.find_all(exp.Select):
        for clause_name in ("where", "having"):
            clause = query.args.get(clause_name)
            add(getattr(clause, "this", clause))
        for case_node in query.find_all(exp.Case):
            for branch in case_node.args.get("ifs") or []:
                add(branch.args.get("this"))
        for filter_node in query.find_all(exp.Filter):
            add(getattr(filter_node.args.get("expression"), "this", None))
    return fragments


def _validate_metric_contract_coverage(
    sql: str,
    *,
    dialect: str,
    metric_contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    """校验候选 SQL 是否真正实现了计划中必须覆盖的指标契约。"""

    required_contracts = [
        item
        for item in metric_contracts
        if isinstance(item, dict) and item.get("enforcement") == "required"
    ]
    if not required_contracts:
        return {"status": "not_required", "errors": [], "warnings": []}
    expression = parse_one(sql, read=_sqlglot_dialect(dialect))
    candidate_tables, candidate_columns = _extract_tables_columns(expression)
    candidate_table_names = {value.lower() for value in candidate_tables}
    candidate_column_names = {value.lower() for value in candidate_columns}

    def table_is_present(value: Any) -> bool:
        expected = str(value or "").strip().lower()
        if not expected:
            return True
        if "." in expected:
            return expected in candidate_table_names
        return any(table.rsplit(".", 1)[-1] == expected for table in candidate_table_names)

    def column_is_present(value: Any) -> bool:
        expected = str(value or "").strip().lower()
        if not expected:
            return True
        if "." not in expected:
            return any(column.rsplit(".", 1)[-1] == expected for column in candidate_column_names)
        expected_table, expected_column = expected.rsplit(".", 1)
        for candidate in candidate_column_names:
            if "." not in candidate:
                # 未限定列已经过 Schema 唯一性校验，单独按字段名匹配是安全的。
                if candidate == expected_column:
                    return True
                continue
            candidate_table, candidate_column = candidate.rsplit(".", 1)
            if candidate_column != expected_column:
                continue
            if "." in expected_table:
                if candidate_table == expected_table:
                    return True
            elif candidate_table.rsplit(".", 1)[-1] == expected_table:
                return True
        return False

    candidate_formulas: set[str] = set()
    for selection in expression.find_all(exp.Select):
        for projection in selection.selects:
            nodes = [projection.this] if isinstance(projection, exp.Alias) else [projection]
            nodes.extend(node for node in projection.walk() if isinstance(node, exp.AggFunc))
            candidate_formulas.update(
                _canonical_sql_fragment(node.sql(comments=False), dialect=dialect)
                for node in nodes
                if node is not None
            )
    predicates = _predicate_fragments(expression, dialect=dialect)
    errors: list[str] = []
    warnings: list[str] = []
    covered: list[str] = []
    for contract in required_contracts:
        name = str(contract.get("name") or "未知指标")
        missing_tables = [
            table for table in contract.get("source_tables") or [] if not table_is_present(table)
        ]
        missing_columns = [
            column
            for column in contract.get("source_columns") or []
            if not column_is_present(column)
        ]
        expected_formula = _canonical_sql_fragment(
            str(contract.get("formula") or ""), dialect=dialect
        )
        formula_missing = bool(expected_formula and expected_formula not in candidate_formulas)
        required_predicates = {
            _canonical_sql_fragment(str(item.get("expression") or ""), dialect=dialect)
            for item in contract.get("filter_contracts") or []
            if item.get("policy") == "required" and str(item.get("expression") or "").strip()
        }
        missing_predicates = sorted(required_predicates.difference(predicates))
        if missing_tables or missing_columns or formula_missing or missing_predicates:
            details: list[str] = []
            if missing_tables:
                details.append("缺少来源表 " + ", ".join(missing_tables))
            if missing_columns:
                details.append("缺少来源字段 " + ", ".join(missing_columns))
            if formula_missing:
                details.append("缺少指标公式")
            if missing_predicates:
                details.append("缺少固有过滤 " + "; ".join(missing_predicates))
            errors.append(f"指标“{name}”契约未覆盖：" + "；".join(details))
        else:
            covered.append(name)
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "covered_metrics": list(dict.fromkeys(covered)),
        "required_metrics": [str(item.get("name") or "") for item in required_contracts],
    }


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
    output_mode: str = "sql_only",
    clarification_context: str | None = None,
    source_decision: DataSourceDecision | dict[str, Any] | None = None,
) -> tuple[SQLQueryDraft, list[SQLQueryCandidate]]:
    """将 DataAgent 治理运行投影为现有确认执行草案。"""

    if group_type not in {"alternative", "batch"}:
        raise ValidationException("group_type 仅支持 alternative 或 batch")
    if output_mode not in {"sql_only", "execute_and_answer"}:
        raise ValidationException("output_mode 仅支持 sql_only 或 execute_and_answer")
    await _validate_project_scope(
        db,
        project_id=project_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=data_source.id,
    )

    from data_agent.adapters.opentrace.evidence import OpenTraceEvidenceProvider
    from data_agent.adapters.opentrace.generator import OpenTraceSQLGenerator
    from data_agent.adapters.opentrace.repository import OpenTraceRunRepository
    from data_agent.contracts import (
        CandidateSQL,
        DataScope,
        DataSourceDecision,
        ExecutionMode,
        QueryRequest,
        RunState,
    )
    from data_agent.service import DataAgentService

    class _SuppliedSQLGenerator:
        async def generate(self, request, logical_plan, evidence):
            statements = _split_sql_statements(
                str(supplied_sql or ""), dialect=str(evidence.dialect or "mysql")
            )
            return [CandidateSQL(sql=statement, source="user_supplied") for statement in statements]

    scope = DataScope(
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=data_source.id,
        project_id=project_id,
    )
    normalized_source_decision = (
        DataSourceDecision.model_validate(source_decision)
        if isinstance(source_decision, dict)
        else source_decision
    )
    request = QueryRequest(
        question=question,
        scope=scope,
        mode=ExecutionMode(output_mode),
        confirmed=False,
        clarification_context=clarification_context,
        candidate_count=MAX_DRAFT_CANDIDATES,
        max_rows=settings.data_agent_max_result_rows,
        idempotency_key=f"response:{response_id}" if response_id else None,
        source_decision=normalized_source_decision,
    )
    service = DataAgentService(
        evidence_provider=OpenTraceEvidenceProvider(db, data_source),
        sql_generator=(
            _SuppliedSQLGenerator()
            if supplied_sql and supplied_sql.strip()
            else OpenTraceSQLGenerator()
        ),
        repository=OpenTraceRunRepository(db),
    )
    run = await service.create(request)

    existing = await db.scalar(
        select(SQLQueryDraft).where(
            SQLQueryDraft.data_agent_run_id == run.id,
            SQLQueryDraft.user_id == user_id,
            SQLQueryDraft.tenant_id == tenant_id,
            SQLQueryDraft.workspace_id == workspace_id,
        )
    )
    if existing is not None:
        return await load_scoped_draft(
            db,
            draft_id=existing.id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    if run.state in {RunState.FAILED, RunState.BLOCKED} and not run.candidates:
        raise ValidationException(
            "DataAgent 未能生成通过治理校验的 SQL",
            details={"warnings": run.warnings[:10], "trace": run.trace[-5:]},
        )

    plan_payload = run.logical_plan.model_dump(mode="json") if run.logical_plan else {}
    clarification = (
        {
            "question_text": run.logical_plan.clarification_question,
            "missing_entities": run.logical_plan.missing_information,
            "suggested_options": [],
        }
        if run.state == RunState.NEEDS_CLARIFICATION and run.logical_plan
        else {}
    )
    draft = SQLQueryDraft(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        response_id=response_id,
        data_agent_run_id=run.id,
        data_source_id=data_source.id,
        question=question,
        group_type=group_type,
        status=(
            "needs_clarification"
            if run.state == RunState.NEEDS_CLARIFICATION
            else "awaiting_confirmation"
        ),
        output_mode=output_mode,
        query_plan=plan_payload,
        clarification=clarification,
        dialect=str(run.evidence.dialect if run.evidence else data_source.source_type),
        schema_fingerprint=run.evidence.schema_fingerprint if run.evidence else None,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(draft)
    await db.flush()

    evidence_asset_ids = [
        item.source_id.split(":", 1)[-1]
        for item in (run.evidence.items if run.evidence else [])
        if item.type.value == "sql_asset"
    ]
    candidates: list[SQLQueryCandidate] = []
    viable = [candidate for candidate in run.candidates if not candidate.validation.errors]
    for position, candidate_run in enumerate(viable[:MAX_DRAFT_CANDIDATES], start=1):
        candidate = SQLQueryCandidate(
            id=candidate_run.id,
            draft_id=draft.id,
            position=position,
            title=f"SQL 方案 {position}",
            description=(
                "由治理语义层确定性编译"
                if candidate_run.source == "semantic_compiler"
                else "由 DataAgent 在治理证据约束下生成"
            ),
            sql=candidate_run.sql,
            sql_hash=_hash_text(candidate_run.sql),
            asset_ids=evidence_asset_ids,
            tables=candidate_run.validation.referenced_tables,
            columns=candidate_run.validation.referenced_columns,
            assumptions=[
                *candidate_run.assumptions,
                *(run.logical_plan.assumptions if run.logical_plan else []),
            ],
            validation_report=candidate_run.validation.model_dump(mode="json"),
        )
        candidate.validation_report["supporting_memory_ids"] = candidate_run.supporting_memory_ids
        db.add(candidate)
        candidates.append(candidate)
    if not candidates and run.state != RunState.NEEDS_CLARIFICATION:
        raise ValidationException(
            "DataAgent 没有可供确认执行的候选 SQL",
            details={"warnings": run.warnings[:10]},
        )
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
        "returned_row_count": len(candidate.result_rows or []),
        "result_truncated": candidate.row_count > len(candidate.result_rows or []),
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
        "output_mode": getattr(draft, "output_mode", "sql_only"),
        "query_plan": getattr(draft, "query_plan", {}) or {},
        "needs_clarification": draft.status == "needs_clarification",
        "clarification": getattr(draft, "clarification", {}) or {},
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
    retry_failed: bool = False,
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
    sensitive = await _sensitive_columns(db, draft.data_source_id)
    current_fingerprint = schema_fingerprint(current_schema.schema_payload, sensitive)
    if not schema_fingerprint_matches(
        draft.schema_fingerprint,
        current_schema.schema_payload,
        sensitive,
    ):
        raise ValidationException(
            "数据源 Schema 已变化，请重新生成 SQL 草案",
            details={
                "reason": "schema_changed",
                "draft_fingerprint": draft.schema_fingerprint,
                "current_fingerprint": current_fingerprint,
            },
        )
    if draft.schema_fingerprint != current_fingerprint:
        # 兼容旧版本基于完整 JSON 的指纹，验证通过后原位升级。
        draft.schema_fingerprint = current_fingerprint

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
        started_at = draft.execution_started_at
        if started_at is not None and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if started_at is not None and datetime.now(UTC) - started_at <= EXECUTION_STALE_AFTER:
            raise ValidationException("SQL 查询草案正在执行，请稍后查看结果")
        for candidate in candidates:
            if candidate.execution_status == "executing":
                candidate.execution_status = "pending"
                candidate.error_message = "上次执行进程中断，已恢复为可重试状态"
        previous_summary = dict(draft.execution_summary or {})
        draft.execution_summary = {
            **previous_summary,
            "recovery_count": int(previous_summary.get("recovery_count") or 0) + 1,
            "last_recovered_at": datetime.now(UTC).isoformat(),
        }
        draft.status = "awaiting_confirmation"
        draft.execution_started_at = None
        await db.commit()

    executable_statuses = {"pending"}
    if retry_failed:
        executable_statuses.add("failed")
    to_execute = [item for item in selected if item.execution_status in executable_statuses]
    if not to_execute:
        return serialize_draft(draft, candidates)

    for candidate in to_execute:
        if _hash_text(candidate.sql) != candidate.sql_hash:
            raise ValidationException(
                "候选 SQL 完整性校验失败",
                details={"reason": "sql_hash_mismatch", "candidate_id": candidate.id},
            )
        try:
            validated_sql, _, _, _ = _validated_candidate(
                candidate.sql,
                dialect=draft.dialect,
                table_columns=current_schema.column_map,
                sensitive_columns=sensitive,
            )
            coverage = _validate_metric_contract_coverage(
                validated_sql,
                dialect=draft.dialect,
                metric_contracts=(getattr(draft, "query_plan", {}) or {}).get("metric_contracts")
                or [],
            )
            if coverage["errors"]:
                raise SQLValidationError("；".join(coverage["errors"]))
        except (SQLValidationError, ParseError) as exc:
            raise ValidationException(f"候选 SQL 重新校验失败：{exc}") from exc

    data_agent_run_id = getattr(draft, "data_agent_run_id", None)
    if data_agent_run_id and draft.group_type == "alternative" and len(to_execute) == 1:
        from data_agent.adapters.opentrace.answer import OpenTraceAnswerSynthesizer
        from data_agent.adapters.opentrace.evidence import OpenTraceEvidenceProvider
        from data_agent.adapters.opentrace.executor import OpenTraceQueryExecutor
        from data_agent.adapters.opentrace.generator import OpenTraceSQLGenerator
        from data_agent.adapters.opentrace.learning import OpenTraceLearningRepository
        from data_agent.adapters.opentrace.repository import OpenTraceRunRepository
        from data_agent.contracts import DataScope, RunState
        from data_agent.learning import ExecutionLearningEngine
        from data_agent.service import DataAgentService

        candidate = to_execute[0]
        draft.status = "executing"
        draft.execution_started_at = datetime.now(UTC)
        candidate.selected = True
        candidate.execution_status = "executing"
        candidate.error_message = None
        await db.flush()
        scope = DataScope(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            data_source_id=draft.data_source_id,
            project_id=draft.project_id,
        )
        run = await DataAgentService(
            evidence_provider=OpenTraceEvidenceProvider(db, source),
            sql_generator=OpenTraceSQLGenerator(),
            query_executor=OpenTraceQueryExecutor(source),
            answer_synthesizer=OpenTraceAnswerSynthesizer(),
            repository=OpenTraceRunRepository(db),
            learning_repository=(
                OpenTraceLearningRepository(db) if settings.data_agent_learning_enabled else None
            ),
            learning_engine=ExecutionLearningEngine(
                minimum_confidence=settings.data_agent_learning_min_confidence
            ),
        ).execute(
            data_agent_run_id,
            scope,
            candidate_id=candidate.id,
            confirmed=True,
        )
        candidate.executed_at = datetime.now(UTC)
        if run.result is not None:
            candidate.result_rows = run.result.rows
            candidate.row_count = run.result.total_rows or run.result.returned_rows
        candidate.validation_report = {
            **(candidate.validation_report or {}),
            "preflight": run.preflight.model_dump(mode="json") if run.preflight else {},
            "result_validation": (
                run.result_validation.model_dump(mode="json") if run.result_validation else {}
            ),
        }
        if run.state == RunState.COMPLETED:
            candidate.execution_status = "completed"
            candidate.error_message = None
            draft.status = "completed"
        else:
            candidate.execution_status = "failed"
            candidate.error_message = "；".join(run.warnings[-5:]) or "DataAgent 执行未完成"
            draft.status = "failed"
        draft.selected_candidate_ids = sorted(
            set(draft.selected_candidate_ids or []).union({candidate.id})
        )
        draft.execution_started_at = None
        draft.execution_summary = {
            "data_agent_run_id": run.id,
            "state": run.state.value,
            "answer": run.answer,
            "answer_citations": [item.model_dump(mode="json") for item in run.answer_citations],
            "answer_metadata": run.answer_metadata,
            "learning": run.learning.model_dump(mode="json") if run.learning else {},
            "source_decision": (
                run.request.source_decision.model_dump(mode="json")
                if run.request.source_decision
                else {}
            ),
            "warnings": run.warnings,
            "preflight": run.preflight.model_dump(mode="json") if run.preflight else {},
            "result_validation": (
                run.result_validation.model_dump(mode="json") if run.result_validation else {}
            ),
        }
        await db.commit()
        return serialize_draft(draft, candidates)

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
    draft.execution_started_at = datetime.now(UTC)
    draft.selected_candidate_ids = sorted(
        set(draft.selected_candidate_ids or []).union(selected_ids)
    )
    for candidate in to_execute:
        candidate.selected = True
        candidate.execution_status = "executing"
        candidate.error_message = None
    await db.commit()

    for candidate in to_execute:
        try:
            rows = await SQLExecutor().run_on_dsn(
                dsn,
                candidate.sql,
                source_type=source.source_type,
                table_columns=current_schema.column_map,
            )
            bounded_rows, _ = _bounded_result_rows(rows)
            candidate.result_rows = bounded_rows
            candidate.row_count = len(rows)
            candidate.execution_status = "completed"
            candidate.error_message = None
        except Exception as exc:  # noqa: BLE001 - 每条候选独立记录，允许部分失败
            candidate.result_rows = []
            candidate.row_count = 0
            candidate.execution_status = "failed"
            candidate.error_message = str(exc)[:2000]
        candidate.executed_at = datetime.now(UTC)
        draft.execution_started_at = datetime.now(UTC)
        await db.commit()

    selected_history = [
        item for item in candidates if item.id in set(draft.selected_candidate_ids or [])
    ]
    succeeded = sum(1 for item in selected_history if item.execution_status == "completed")
    failed = sum(1 for item in selected_history if item.execution_status == "failed")
    draft.status = "completed" if failed == 0 else "partially_failed" if succeeded else "failed"
    previous_summary = dict(draft.execution_summary or {})
    draft.execution_summary = {
        "requested": len(selected_history),
        "succeeded": succeeded,
        "failed": failed,
        "completed_at": datetime.now(UTC).isoformat(),
        "recovery_count": int(previous_summary.get("recovery_count") or 0),
    }
    if previous_summary.get("last_recovered_at"):
        draft.execution_summary["last_recovered_at"] = previous_summary["last_recovered_at"]
    draft.execution_started_at = None
    await db.commit()
    return serialize_draft(draft, candidates)
