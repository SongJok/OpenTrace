"""组织级工作台模板的持久化、匹配和场景投影合同。"""

from pathlib import Path

import pytest

from gateway.api_gateway.main import app
from gateway.api_gateway.routers.enterprise_admin import WorkbenchTemplateInput
from infra.storage.models import EnterpriseWorkbenchTemplate, EnterpriseWorkbenchTemplateTarget
from services.enterprise_scenarios import (
    apply_organization_templates,
    build_enterprise_scenarios,
)
from services.enterprise_workbench_templates import _validate_configuration

ROOT = Path(__file__).resolve().parents[1]


def _ready_scenarios() -> list[dict[str, object]]:
    return build_enterprise_scenarios(
        project_count=1,
        published_knowledge_count=1,
        active_data_source_count=1,
        installed_skill_count=1,
        company_skill_count=1,
        active_goal_count=0,
        active_task_count=0,
        active_alert_count=0,
    )


def test_workbench_template_models_preserve_scope_version_and_relational_targets() -> None:
    assert EnterpriseWorkbenchTemplate.__tablename__ == "enterprise_workbench_templates"
    assert (
        EnterpriseWorkbenchTemplateTarget.__tablename__ == "enterprise_workbench_template_targets"
    )
    assert {
        "tenant_id",
        "workspace_id",
        "audience_type",
        "scenario_ids",
        "priority",
        "status",
        "version",
        "created_by",
        "updated_by",
    }.issubset(EnterpriseWorkbenchTemplate.__table__.columns.keys())
    assert {"template_id", "principal_id", "tenant_id", "workspace_id"}.issubset(
        EnterpriseWorkbenchTemplateTarget.__table__.columns.keys()
    )


def test_workbench_template_admin_api_exposes_governed_crud() -> None:
    paths = app.openapi()["paths"]
    collection = paths["/api/v1/admin/enterprise/workbench/templates"]
    resource = paths["/api/v1/admin/enterprise/workbench/templates/{template_id}"]
    assert {"get", "post"}.issubset(collection)
    assert {"put", "delete"}.issubset(resource)
    assert "201" in collection["post"]["responses"]
    payload = WorkbenchTemplateInput(
        name="财务经营工作台",
        audience_type="principals",
        principal_ids=["principal-finance"],
        scenario_ids=["business_metric_review", "decision_brief"],
        priority=300,
        status="active",
    )
    assert payload.scenario_ids[0] == "business_metric_review"


def test_template_validation_rejects_unknown_scenarios_and_unsafe_audiences() -> None:
    with pytest.raises(ValueError, match="all_audience_cannot_have_principals"):
        _validate_configuration(
            audience_type="all",
            principal_ids=["principal-finance"],
            scenario_ids=["business_metric_review"],
            status="active",
        )
    with pytest.raises(ValueError, match="unknown_workbench_scenario"):
        _validate_configuration(
            audience_type="principals",
            principal_ids=["principal-finance"],
            scenario_ids=["invented_runtime"],
            status="active",
        )


def test_matched_templates_merge_priority_order_without_changing_readiness() -> None:
    scenarios = apply_organization_templates(
        _ready_scenarios(),
        [
            {
                "id": "template-high",
                "name": "财务负责人",
                "scenario_ids": ["metric_risk_monitor", "business_metric_review"],
            },
            {
                "id": "template-low",
                "name": "管理协作",
                "scenario_ids": ["decision_brief", "business_metric_review"],
            },
        ],
    )
    assert [item["id"] for item in scenarios[:3]] == [
        "metric_risk_monitor",
        "business_metric_review",
        "decision_brief",
    ]
    assert all(item["recommended"] for item in scenarios[:3])
    assert all(item["organization_recommended"] for item in scenarios[:3])
    assert scenarios[1]["recommendation_reason"] == "财务负责人、管理协作"
    assert scenarios[0]["status"] == "ready"
    assert scenarios[0]["approval_required"] is True


def test_blocked_organization_scenario_stays_blocked_and_is_not_recommended() -> None:
    scenarios = build_enterprise_scenarios(
        project_count=0,
        published_knowledge_count=0,
        active_data_source_count=0,
        installed_skill_count=0,
        company_skill_count=0,
        active_goal_count=0,
        active_task_count=0,
        active_alert_count=0,
    )
    personalized = apply_organization_templates(
        scenarios,
        [{"id": "template", "name": "经营岗位", "scenario_ids": ["decision_brief"]}],
    )
    assert personalized[0]["id"] == "decision_brief"
    assert personalized[0]["status"] == "setup_required"
    assert personalized[0]["recommended"] is False
    assert personalized[0]["organization_recommended"] is True
    assert personalized[0]["blockers"]
    assert any(item["recommended"] for item in personalized if item["status"] != "setup_required")


def test_workbench_template_resolution_keeps_every_scope_and_effective_time_boundary() -> None:
    source = (ROOT / "services/enterprise_workbench_templates.py").read_text(encoding="utf-8")
    for model in (
        "EnterpriseDirectoryMembership",
        "EnterpriseDirectoryPrincipal",
        "EnterpriseWorkbenchTemplate",
        "EnterpriseWorkbenchTemplateTarget",
    ):
        assert f"{model}.tenant_id == tenant_id" in source
        assert f"{model}.workspace_id == workspace_id" in source
    assert "EnterpriseDirectoryMembership.user_id == user_id" in source
    assert "EnterpriseDirectoryMembership.effective_from <= effective_at" in source
    assert "EnterpriseDirectoryMembership.effective_to > effective_at" in source
    assert "EnterpriseDirectoryPrincipal.external_id.in_(pending_parent_ids)" in source
    assert ".with_for_update()" in source
    assert source.count("row.updated_at = datetime.now(UTC)") == 2
    assert "db.commit" not in source


def test_r0015_migration_is_additive_reversible_and_runtime_verified() -> None:
    migration = (ROOT / "alembic/versions/r0015_enterprise_workbench_templates.py").read_text(
        encoding="utf-8"
    )
    database = (ROOT / "infra/storage/database.py").read_text(encoding="utf-8")
    assert 'revision = "r0015_enterprise_workbench_templates"' in migration
    assert 'down_revision = "r0014_enterprise_reports"' in migration
    for table in (
        "enterprise_workbench_templates",
        "enterprise_workbench_template_targets",
    ):
        assert f'"{table}"' in migration
        assert f'op.drop_table("{table}")' in migration
        assert f'"{table}",' in database
