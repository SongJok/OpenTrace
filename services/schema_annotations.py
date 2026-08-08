"""Schema 业务标注、自动建议与人工优先合并。"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import SchemaMetadata, SchemaTableMetadata

ANNOTATION_STATUSES = {"suggested", "verified", "rejected"}
ANNOTATION_SOURCES = {"manual", "database_comment", "sql_asset", "inferred", "ai"}

_SOURCE_PRIORITY = {
    "manual": 100,
    "sql_asset": 80,
    "database_comment": 70,
    "inferred": 30,
    "ai": 20,
}

_TIME_PATTERN = re.compile(
    r"(^|_)(at|time|date|day|month|year|timestamp|created|updated|paid|start|end)($|_)",
    re.I,
)
_METRIC_PATTERN = re.compile(
    r"(^|_)(amount|price|cost|revenue|sales|gmv|income|profit|fee|count|qty|num|rate|ratio)($|_)",
    re.I,
)
_DIMENSION_PATTERN = re.compile(
    r"(^|_)(name|title|status|state|type|category|channel|source|platform|region|city|role|level|tier|gender)($|_)",
    re.I,
)
_SENSITIVE_PATTERN = re.compile(
    r"(^|_)(email|phone|mobile|address|identity|id_card|credit_card)($|_)", re.I
)


def _clean_list(values: Any, *, limit: int = 50) -> list[str]:
    if not isinstance(values, list | tuple | set):
        return []
    return list(
        dict.fromkeys(
            str(value).strip() for value in values if value is not None and str(value).strip()
        )
    )[:limit]


def _business_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").replace("_", " ")).strip().title()


def _comment_business_name(comment: str, fallback: str) -> str:
    first = re.split(r"[。；;，,\n]", str(comment or "").strip(), maxsplit=1)[0].strip()
    return (first or _business_name(fallback))[:255]


def _column_semantics(name: str, data_type: str, comment: str) -> dict[str, Any]:
    haystack = f"{name} {comment}".lower()
    is_time = bool(_TIME_PATTERN.search(name)) or any(
        token in haystack for token in ("时间", "日期", "timestamp")
    )
    is_metric = bool(_METRIC_PATTERN.search(name)) or any(
        token in haystack for token in ("金额", "收入", "成本", "数量", "比率", "指标")
    )
    is_dimension = bool(_DIMENSION_PATTERN.search(name)) or any(
        token in haystack for token in ("状态", "类型", "分类", "渠道", "地区", "维度")
    )
    is_sensitive = bool(_SENSITIVE_PATTERN.search(name)) or any(
        token in haystack for token in ("邮箱", "电话", "手机号", "身份证", "地址")
    )
    if is_time:
        semantic_type = "time"
    elif is_metric:
        semantic_type = "metric"
    elif is_dimension:
        semantic_type = "dimension"
    elif any(token in str(data_type or "").lower() for token in ("int", "decimal", "float")):
        semantic_type = "number"
    else:
        semantic_type = None
    return {
        "semantic_type": semantic_type,
        "is_time_column": is_time,
        "is_metric_column": is_metric,
        "is_dimension_column": is_dimension,
        "is_sensitive": is_sensitive,
    }


def _candidate_changed(record: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for field, value in candidate.items():
        if value in (None, "", [], {}):
            continue
        current = getattr(record, field, None)
        if current != value:
            changed[field] = value
    return changed


def _apply_candidate(
    record: Any,
    candidate: dict[str, Any],
    *,
    source: str,
    confidence: float,
    source_ref: str,
    fingerprint: str | None,
) -> str:
    """把自动建议安全合并到记录；已审核值永不被覆盖。"""

    refs = _clean_list([*(record.source_refs or []), source_ref])
    record.source_refs = refs
    record.schema_fingerprint = fingerprint or record.schema_fingerprint
    changes = _candidate_changed(record, candidate)
    if not changes:
        return "unchanged"

    if record.annotation_status in {"verified", "rejected"}:
        record.suggested_changes = {
            "fields": changes,
            "source": source,
            "confidence": confidence,
            "source_ref": source_ref,
            "schema_fingerprint": fingerprint,
        }
        return "conflict"

    existing_priority = _SOURCE_PRIORITY.get(record.annotation_source, 0)
    candidate_priority = _SOURCE_PRIORITY.get(source, 0)
    if candidate_priority < existing_priority and confidence <= record.annotation_confidence:
        return "ignored"

    for field, value in candidate.items():
        if value not in (None, "", [], {}):
            setattr(record, field, value)
    record.annotation_source = source
    record.annotation_confidence = max(0.0, min(float(confidence), 1.0))
    record.annotation_status = "suggested"
    record.suggested_changes = {}
    return "updated"


async def reconcile_schema_annotations(
    db: AsyncSession,
    *,
    data_source_id: str,
    schema_payload: dict[str, Any],
    fingerprint: str | None = None,
    max_items: int = 20000,
) -> dict[str, int]:
    """从物理 Schema 生成表/列业务标注建议，不覆盖人工审核结果。"""

    stats = {"created": 0, "updated": 0, "conflicts": 0, "unchanged": 0, "skipped": 0}
    tables = schema_payload.get("tables") if isinstance(schema_payload, dict) else []
    if not isinstance(tables, list):
        return stats

    existing_tables = {
        item.table_name: item
        for item in (
            (
                await db.execute(
                    select(SchemaTableMetadata).where(
                        SchemaTableMetadata.data_source_id == data_source_id
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    existing_columns = {
        (item.table_name, item.column_name): item
        for item in (
            (
                await db.execute(
                    select(SchemaMetadata).where(SchemaMetadata.data_source_id == data_source_id)
                )
            )
            .scalars()
            .all()
        )
    }

    def count(outcome: str) -> None:
        key = "conflicts" if outcome == "conflict" else outcome
        if key in stats:
            stats[key] += 1

    considered = 0
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name") or "").strip()
        if not table_name:
            continue
        table_comment = str(table.get("comment") or "").strip()
        if table_comment:
            if considered >= max_items:
                stats["skipped"] += 1
            else:
                considered += 1
                table_candidate = {
                    "business_name": _comment_business_name(table_comment, table_name),
                    "business_description": table_comment,
                }
                table_record = existing_tables.get(table_name)
                if table_record is None:
                    table_record = SchemaTableMetadata(
                        id=str(uuid.uuid4()),
                        data_source_id=data_source_id,
                        table_name=table_name,
                        annotation_source="database_comment",
                        annotation_confidence=0.9,
                        annotation_status="suggested",
                        schema_fingerprint=fingerprint,
                        source_refs=[f"schema:{table_name}"],
                        **table_candidate,
                    )
                    db.add(table_record)
                    existing_tables[table_name] = table_record
                    stats["created"] += 1
                else:
                    count(
                        _apply_candidate(
                            table_record,
                            table_candidate,
                            source="database_comment",
                            confidence=0.9,
                            source_ref=f"schema:{table_name}",
                            fingerprint=fingerprint,
                        )
                    )

        columns = table.get("columns")
        if not isinstance(columns, list):
            continue
        for column in columns:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name") or "").strip()
            if not column_name:
                continue
            comment = str(column.get("comment") or "").strip()
            data_type = str(column.get("type") or column.get("data_type") or "").strip()
            source = "database_comment" if comment else "inferred"
            confidence = 0.9 if comment else 0.5
            semantics = _column_semantics(column_name, data_type, comment)
            if not comment and not any(
                semantics.get(flag)
                for flag in (
                    "is_time_column",
                    "is_metric_column",
                    "is_dimension_column",
                    "is_sensitive",
                )
            ):
                continue
            if considered >= max_items:
                stats["skipped"] += 1
                continue
            considered += 1
            candidate = {
                "business_name": _comment_business_name(comment, column_name),
                "business_description": comment or None,
                **semantics,
            }
            key = (table_name, column_name)
            record = existing_columns.get(key)
            if record is None:
                record = SchemaMetadata(
                    id=str(uuid.uuid4()),
                    data_source_id=data_source_id,
                    table_name=table_name,
                    column_name=column_name,
                    annotation_source=source,
                    annotation_confidence=confidence,
                    annotation_status="suggested",
                    schema_fingerprint=fingerprint,
                    source_refs=[f"schema:{table_name}.{column_name}"],
                    **candidate,
                )
                db.add(record)
                existing_columns[key] = record
                stats["created"] += 1
            else:
                count(
                    _apply_candidate(
                        record,
                        candidate,
                        source=source,
                        confidence=confidence,
                        source_ref=f"schema:{table_name}.{column_name}",
                        fingerprint=fingerprint,
                    )
                )
    return stats


async def suggest_column_annotation(
    db: AsyncSession,
    *,
    data_source_id: str,
    table_name: str,
    column_name: str,
    candidate: dict[str, Any],
    source: str,
    confidence: float,
    source_ref: str,
    fingerprint: str | None = None,
) -> str:
    """由已发布 SQL 等可信资产提出字段语义建议。"""

    record = await db.scalar(
        select(SchemaMetadata).where(
            SchemaMetadata.data_source_id == data_source_id,
            SchemaMetadata.table_name == table_name,
            SchemaMetadata.column_name == column_name,
        )
    )
    if record is None:
        record = SchemaMetadata(
            id=str(uuid.uuid4()),
            data_source_id=data_source_id,
            table_name=table_name,
            column_name=column_name,
            annotation_source=source,
            annotation_confidence=confidence,
            annotation_status="suggested",
            source_refs=[source_ref],
            schema_fingerprint=fingerprint,
            **candidate,
        )
        db.add(record)
        return "created"
    return _apply_candidate(
        record,
        candidate,
        source=source,
        confidence=confidence,
        source_ref=source_ref,
        fingerprint=fingerprint,
    )


def approve_annotation(record: Any, *, user_id: str) -> None:
    suggested = record.suggested_changes or {}
    for field, value in dict(suggested.get("fields") or {}).items():
        if hasattr(record, field):
            setattr(record, field, value)
    if suggested:
        record.annotation_source = str(suggested.get("source") or record.annotation_source)
        record.annotation_confidence = float(
            suggested.get("confidence") or record.annotation_confidence
        )
    record.annotation_status = "verified"
    record.suggested_changes = {}
    record.approved_by = user_id
    record.approved_at = datetime.now(UTC)


def reject_annotation(record: Any, *, user_id: str) -> None:
    # 已审核人工值收到新建议时，“拒绝”只丢弃建议，不能让原标注退出生成上下文。
    if not record.suggested_changes:
        record.annotation_status = "rejected"
    record.suggested_changes = {}
    record.approved_by = user_id
    record.approved_at = datetime.now(UTC)


def serialize_annotation(record: Any, *, target_type: str) -> dict[str, Any]:
    payload = {
        "id": record.id,
        "target_type": target_type,
        "data_source_id": record.data_source_id,
        "table_name": record.table_name,
        "business_name": record.business_name,
        "business_description": record.business_description,
        "aliases": record.aliases or [],
        "tags": record.tags or [],
        "annotation_source": record.annotation_source,
        "annotation_confidence": record.annotation_confidence,
        "annotation_status": record.annotation_status,
        "suggested_changes": record.suggested_changes or {},
        "source_refs": record.source_refs or [],
        "schema_fingerprint": record.schema_fingerprint,
        "approved_by": record.approved_by,
        "approved_at": record.approved_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if target_type == "column":
        payload.update(
            {
                "column_name": record.column_name,
                "semantic_type": record.semantic_type,
                "value_map": record.value_map or {},
                "is_primary_key": record.is_primary_key,
                "is_foreign_key": record.is_foreign_key,
                "is_time_column": record.is_time_column,
                "time_grain": record.time_grain,
                "is_metric_column": record.is_metric_column,
                "is_dimension_column": record.is_dimension_column,
                "is_sensitive": record.is_sensitive,
                "masking_rule": record.masking_rule,
                "lifecycle_stage": record.lifecycle_stage,
                "sample_values": record.sample_values or [],
            }
        )
    return payload
