from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import DataSourceSchema


@dataclass
class SchemaInspectionResult:
    schema_payload: dict[str, Any]
    table_names: list[str]
    table_count: int
    column_map: dict[str, list[str]]


async def load_schema_inspection(db: AsyncSession, data_source_id: str) -> SchemaInspectionResult:
    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source_id)
    )
    schema_row = rs.scalar_one_or_none()
    try:
        schema_payload = (
            json.loads(schema_row.schema_json or "{}") if schema_row else {"tables": []}
        )
    except Exception:
        schema_payload = {"tables": []}

    tables = schema_payload.get("tables") if isinstance(schema_payload, dict) else []
    table_names: list[str] = []
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or "").strip()
            if name:
                table_names.append(name)

    if not table_names and schema_row and isinstance(schema_row.schema_json, str):
        # Some sync jobs store a flat schema payload without `tables` nesting.
        flat = schema_payload if isinstance(schema_payload, dict) else {}
        for key in ("table_names", "tables_names", "names"):
            values = flat.get(key) if isinstance(flat, dict) else None
            if isinstance(values, list):
                table_names.extend([str(v).strip() for v in values if str(v).strip()])
        if not table_names and isinstance(flat.get("schema"), dict):
            nested = flat.get("schema")
            if isinstance(nested, dict):
                tables2 = nested.get("tables")
                if isinstance(tables2, list):
                    for t in tables2:
                        if isinstance(t, dict):
                            name = str(t.get("name") or "").strip()
                            if name:
                                table_names.append(name)

    # Build column_map: table_name → [column_names]. 仅 ClickHouse 全库同步使用
    # database.table 作为唯一键，避免不同库的同名表相互覆盖；其他数据源保持历史键名。
    column_map: dict[str, list[str]] = {}
    cross_database_scope = (
        isinstance(schema_payload, dict)
        and str(schema_payload.get("database_scope") or "").strip() == "*"
    )
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            tname = str(t.get("name") or "").strip()
            if not tname:
                continue
            database = str(t.get("database") or "").strip()
            qualified_name = tname
            if cross_database_scope and database and database != "*" and "." not in tname:
                qualified_name = f"{database}.{tname}"
            columns = t.get("columns")
            if isinstance(columns, list):
                col_names = [str(c.get("name", "")).strip() for c in columns if isinstance(c, dict)]
                column_map[qualified_name] = [cn for cn in col_names if cn]

    return SchemaInspectionResult(
        schema_payload=schema_payload,
        table_names=table_names,
        table_count=len(table_names),
        column_map=column_map,
    )


def build_schema_hint(schema_payload: dict[str, Any], max_chars: int = 4000) -> str:
    try:
        return json.dumps(schema_payload or {"tables": []}, ensure_ascii=False)[:max_chars]
    except Exception:
        return '{"tables": []}'
