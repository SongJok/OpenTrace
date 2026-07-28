#!/usr/bin/env python3
"""在 Alembic 升级前收敛开发运行时抢先创建的空表。

历史开发启动流程会先运行 API，API 的 ``Base.metadata.create_all()`` 可能在
Alembic 之前创建新 ORM 表。当数据库 revision 仍停留在这些表对应迁移之前时，
后续 ``alembic upgrade`` 会因 DuplicateTableError 失败。

本脚本只处理已知 revision 和已知冲突表，并且仅在所有冲突表为空、schema 未进入
混合状态时执行事务性清理。任何业务数据都会阻止自动操作。
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import psycopg2
from psycopg2 import sql

from infra.config.settings import settings

ENTERPRISE_BASE_REVISION = "20260803_chatgpt_five_pillars"
ENTERPRISE_REVISION = "r0001_enterprise_knowledge_base"

R0001_RUNTIME_TABLES = (
    "knowledge_sync_items",
    "knowledge_review_tasks",
    "knowledge_source_permissions",
    "knowledge_sync_runs",
    "knowledge_connectors",
    "knowledge_space_projects",
    "knowledge_principal_memberships",
    "knowledge_space_members",
    "knowledge_spaces",
    "enterprise_directory_memberships",
    "enterprise_directory_sync_runs",
    "enterprise_directory_principals",
    "data_deletion_jobs",
    "legal_holds",
    "revoked_tokens",
)
R0002_RUNTIME_TABLES = ("knowledge_sync_items",)
R0001_SOURCE_COLUMNS = frozenset(
    {
        "space_id",
        "connector_id",
        "steward_id",
        "classification",
        "source_system",
        "sync_status",
        "effective_from",
        "effective_to",
        "review_due_at",
        "deleted_at",
    }
)


def cleanup_tables_for_revision(revision: str | None) -> tuple[str, ...]:
    """返回当前 revision 允许清理的、由运行时提前创建的表。"""
    if revision == ENTERPRISE_BASE_REVISION:
        return R0001_RUNTIME_TABLES
    if revision == ENTERPRISE_REVISION:
        return R0002_RUNTIME_TABLES
    return ()


def _database_url() -> str:
    raw = os.getenv("DATABASE_URL") or settings.database_url
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


def _existing_tables(cursor, candidates: Iterable[str]) -> tuple[str, ...]:
    tables: list[str] = []
    for table in candidates:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        if cursor.fetchone()[0] is not None:
            tables.append(table)
    return tuple(tables)


def reconcile() -> bool:
    """安全清理已知的空冲突表；发生清理时返回 True。"""
    with psycopg2.connect(_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opentrace-migration",))
            cursor.execute("SELECT to_regclass('public.alembic_version')")
            if cursor.fetchone()[0] is None:
                print("✓ 迁移前 schema 检查完成：尚无 Alembic 版本表")
                return False

            cursor.execute("SELECT version_num FROM public.alembic_version")
            row = cursor.fetchone()
            revision = str(row[0]) if row else None
            candidates = cleanup_tables_for_revision(revision)
            if not candidates:
                print(f"✓ 迁移前 schema 检查完成：当前 revision={revision or 'none'}")
                return False

            existing = _existing_tables(cursor, candidates)
            if not existing:
                print(f"✓ 迁移前 schema 检查完成：revision={revision} 无抢建表")
                return False

            if revision == ENTERPRISE_BASE_REVISION:
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'knowledge_sources'
                      AND column_name = ANY(%s)
                    """,
                    (list(R0001_SOURCE_COLUMNS),),
                )
                mixed_columns = sorted(str(item[0]) for item in cursor.fetchall())
                if mixed_columns:
                    raise RuntimeError(
                        "检测到企业知识迁移混合状态，拒绝自动清理；knowledge_sources 已存在列: "
                        + ", ".join(mixed_columns)
                    )

            non_empty: list[str] = []
            for table in existing:
                cursor.execute(
                    sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
                        sql.Identifier("public", table)
                    )
                )
                if bool(cursor.fetchone()[0]):
                    non_empty.append(table)
            if non_empty:
                raise RuntimeError(
                    "检测到迁移前抢建表包含数据，拒绝自动清理: " + ", ".join(non_empty)
                )

            for table in existing:
                cursor.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier("public", table)))

    print("✓ 已安全清理运行时提前创建的空表，Alembic 将按正式迁移重建: " + ", ".join(existing))
    return True


def main() -> None:
    reconcile()


if __name__ == "__main__":
    main()
