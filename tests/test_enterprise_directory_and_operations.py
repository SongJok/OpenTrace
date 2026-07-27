"""企业目录、运营中心和迁移的企业级合约。"""

from pathlib import Path

from gateway.api_gateway.main import app
from gateway.api_gateway.routers.enterprise_admin import DirectorySyncRequest
from infra.storage.models import (
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseDirectorySyncRun,
)

ROOT = Path(__file__).resolve().parents[1]


def test_directory_models_are_durable_and_tenant_scoped() -> None:
    assert EnterpriseDirectoryPrincipal.__tablename__ == "enterprise_directory_principals"
    assert EnterpriseDirectoryMembership.__tablename__ == "enterprise_directory_memberships"
    assert EnterpriseDirectorySyncRun.__tablename__ == "enterprise_directory_sync_runs"
    assert {
        "tenant_id",
        "workspace_id",
        "principal_type",
        "external_id",
        "source",
        "status",
        "last_synced_at",
    }.issubset(EnterpriseDirectoryPrincipal.__table__.columns.keys())
    assert {
        "tenant_id",
        "workspace_id",
        "user_id",
        "principal_id",
        "effective_from",
        "effective_to",
    }.issubset(EnterpriseDirectoryMembership.__table__.columns.keys())
    assert {"provider", "authoritative", "stats", "requested_by", "completed_at"}.issubset(
        EnterpriseDirectorySyncRun.__table__.columns.keys()
    )


def test_directory_sync_contract_has_enterprise_bounds() -> None:
    payload = DirectorySyncRequest(
        provider="scim",
        authoritative=True,
        principals=[
            {
                "principal_type": "department",
                "external_id": "finance",
                "display_name": "财务部",
            }
        ],
        memberships=[
            {
                "user_email": "member@example.com",
                "principal_type": "department",
                "principal_external_id": "finance",
            }
        ],
    )
    assert payload.provider == "scim"
    assert payload.authoritative is True
    assert payload.principals[0].external_id == "finance"


def test_enterprise_admin_exposes_directory_and_operations_surfaces() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/admin/enterprise/operations/overview": {"get"},
        "/api/v1/admin/enterprise/directory/principals": {"get"},
        "/api/v1/admin/enterprise/directory/memberships": {"get"},
        "/api/v1/admin/enterprise/directory/sync-runs": {"get"},
        "/api/v1/admin/enterprise/directory/sync": {"post"},
    }
    for path, methods in expected.items():
        assert methods.issubset(paths[path])
    assert "202" in paths["/api/v1/admin/enterprise/directory/sync"]["post"]["responses"]


def test_directory_sync_projects_memberships_into_knowledge_acl() -> None:
    source = (ROOT / "services/enterprise_directory.py").read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in source
    assert "await db.flush()" in source
    assert "KnowledgePrincipalMembership" in source
    assert '"directory_principal_id"' in source
    assert '"directory_membership_id"' in source
    assert "authoritative" in source
    assert "enterprise_directory_sync" in source


def test_operations_projection_uses_database_facts_and_scope() -> None:
    source = (ROOT / "services/enterprise_operations.py").read_text(encoding="utf-8")
    for model in (
        "ResponseRecord",
        "GoalRun",
        "TaskDefinition",
        "AlertRule",
        "DataSource",
        "KnowledgeSource",
        "KnowledgeSpace",
        "EnterpriseDirectoryPrincipal",
        "EnterpriseDirectoryMembership",
    ):
        assert f"{model}.tenant_id == tenant_id" in source
        assert f"{model}.workspace_id == workspace_id" in source
    assert "ResponseModelCall" in source
    assert "Redis" not in source
    assert "db.commit" not in source


def test_r0003_migration_is_additive_and_reversible() -> None:
    migration = (ROOT / "alembic/versions/r0003_enterprise_directory_and_operations.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "r0003_enterprise_directory_and_operations"' in migration
    assert 'down_revision = "r0002_durable_knowledge_sync_queue"' in migration
    for table in (
        "enterprise_directory_principals",
        "enterprise_directory_memberships",
        "enterprise_directory_sync_runs",
    ):
        assert f'"{table}"' in migration
        assert f'op.drop_table("{table}")' in migration
