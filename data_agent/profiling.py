"""对真实数据做有界、只读且可审计的数据画像。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.sql_executor import SQLExecutor
from infra.config.settings import settings
from infra.metadata.schema_inspector import load_schema_inspection
from infra.security.data_source_secrets import decrypt_data_source_secret
from infra.storage.data_agent_models import DataAgentProfile
from infra.storage.models import DataSource, SchemaMetadata

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _safe_qualified_identifier(value: str) -> bool:
    return bool(value) and all(_IDENTIFIER.fullmatch(part) for part in value.split("."))


def _schema_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _semantic_type(column: str, values: list[Any]) -> str:
    lowered = column.lower()
    if re.search(r"(^|_)(id|uuid|guid)$", lowered):
        return "identifier"
    if re.search(r"time|date|created|updated|paid|occurred|时间|日期", lowered):
        return "datetime"
    if re.search(r"amount|price|revenue|gmv|cost|fee|金额|收入|流水|价格", lowered):
        return "monetary_amount"
    if re.search(r"status|state|type|category|level|状态|类型|等级", lowered):
        return "enum"
    non_null = [value for value in values if value is not None]
    if non_null and all(isinstance(value, bool) for value in non_null):
        return "boolean"
    if non_null and all(
        isinstance(value, int | float) and not isinstance(value, bool) for value in non_null
    ):
        return "numeric"
    return "text"


def _column_profile(column: str, values: list[Any], *, sensitive: bool) -> dict[str, Any]:
    sample_size = len(values)
    non_null = [value for value in values if value is not None]
    distinct = {_json_key(value) for value in non_null}
    numeric = [
        float(value)
        for value in non_null
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]
    semantic_type = _semantic_type(column, values)
    result: dict[str, Any] = {
        "sample_size": sample_size,
        "non_null_count": len(non_null),
        "null_rate": ((sample_size - len(non_null)) / sample_size) if sample_size else None,
        "sample_distinct_count": len(distinct),
        "sample_cardinality": (len(distinct) / len(non_null)) if non_null else None,
        "semantic_type": semantic_type,
        "enum_candidate": bool(non_null) and len(distinct) <= min(50, max(2, len(non_null) // 2)),
        "is_time": semantic_type == "datetime",
        "is_metric": semantic_type in {"numeric", "monetary_amount"},
        "is_dimension": semantic_type in {"enum", "boolean", "text"}
        and bool(non_null)
        and len(distinct) <= min(500, max(20, int(len(non_null) * 0.5))),
        "sensitive": sensitive,
    }
    if numeric:
        ordered = sorted(numeric)
        result.update(
            {
                "min": ordered[0],
                "max": ordered[-1],
                "avg": sum(ordered) / len(ordered),
                "p50": ordered[len(ordered) // 2],
                "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            }
        )
    if not sensitive:
        counts = Counter(_json_key(value) for value in non_null)
        result["top_values"] = [
            {"value": json.loads(value), "count": count}
            for value, count in counts.most_common(settings.data_agent_profile_top_values)
        ]
        result["sample_values"] = [json.loads(value) for value in list(distinct)[:10]]
    else:
        result["top_values"] = []
        result["sample_values"] = []
    return result


class DataProfiler:
    def __init__(self, db: AsyncSession, data_source: DataSource) -> None:
        self.db = db
        self.data_source = data_source

    async def refresh(
        self,
        *,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        requested_tables: list[str] | None = None,
    ) -> list[DataAgentProfile]:
        inspection = await load_schema_inspection(self.db, self.data_source.id)
        fingerprint = _schema_fingerprint(inspection.schema_payload)
        allowed = set(inspection.column_map)
        tables = [
            table for table in (requested_tables or inspection.table_names) if table in allowed
        ]
        tables = tables[: settings.data_agent_profile_max_tables]
        sensitive_rows = list(
            (
                await self.db.execute(
                    select(SchemaMetadata).where(
                        SchemaMetadata.data_source_id == self.data_source.id,
                        SchemaMetadata.is_sensitive.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        sensitive = {(row.table_name.lower(), row.column_name.lower()) for row in sensitive_rows}
        await self.db.execute(
            update(DataAgentProfile)
            .where(
                DataAgentProfile.user_id == user_id,
                DataAgentProfile.tenant_id == tenant_id,
                DataAgentProfile.workspace_id == workspace_id,
                DataAgentProfile.data_source_id == self.data_source.id,
                DataAgentProfile.status == "current",
            )
            .values(status="stale")
        )

        dsn = DBRouter().build_dsn(
            DBConnectionInfo(
                source_type=self.data_source.source_type,
                host=self.data_source.host,
                port=self.data_source.port,
                database=self.data_source.database,
                username=self.data_source.username,
                password=decrypt_data_source_secret(self.data_source.password_encrypted),
            )
        )
        executor = SQLExecutor(
            max_rows=settings.data_agent_profile_sample_rows,
            timeout_ms=settings.data_agent_profile_statement_timeout_ms,
        )
        expires_at = datetime.now(UTC) + timedelta(hours=settings.data_agent_profile_ttl_hours)
        profiles: list[DataAgentProfile] = []
        for table in tables:
            columns = list(inspection.column_map.get(table) or [])[
                : settings.data_agent_profile_max_columns_per_table
            ]
            if not _safe_qualified_identifier(table):
                profiles.append(
                    self._failed_profile(
                        user_id,
                        tenant_id,
                        workspace_id,
                        fingerprint,
                        table,
                        "表名不符合安全标识符规则，已跳过真实数据采样",
                    )
                )
                continue
            safe_columns = [column for column in columns if _IDENTIFIER.fullmatch(column)]
            if not safe_columns:
                continue
            sql = f"SELECT {', '.join(safe_columns)} FROM {table}"
            try:
                rows = await executor.run_on_dsn(
                    dsn,
                    sql,
                    source_type=self.data_source.source_type,
                    table_columns=inspection.column_map,
                )
            except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
                profiles.append(
                    self._failed_profile(
                        user_id,
                        tenant_id,
                        workspace_id,
                        fingerprint,
                        table,
                        str(exc)[:2000],
                    )
                )
                continue

            table_profile = DataAgentProfile(
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                data_source_id=self.data_source.id,
                schema_fingerprint=fingerprint,
                table_name=table,
                column_name="",
                profile_type="table",
                sample_size=len(rows),
                profile_json={
                    "sample_size": len(rows),
                    "column_count": len(columns),
                    "profiled_column_count": len(safe_columns),
                    "sampling_bias": "有界顺序样本仅用于语义和质量提示，不代表全表精确分布",
                },
                expires_at=expires_at,
            )
            self.db.add(table_profile)
            profiles.append(table_profile)
            for column in safe_columns:
                values = [row.get(column) for row in rows]
                profile = DataAgentProfile(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    data_source_id=self.data_source.id,
                    schema_fingerprint=fingerprint,
                    table_name=table,
                    column_name=column,
                    profile_type="column",
                    sample_size=len(values),
                    profile_json=_column_profile(
                        column,
                        values,
                        sensitive=(table.lower(), column.lower()) in sensitive,
                    ),
                    expires_at=expires_at,
                )
                self.db.add(profile)
                profiles.append(profile)
        await self.db.flush()
        return profiles

    def _failed_profile(
        self,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        fingerprint: str,
        table: str,
        error: str,
    ) -> DataAgentProfile:
        profile = DataAgentProfile(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            data_source_id=self.data_source.id,
            schema_fingerprint=fingerprint,
            table_name=table,
            column_name="",
            profile_type="table",
            sampling_method="bounded_head",
            sample_size=0,
            profile_json={},
            status="failed",
            error_message=error,
        )
        self.db.add(profile)
        return profile


def serialize_profile(profile: DataAgentProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "data_source_id": profile.data_source_id,
        "schema_fingerprint": profile.schema_fingerprint,
        "table_name": profile.table_name,
        "column_name": profile.column_name,
        "profile_type": profile.profile_type,
        "sampling_method": profile.sampling_method,
        "sample_size": profile.sample_size,
        "profile": profile.profile_json or {},
        "status": profile.status,
        "error_message": profile.error_message,
        "profiled_at": profile.profiled_at,
        "expires_at": profile.expires_at,
    }
