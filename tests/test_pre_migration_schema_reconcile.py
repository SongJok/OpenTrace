from pathlib import Path

from scripts.reconcile_pre_migration_schema import (
    ENTERPRISE_BASE_REVISION,
    ENTERPRISE_REVISION,
    R0001_RUNTIME_TABLES,
    cleanup_tables_for_revision,
)

ROOT = Path(__file__).resolve().parents[1]


def test_cleanup_scope_is_limited_to_known_pre_enterprise_revisions() -> None:
    assert cleanup_tables_for_revision(ENTERPRISE_BASE_REVISION) == R0001_RUNTIME_TABLES
    assert cleanup_tables_for_revision(ENTERPRISE_REVISION) == ("knowledge_sync_items",)
    assert cleanup_tables_for_revision("r0002_durable_knowledge_sync_queue") == ()
    assert cleanup_tables_for_revision(None) == ()


def test_cleanup_order_drops_dependent_tables_before_parents() -> None:
    order = list(R0001_RUNTIME_TABLES)
    assert order.index("knowledge_sync_items") < order.index("knowledge_sync_runs")
    assert order.index("knowledge_sync_runs") < order.index("knowledge_connectors")
    assert order.index("knowledge_connectors") < order.index("knowledge_spaces")
    assert order.index("knowledge_space_members") < order.index("knowledge_spaces")


def test_reconciler_refuses_non_empty_or_mixed_schema_by_contract() -> None:
    text = (ROOT / "scripts/reconcile_pre_migration_schema.py").read_text(encoding="utf-8")
    assert "检测到迁移前抢建表包含数据，拒绝自动清理" in text
    assert "检测到企业知识迁移混合状态，拒绝自动清理" in text
    assert "pg_advisory_xact_lock" in text
    assert "DROP TABLE" in text
