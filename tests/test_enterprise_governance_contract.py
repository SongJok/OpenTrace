from pathlib import Path

from infra.storage.models import Attachment
from services.data_governance import deletion_table_order

ROOT = Path(__file__).resolve().parents[1]


def test_deletion_order_covers_core_tenant_tables_but_preserves_governance_evidence():
    names = {table.name for table in deletion_table_order()}
    assert {"responses", "chat_sessions", "documents", "data_sources", "attachments"}.issubset(
        names
    )
    assert not {"legal_holds", "data_deletion_jobs", "audit_logs"}.intersection(names)


def test_attachment_model_uses_scoped_object_metadata():
    columns = Attachment.__table__.c
    for name in ("tenant_id", "workspace_id", "storage_backend", "object_key", "object_etag"):
        assert name in columns


def test_migration_enables_rls_for_response_facts():
    source = (ROOT / "alembic" / "versions" / "r0004_enterprise_runtime_governance.py").read_text(
        encoding="utf-8"
    )
    assert "ALTER TABLE" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "response_events" in source
    assert "app.workspace_id" in source
    assert "app.service_role" in source
