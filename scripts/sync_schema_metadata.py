#!/usr/bin/env python3
"""
Sync schema metadata from a live data source's information_schema.
Infers semantic types from column name patterns and upserts into schema_metadata.

Usage:
  python scripts/sync_schema_metadata.py --data-source-id <UUID> [--sample-rows N]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import get_settings
from infra.storage.database import SessionLocal
from infra.storage.models import DataSource, SchemaMetadata

# ── Semantic type inference patterns ─────────────────────────────────────

SEMANTIC_PATTERNS: list[tuple[re.Pattern, str, dict[str, Any]]] = [
    # (regex, semantic_type, extra_flags)
    (re.compile(r"(^|_)id$", re.I), "id", {"is_dimension_column": True}),
    (re.compile(r"(^|_)(name|title|label|description|comment|note|remark)$", re.I), "name", {"is_dimension_column": True}),
    (re.compile(r"(^|_)(amount|price|cost|revenue|fee|charge|sales|gmv|income|profit|loss|balance|budget)$", re.I), "amount", {"is_metric_column": True}),
    (re.compile(r"(^|_)(count|qty|quantity|num|number|cnt)$", re.I), "count", {"is_metric_column": True}),
    (re.compile(r"(^|_)(rate|ratio|pct|percent|percentage|avg|average)$", re.I), "percentage", {"is_metric_column": True}),
    (re.compile(r"(^|_)(at|time|date|day|month|year|hour|minute|second|timestamp|ts|created|updated|deleted|expired|start|end|begin|finish)$", re.I), "time", {"is_time_column": True, "is_dimension_column": True}),
    (re.compile(r"(^|_)(status|state|type|kind|category|stage|level|tier|grade|rank|role|gender|mode|channel|source|platform|device|region|country|city|province|area)$", re.I), "category", {"is_dimension_column": True}),
    (re.compile(r"(^|_)(email|phone|mobile|tel|address|zip|postal)$", re.I), "name", {"is_dimension_column": True, "is_sensitive": True}),
]

TIME_GRAIN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|_)year", re.I), "year"),
    (re.compile(r"(^|_)month", re.I), "month"),
    (re.compile(r"(^|_)day|(^|_)date", re.I), "day"),
    (re.compile(r"(^|_)hour", re.I), "hour"),
    (re.compile(r"(^|_)minute", re.I), "minute"),
]

LIFECYCLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|_)created_at$", re.I), "creation"),
    (re.compile(r"(^|_)updated_at$", re.I), "modification"),
    (re.compile(r"(^|_)deleted_at$", re.I), "deletion"),
    (re.compile(r"(^|_)expired_at$", re.I), "expiration"),
]


def _infer_semantic_type(column_name: str, data_type: str) -> tuple[str | None, dict[str, Any]]:
    """Infer semantic_type and flags from column name pattern."""
    flags: dict[str, Any] = {}

    for pattern, sem_type, extra_flags in SEMANTIC_PATTERNS:
        if pattern.search(column_name):
            flags.update(extra_flags)
            return sem_type, flags

    # Fallback by SQL type
    dt = data_type.lower()
    if any(t in dt for t in ("int", "numeric", "decimal", "float", "double", "real")):
        return "count", {"is_metric_column": True}
    if any(t in dt for t in ("timestamp", "date", "time", "datetime")):
        return "time", {"is_time_column": True, "is_dimension_column": True}
    if any(t in dt for t in ("bool",)):
        return "category", {"is_dimension_column": True}

    return None, {}


def _infer_time_grain(column_name: str) -> str | None:
    for pattern, grain in TIME_GRAIN_PATTERNS:
        if pattern.search(column_name):
            return grain
    return None


def _infer_lifecycle_stage(column_name: str) -> str | None:
    for pattern, stage in LIFECYCLE_PATTERNS:
        if pattern.search(column_name):
            return stage
    return None


async def _get_columns(conn_info: DataSource) -> list[dict]:
    """Query information_schema.columns from the target data source."""
    from execution.data.db_router import DBConnectionInfo, DBRouter

    settings_obj = get_settings()
    from cryptography.fernet import Fernet
    import hashlib
    import base64

    secret = settings_obj.data_secret_key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    f = Fernet(key)
    password = f.decrypt(conn_info.password_encrypted.encode("utf-8")).decode("utf-8")

    db_info = DBConnectionInfo(
        source_type=conn_info.source_type,
        host=conn_info.host,
        port=conn_info.port,
        database=conn_info.database,
        username=conn_info.username,
        password=password,
    )

    router = DBRouter()
    engine_factory = router.get_engine(db_info)
    engine = engine_factory()

    query = text(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'mysql', 'sys', 'performance_schema') "
        "ORDER BY table_name, ordinal_position"
    )

    async with engine.connect() as conn:
        result = await conn.execute(query)
        rows = result.fetchall()

    await engine.dispose()
    return [dict(r._mapping) for r in rows]


async def _fetch_sample_values(
    conn_info: DataSource, table_name: str, column_name: str, limit: int = 10
) -> list[str]:
    """Fetch sample values from a column."""
    from execution.data.db_router import DBConnectionInfo, DBRouter
    from cryptography.fernet import Fernet
    import hashlib
    import base64

    settings_obj = get_settings()
    secret = settings_obj.data_secret_key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    password = Fernet(key).decrypt(conn_info.password_encrypted.encode("utf-8")).decode("utf-8")

    db_info = DBConnectionInfo(
        source_type=conn_info.source_type,
        host=conn_info.host,
        port=conn_info.port,
        database=conn_info.database,
        username=conn_info.username,
        password=password,
    )

    router = DBRouter()
    engine_factory = router.get_engine(db_info)
    engine = engine_factory()

    try:
        query = text(
            f'SELECT DISTINCT "{column_name}" AS val FROM "{table_name}" '
            f'WHERE "{column_name}" IS NOT NULL LIMIT {limit}'
        )
        async with engine.connect() as conn:
            result = await conn.execute(query)
            rows = result.fetchall()
        return [str(r[0]) for r in rows]
    except Exception:
        return []
    finally:
        await engine.dispose()


async def sync_schema_metadata(
    data_source_id: str, fetch_samples: bool = False, sample_limit: int = 10
) -> dict:
    """Main sync entry point."""
    async with SessionLocal() as session:
        ds = await session.get(DataSource, data_source_id)
        if not ds:
            raise ValueError(f"DataSource not found: {data_source_id}")

        print(f"Connected to data source: {ds.name} ({ds.source_type})")
        print("Fetching columns from information_schema...")

        columns = await _get_columns(ds)
        print(f"Found {len(columns)} columns across {len(set(c['table_name'] for c in columns))} tables")

        upserted = 0
        for col in columns:
            table_name = col["table_name"]
            column_name = col["column_name"]
            data_type = col["data_type"]
            is_nullable = col.get("is_nullable", "YES") == "YES"
            default_value = col.get("column_default")

            semantic_type, flags = _infer_semantic_type(column_name, data_type)
            time_grain = _infer_time_grain(column_name)
            lifecycle_stage = _infer_lifecycle_stage(column_name)
            business_name = column_name.replace("_", " ").title()

            sample_values = None
            if fetch_samples:
                sample_values = await _fetch_sample_values(ds, table_name, column_name, sample_limit)

            # Upsert
            result = await session.execute(
                select(SchemaMetadata).where(
                    SchemaMetadata.data_source_id == data_source_id,
                    SchemaMetadata.table_name == table_name,
                    SchemaMetadata.column_name == column_name,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.business_name = existing.business_name or business_name
                existing.semantic_type = existing.semantic_type or semantic_type
                existing.is_time_column = existing.is_time_column or flags.get("is_time_column", False)
                existing.is_metric_column = existing.is_metric_column or flags.get("is_metric_column", False)
                existing.is_dimension_column = existing.is_dimension_column or flags.get("is_dimension_column", False)
                existing.is_sensitive = existing.is_sensitive or flags.get("is_sensitive", False)
                existing.nullable = is_nullable
                existing.default_value = default_value
                existing.time_grain = existing.time_grain or time_grain
                existing.lifecycle_stage = existing.lifecycle_stage or lifecycle_stage
                if sample_values:
                    existing.sample_values = sample_values
            else:
                session.add(
                    SchemaMetadata(
                        data_source_id=data_source_id,
                        table_name=table_name,
                        column_name=column_name,
                        business_name=business_name,
                        semantic_type=semantic_type,
                        is_time_column=flags.get("is_time_column", False),
                        is_metric_column=flags.get("is_metric_column", False),
                        is_dimension_column=flags.get("is_dimension_column", False),
                        is_sensitive=flags.get("is_sensitive", False),
                        nullable=is_nullable,
                        default_value=default_value,
                        time_grain=time_grain,
                        lifecycle_stage=lifecycle_stage,
                        sample_values=sample_values,
                    )
                )
            upserted += 1

        await session.commit()
        print(f"✓ Upserted {upserted} columns into schema_metadata")
        return {"columns_found": len(columns), "upserted": upserted}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync schema metadata from data source")
    parser.add_argument("--data-source-id", required=True, help="UUID of the data source")
    parser.add_argument("--sample-rows", type=int, default=0, help="Number of sample rows to fetch per column (0=skip)")
    args = parser.parse_args()

    await sync_schema_metadata(
        data_source_id=args.data_source_id,
        fetch_samples=args.sample_rows > 0,
        sample_limit=args.sample_rows,
    )


if __name__ == "__main__":
    asyncio.run(main())
