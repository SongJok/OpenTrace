"""为当前 SQL 草案主路径构建受作用域约束的数据知识上下文。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    DataSourceSchema,
    MetricDefinition,
    SchemaMetadata,
    SchemaTableMetadata,
    SQLAsset,
    TableRelationship,
)


@dataclass(frozen=True)
class DataKnowledgeContext:
    prompt: str
    counts: dict[str, int]


def _query_tokens(value: str) -> set[str]:
    tokens = set(re.findall(r"[a-zA-Z0-9_]+", str(value or "").lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", str(value or "")):
        tokens.add(segment)
        tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return {token for token in tokens if token}


def _score(tokens: set[str], *values: Any) -> int:
    text = " ".join(
        (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, dict | list)
            else str(value or "")
        )
        for value in values
    ).lower()
    return sum(1 for token in tokens if token in text)


def _usable_annotation(record: Any) -> bool:
    if record.annotation_status == "verified":
        return True
    return (
        record.annotation_status == "suggested"
        and record.annotation_source == "database_comment"
        and float(record.annotation_confidence or 0) >= 0.85
    )


def _bounded_json(payload: dict[str, Any], *, max_chars: int) -> tuple[str, list[str]]:
    """按知识分区裁剪提示词，保证输出始终是合法 JSON。"""

    budget = max(1000, int(max_chars))
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw) <= budget:
        return raw, []

    bounded: dict[str, Any] = {}
    truncated: list[str] = []
    for key, value in payload.items():
        if isinstance(value, list):
            kept: list[Any] = []
            for item in value:
                candidate = {**bounded, key: [*kept, item]}
                candidate["_truncated_sections"] = [*truncated, key]
                if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > budget:
                    break
                kept.append(item)
            bounded[key] = kept
            if len(kept) < len(value):
                truncated.append(key)
        elif isinstance(value, dict):
            kept_mapping: dict[str, Any] = {}
            for item_key, item_value in value.items():
                candidate = {**bounded, key: {**kept_mapping, item_key: item_value}}
                candidate["_truncated_sections"] = [*truncated, key]
                if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) > budget:
                    break
                kept_mapping[item_key] = item_value
            bounded[key] = kept_mapping
            if len(kept_mapping) < len(value):
                truncated.append(key)
        else:
            candidate = {**bounded, key: value}
            if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) <= budget:
                bounded[key] = value
            else:
                truncated.append(key)

    if truncated:
        bounded["_truncated_sections"] = list(dict.fromkeys(truncated))
    raw = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
    if len(raw) <= budget:
        return raw, list(dict.fromkeys(truncated))
    fallback = json.dumps(
        {"_truncated_sections": ["all"]}, ensure_ascii=False, separators=(",", ":")
    )
    return fallback, list(payload)


async def build_data_knowledge_context(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    assets: list[SQLAsset],
    max_chars: int = 12000,
) -> DataKnowledgeContext:
    """汇总审核知识；自动猜测只在高可信物理注释来源时进入提示词。"""

    tokens = _query_tokens(question)
    schema_row = await db.scalar(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source_id)
    )
    semantic_mappings = schema_row.semantic_mappings if schema_row else {}

    table_rows = list(
        (
            await db.execute(
                select(SchemaTableMetadata).where(
                    SchemaTableMetadata.data_source_id == data_source_id,
                    SchemaTableMetadata.annotation_status != "rejected",
                )
            )
        )
        .scalars()
        .all()
    )
    ranked_tables = [
        (
            record,
            _score(
                tokens,
                record.table_name,
                record.business_name,
                record.business_description,
                record.aliases,
                record.tags,
            ),
        )
        for record in table_rows
        if _usable_annotation(record)
    ]
    ranked_tables.sort(key=lambda item: (item[1], item[0].table_name), reverse=True)
    selected_tables = [record for record, score in ranked_tables if score > 0][:20]
    if not selected_tables:
        selected_tables = [record for record, _ in ranked_tables[:8]]
    selected_table_names = {record.table_name for record in selected_tables}

    column_rows = list(
        (
            await db.execute(
                select(SchemaMetadata).where(
                    SchemaMetadata.data_source_id == data_source_id,
                    SchemaMetadata.annotation_status != "rejected",
                )
            )
        )
        .scalars()
        .all()
    )
    ranked_columns = [
        (
            record,
            _score(
                tokens,
                record.table_name,
                record.column_name,
                record.business_name,
                record.business_description,
                record.aliases,
                record.tags,
                record.value_map,
            ),
        )
        for record in column_rows
        if _usable_annotation(record)
    ]
    ranked_columns.sort(
        key=lambda item: (item[0].table_name in selected_table_names, item[1]), reverse=True
    )
    selected_columns = [
        record
        for record, score in ranked_columns
        if score > 0 or record.table_name in selected_table_names
    ][:80]

    metric_rows = list(
        (
            await db.execute(
                select(MetricDefinition).where(
                    MetricDefinition.data_source_id == data_source_id,
                    MetricDefinition.status == "published",
                )
            )
        )
        .scalars()
        .all()
    )
    ranked_metrics = [
        (
            record,
            _score(
                tokens,
                record.name,
                record.aliases,
                record.business_definition,
                record.category,
                record.tags,
            ),
        )
        for record in metric_rows
    ]
    ranked_metrics.sort(key=lambda item: item[1], reverse=True)
    selected_metrics = [record for record, score in ranked_metrics if score > 0][:12]

    relationships = list(
        (
            await db.execute(
                select(TableRelationship).where(
                    TableRelationship.data_source_id == data_source_id,
                    TableRelationship.is_verified.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    selected_relationships = [
        record
        for record in relationships
        if not selected_table_names
        or record.left_table in selected_table_names
        or record.right_table in selected_table_names
    ][:30]

    payload = {
        "semantic_mappings": semantic_mappings or {},
        "table_annotations": [
            {
                "table": record.table_name,
                "business_name": record.business_name,
                "description": record.business_description,
                "aliases": record.aliases or [],
                "tags": record.tags or [],
                "source": record.annotation_source,
            }
            for record in selected_tables
        ],
        "column_annotations": [
            {
                "table": record.table_name,
                "column": record.column_name,
                "business_name": record.business_name,
                "description": record.business_description,
                "aliases": record.aliases or [],
                "semantic_type": record.semantic_type,
                "value_map": record.value_map or {},
                "is_time": record.is_time_column,
                "time_grain": record.time_grain,
                "is_metric": record.is_metric_column,
                "is_dimension": record.is_dimension_column,
                "is_sensitive": record.is_sensitive,
            }
            for record in selected_columns
        ],
        "published_metrics": [
            {
                "name": record.name,
                "aliases": record.aliases or [],
                "formula": record.formula,
                "business_definition": record.business_definition,
                "unit": record.unit,
                "underlying_columns": record.underlying_columns or [],
            }
            for record in selected_metrics
        ],
        "verified_relationships": [
            {
                "left": f"{record.left_table}.{record.left_column}",
                "right": f"{record.right_table}.{record.right_column}",
                "join_type": record.join_type,
                "cardinality": record.cardinality,
                "amplification_risk": record.amplification_risk,
            }
            for record in selected_relationships
        ],
        "published_sql_asset_knowledge": [
            {
                "title": asset.title,
                "description": asset.description,
                "tags": asset.tags or [],
                "knowledge": asset.knowledge_metadata or {},
            }
            for asset in assets[:5]
        ],
    }
    bounded, truncated_sections = _bounded_json(payload, max_chars=max_chars)
    prompt = (
        "以下为该数据源中已审核或高可信的数据知识。业务名称、指标公式、枚举映射和已验证"
        " JOIN 优先于字段名猜测；SQL 资产中的固定过滤值仅在用户明确要求时复用。\n" + bounded
    )
    return DataKnowledgeContext(
        prompt=prompt,
        counts={
            "tables": len(selected_tables),
            "columns": len(selected_columns),
            "metrics": len(selected_metrics),
            "relationships": len(selected_relationships),
            "sql_assets": len(assets[:5]),
            "truncated_sections": len(truncated_sections),
        },
    )
