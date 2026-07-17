from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from gateway.api_gateway.resource_scope import accessible_data_sources_statement
from infra.storage.models import SkillCatalogEntry, UserSkillInstallation
from knowledge.compiler import compile_payload


def _chunk(chunk_id: str, content: str, heading: str = "流程") -> SimpleNamespace:
    return SimpleNamespace(id=chunk_id, content=content, chunk_metadata=f'{{"heading":"{heading}"}}')


def test_orchestration_config_changes_compiler_output() -> None:
    pages, claims, _ = compile_payload(
        document_id="doc",
        source_version_id="version",
        title="操作手册",
        chunks=[_chunk("c1", "第一步完成开户。第二步完成验证。第三步提交材料。")],
        orchestration={
            "summary_length": 80,
            "content_limit": 1000,
            "min_claim_length": 4,
            "max_claims_per_page": 2,
            "page_type_keywords": {"policy": ["开户"]},
        },
    )

    section = next(page for page in pages if page["slug"] != "overview")
    assert section["page_type"] == "policy"
    assert len(claims) == 2
    assert len(section["summary"]) <= 80


def test_acl_statement_contains_owner_tenant_permission_and_expiry_guards() -> None:
    sql = str(accessible_data_sources_statement(
        user_id="user-1",
        tenant_metadata={"tenant_id": "tenant-1", "workspace_id": "workspace-1"},
        required_permission="query",
    ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "data_sources.user_id = 'user-1'" in sql
    assert "resource_permissions.subject_user_id = 'user-1'" in sql
    assert "resource_permissions.permission IN ('query', 'edit', 'admin')" in sql
    assert "resource_permissions.expires_at IS NULL" in sql
    assert "data_sources.tenant_id = 'tenant-1'" in sql


def test_skill_installation_schema_is_account_scoped_and_catalog_backed() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in UserSkillInstallation.__table__.constraints
        if getattr(constraint, "columns", None) is not None
    }
    assert ("user_id", "tenant_id", "workspace_id", "catalog_skill_id") in unique_columns
    assert UserSkillInstallation.__table__.c.catalog_skill_id.foreign_keys
    assert SkillCatalogEntry.__table__.c.external_id.unique is True

