#!/usr/bin/env python3
"""
Sync table relationships from a live data source's FK constraints.
Queries information_schema.table_constraints and key_column_usage,
upserts verified relationships into table_relationships.

Usage:
  python scripts/sync_table_relationships.py --data-source-id <UUID>
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from execution.data.db_router import DBConnectionInfo, DBRouter
from infra.config.settings import get_settings
from infra.storage.database import SessionLocal
from infra.storage.models import DataSource, TableRelationship

# ── FK query templates per source type ───────────────────────────────────

FK_QUERY_PG = text(
    """
    SELECT
        tc.table_name AS left_table,
        kcu.column_name AS left_column,
        ccu.table_name AS right_table,
        ccu.column_name AS right_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
        ON ccu.constraint_name = tc.constraint_name
        AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema NOT IN ('information_schema', 'pg_catalog')
    ORDER BY tc.table_name
"""
)

FK_QUERY_MYSQL = text(
    """
    SELECT
        kcu.table_name AS left_table,
        kcu.column_name AS left_column,
        kcu.referenced_table_name AS right_table,
        kcu.referenced_column_name AS right_column
    FROM information_schema.key_column_usage kcu
    WHERE kcu.referenced_table_name IS NOT NULL
        AND kcu.table_schema NOT IN ('information_schema', 'mysql', 'sys', 'performance_schema')
    ORDER BY kcu.table_name
"""
)

# ClickHouse doesn't enforce FK constraints but we can look for common naming patterns
CLICKHOUSE_PATTERNS = text(
    """
    SELECT
        table AS left_table,
        name AS left_column,
        '' AS right_table,
        '' AS right_column
    FROM system.columns
    WHERE database = currentDatabase()
        AND match(name, '.*_id$')
        AND table NOT LIKE '.%'
    ORDER BY table, name
"""
)


def _cardinality_hint(left_table: str, right_table: str) -> str | None:
    """Guess cardinality based on table naming conventions."""
    # Tables with _log, _event, _detail suffixes are likely N-side
    if any(left_table.lower().endswith(s) for s in ("_log", "_event", "_detail", "_item", "_record")):
        return "N:1"
    if any(right_table.lower().endswith(s) for s in ("_log", "_event", "_detail", "_item", "_record")):
        return "1:N"
    return None


def _amplification_risk_hint(left_table: str, right_table: str) -> str:
    """Estimate amplification risk."""
    high_risk_suffixes = ("_log", "_event", "_detail", "_history", "_trace")
    if any(left_table.lower().endswith(s) for s in high_risk_suffixes):
        return "high"
    medium_risk_suffixes = ("_item", "_record", "_line", "_entry")
    if any(left_table.lower().endswith(s) for s in medium_risk_suffixes):
        return "medium"
    return "low"


async def _fetch_fk_relationships(conn_info: DataSource) -> list[dict]:
    """Query FK constraints from the target data source."""
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

    query = FK_QUERY_MYSQL if conn_info.source_type in ("mysql", "doris") else FK_QUERY_PG

    async with engine.connect() as conn:
        result = await conn.execute(query)
        rows = result.fetchall()

    await engine.dispose()
    return [dict(r._mapping) for r in rows]


async def sync_table_relationships(data_source_id: str) -> dict:
    """Main sync entry point."""
    async with SessionLocal() as session:
        ds = await session.get(DataSource, data_source_id)
        if not ds:
            raise ValueError(f"DataSource not found: {data_source_id}")

        print(f"Connected to data source: {ds.name} ({ds.source_type})")
        print("Fetching FK constraints...")

        fk_rows = await _fetch_fk_relationships(ds)
        print(f"Found {len(fk_rows)} foreign key constraints")

        upserted = 0
        skipped = 0

        for fk in fk_rows:
            left_table = fk["left_table"]
            left_column = fk["left_column"]
            right_table = fk.get("right_table", "")
            right_column = fk.get("right_column", "")

            # Skip incomplete FK definitions (e.g. from ClickHouse pattern matching)
            if not right_table or not right_column:
                skipped += 1
                continue

            cardinality = _cardinality_hint(left_table, right_table)
            amp_risk = _amplification_risk_hint(left_table, right_table)

            result = await session.execute(
                select(TableRelationship).where(
                    TableRelationship.data_source_id == data_source_id,
                    TableRelationship.left_table == left_table,
                    TableRelationship.left_column == left_column,
                    TableRelationship.right_table == right_table,
                    TableRelationship.right_column == right_column,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                if not existing.is_verified:
                    existing.is_verified = True
                if not existing.cardinality and cardinality:
                    existing.cardinality = cardinality
                if not existing.amplification_risk:
                    existing.amplification_risk = amp_risk
            else:
                session.add(
                    TableRelationship(
                        data_source_id=data_source_id,
                        left_table=left_table,
                        left_column=left_column,
                        right_table=right_table,
                        right_column=right_column,
                        join_type="LEFT",
                        cardinality=cardinality,
                        amplification_risk=amp_risk,
                        is_verified=True,
                    )
                )
            upserted += 1

        await session.commit()

        if skipped:
            print(f"  (skipped {skipped} incomplete FKs)")
        print(f"✓ Upserted {upserted} relationships into table_relationships (verified FK)")
        return {"fk_found": len(fk_rows), "upserted": upserted, "skipped": skipped}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync table relationships from FK constraints")
    parser.add_argument("--data-source-id", required=True, help="UUID of the data source")
    args = parser.parse_args()

    await sync_table_relationships(data_source_id=args.data_source_id)


if __name__ == "__main__":
    asyncio.run(main())
