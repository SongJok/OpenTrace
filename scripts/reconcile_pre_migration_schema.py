#!/usr/bin/env python3
"""在 Alembic 升级前收敛开发运行时抢先创建的空表。

历史开发启动流程会先运行 API，API 的 ``Base.metadata.create_all()`` 可能在
Alembic 之前创建新 ORM 表。当数据库 revision 仍停留在这些表对应迁移之前时，
后续 ``alembic upgrade`` 会因 DuplicateTableError 失败。

本脚本按当前 ORM 元数据识别旧运行时抢建表，并且仅删除可证明为空、未被保留表依赖的
对象。企业大脑源数据始终保留；关键迁移表包含数据或 schema 进入混合状态时拒绝操作。
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
    # 当前 ORM 也会创建这些表，并引用下面的知识空间/目录表，因此必须先删依赖表。
    "enterprise_cognitive_versions",
    "enterprise_cognitive_entities",
    "knowledge_spaces",
    "enterprise_directory_memberships",
    "enterprise_directory_sync_runs",
    "enterprise_directory_principals",
    "data_deletion_jobs",
    "legal_holds",
    "revoked_tokens",
)
R0002_RUNTIME_TABLES = ("knowledge_sync_items",)
EMPTY_REVISION_UNSAFE_TABLES = frozenset(
    {
        "task_definitions",
        "task_runs",
        "task_notifications",
        "audit_logs",
        "system_settings",
        "user_ui_settings",
        "responses",
        "response_items",
        "response_events",
        "user_custom_instructions",
        "response_model_calls",
        "knowledge_spaces",
        "knowledge_space_members",
        "knowledge_principal_memberships",
        "knowledge_space_projects",
        "knowledge_connectors",
        "knowledge_sync_runs",
        "knowledge_sync_items",
        "knowledge_sources",
        "knowledge_source_versions",
        "knowledge_pages",
        "knowledge_claims",
        "knowledge_relations",
        "knowledge_compilation_jobs",
        "knowledge_source_permissions",
        "knowledge_review_tasks",
        "enterprise_directory_principals",
        "enterprise_directory_memberships",
        "enterprise_directory_sync_runs",
        "enterprise_cognitive_entities",
        "enterprise_cognitive_versions",
        "enterprise_skills",
    }
)
EMPTY_REVISION_ALWAYS_PRESERVE_TABLES = frozenset(
    {"company_profiles", "company_brain_sources", "company_brain_versions"}
)
BASE_REVISION_UNSAFE_TABLES = frozenset(
    {
        "knowledge_sources",
        "knowledge_spaces",
        "knowledge_space_members",
        "knowledge_principal_memberships",
        "knowledge_space_projects",
        "knowledge_connectors",
        "knowledge_sync_runs",
        "knowledge_sync_items",
        "knowledge_source_permissions",
        "knowledge_review_tasks",
        "enterprise_directory_principals",
        "enterprise_directory_memberships",
        "enterprise_directory_sync_runs",
        "enterprise_cognitive_entities",
        "enterprise_cognitive_versions",
        "enterprise_skills",
    }
)
ENTERPRISE_REVISION_UNSAFE_TABLES = frozenset(
    {
        "knowledge_sync_items",
        "enterprise_directory_principals",
        "enterprise_directory_memberships",
        "enterprise_directory_sync_runs",
        "enterprise_cognitive_entities",
        "enterprise_cognitive_versions",
        "enterprise_skills",
    }
)
BASE_REVISION_RUNTIME_TABLES = frozenset(
    set(R0001_RUNTIME_TABLES)
    | {
        "enterprise_skills",
    }
)
ENTERPRISE_REVISION_RUNTIME_TABLES = frozenset(
    {
        "knowledge_sync_items",
        "enterprise_directory_principals",
        "enterprise_directory_memberships",
        "enterprise_directory_sync_runs",
        "data_deletion_jobs",
        "legal_holds",
        "revoked_tokens",
        "enterprise_cognitive_entities",
        "enterprise_cognitive_versions",
        "enterprise_skills",
    }
)
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


def _runtime_model_tables() -> tuple[str, ...]:
    """返回旧版运行时可能提前创建的 ORM 表。"""
    import infra.storage.model_settings  # noqa: F401
    import infra.storage.models  # noqa: F401
    from infra.storage.database import Base

    return tuple(sorted({table.name for table in Base.metadata.tables.values()}))


def _foreign_key_dependencies(cursor) -> set[tuple[str, str]]:
    """返回 (子表, 父表)，用于按依赖顺序清理空表。"""
    cursor.execute(
        """
        SELECT child.relname, parent.relname
        FROM pg_catalog.pg_constraint AS constraint_record
        JOIN pg_catalog.pg_class AS child
          ON child.oid = constraint_record.conrelid
        JOIN pg_catalog.pg_namespace AS child_schema
          ON child_schema.oid = child.relnamespace
        JOIN pg_catalog.pg_class AS parent
          ON parent.oid = constraint_record.confrelid
        JOIN pg_catalog.pg_namespace AS parent_schema
          ON parent_schema.oid = parent.relnamespace
        WHERE constraint_record.contype = 'f'
          AND child_schema.nspname = 'public'
          AND parent_schema.nspname = 'public'
        """
    )
    return {(str(row[0]), str(row[1])) for row in cursor.fetchall()}


def _non_empty_tables(cursor, tables: Iterable[str]) -> set[str]:
    non_empty: set[str] = set()
    for table in tables:
        cursor.execute(
            sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
                sql.Identifier("public", table)
            )
        )
        if bool(cursor.fetchone()[0]):
            non_empty.add(table)
    return non_empty


def _reconcile_empty_revision(
    cursor,
    *,
    unsafe_tables: frozenset[str] = EMPTY_REVISION_UNSAFE_TABLES,
    candidate_tables: Iterable[str] | None = None,
) -> bool:
    """收敛无 Alembic 版本的旧 ORM schema，只删除可证明为空的表。"""
    model_tables = set(_runtime_model_tables())
    if candidate_tables is not None:
        model_tables &= set(candidate_tables)
    existing = set(_existing_tables(cursor, model_tables))
    if not existing:
        print("✓ 迁移前 schema 检查完成：没有需要收敛的运行时抢建表")
        return False

    non_empty = _non_empty_tables(cursor, existing)
    unsafe_non_empty = sorted(non_empty & unsafe_tables)
    if unsafe_non_empty:
        raise RuntimeError(
            "检测到 Alembic 版本为空且迁移管理表包含数据，拒绝自动清理；请先备份并人工迁移: "
            + ", ".join(unsafe_non_empty)
        )

    dependencies = _foreign_key_dependencies(cursor)
    protected = set(non_empty) | (existing & EMPTY_REVISION_ALWAYS_PRESERVE_TABLES)
    changed = True
    while changed:
        changed = False
        for child, parent in dependencies:
            if parent not in existing or parent in protected:
                continue
            if child not in existing or child in protected or child not in model_tables:
                protected.add(parent)
                changed = True

    drop_set = existing - protected
    if not drop_set:
        print("✓ 迁移前 schema 检查完成：已有数据表均保留，未执行自动清理")
        return False

    dropped: list[str] = []
    remaining = set(drop_set)
    while remaining:
        ready = sorted(
            table
            for table in remaining
            if not any(child in remaining and parent == table for child, parent in dependencies)
        )
        if not ready:
            raise RuntimeError(
                "无法安全计算旧 schema 的外键清理顺序，拒绝自动清理: "
                + ", ".join(sorted(remaining))
            )
        for table in ready:
            cursor.execute(sql.SQL("DROP TABLE {} ").format(sql.Identifier("public", table)))
            remaining.remove(table)
            dropped.append(table)

    print("✓ 已清理旧运行时创建的空表，Alembic 将按正式迁移重建: " + ", ".join(dropped))
    return True


def reconcile() -> bool:
    """安全清理已知的空冲突表；发生清理时返回 True。"""
    with psycopg2.connect(_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opentrace-migration",))
            cursor.execute("SELECT to_regclass('public.alembic_version')")
            has_version_table = cursor.fetchone()[0] is not None
            if not has_version_table:
                return _reconcile_empty_revision(cursor)

            cursor.execute("SELECT version_num FROM public.alembic_version")
            row = cursor.fetchone()
            revision = str(row[0]) if row else None
            if revision is None:
                return _reconcile_empty_revision(cursor)
            if revision in {ENTERPRISE_BASE_REVISION, ENTERPRISE_REVISION}:
                # 这两个版本之后的旧启动流程可能已用当前 ORM 抢建了整批新表；
                # 统一走依赖感知清理，避免只清理部分表后留下新的撞表点。
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
                unsafe_tables = (
                    BASE_REVISION_UNSAFE_TABLES
                    if revision == ENTERPRISE_BASE_REVISION
                    else ENTERPRISE_REVISION_UNSAFE_TABLES
                )
                candidate_tables = (
                    BASE_REVISION_RUNTIME_TABLES
                    if revision == ENTERPRISE_BASE_REVISION
                    else ENTERPRISE_REVISION_RUNTIME_TABLES
                )
                return _reconcile_empty_revision(
                    cursor,
                    unsafe_tables=unsafe_tables,
                    candidate_tables=candidate_tables,
                )
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
