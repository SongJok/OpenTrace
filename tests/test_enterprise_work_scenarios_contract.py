"""企业日常工作场景的能力、记忆、证据与审批合同。"""

from __future__ import annotations

from pathlib import Path

from kernel.agent_runtime.manifest import get_manifest
from services.enterprise_scenarios import (
    ENTERPRISE_SCENARIO_CATALOG,
    build_enterprise_scenarios,
)
from tools.builtin_tools import analytics_tools as _analytics_tools  # noqa: F401
from tools.builtin_tools import platform_tools as _platform_tools  # noqa: F401
from tools.registry.registry import registry

ROOT = Path(__file__).resolve().parents[1]


def _scenarios(**overrides: int) -> list[dict[str, object]]:
    state = {
        "project_count": 0,
        "published_knowledge_count": 0,
        "active_data_source_count": 0,
        "installed_skill_count": 0,
        "company_skill_count": 0,
        "active_goal_count": 0,
        "active_task_count": 0,
        "active_alert_count": 0,
    }
    state.update(overrides)
    return build_enterprise_scenarios(**state)


def _by_id(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["id"]): item for item in items}


def test_scenario_catalog_covers_daily_enterprise_work_and_has_unique_ids() -> None:
    assert len(ENTERPRISE_SCENARIO_CATALOG) >= 8
    ids = [item.id for item in ENTERPRISE_SCENARIO_CATALOG]
    assert len(ids) == len(set(ids))
    assert {
        "知识协作",
        "数据决策",
        "管理协作",
        "个人效能",
        "持续工作",
        "风险治理",
        "能力复用",
    }.issubset({item.category for item in ENTERPRISE_SCENARIO_CATALOG})
    assert all(item.deliverables for item in ENTERPRISE_SCENARIO_CATALOG)
    assert all(item.evidence_requirements for item in ENTERPRISE_SCENARIO_CATALOG)


def test_missing_foundations_produce_actionable_setup_routes_without_blocking_calendar() -> None:
    scenarios = _by_id(_scenarios())

    assert scenarios["calendar_focus_plan"]["status"] == "ready"
    assert scenarios["calendar_focus_plan"]["action_route"] == "/chat"
    assert scenarios["trusted_knowledge_answer"]["status"] == "setup_required"
    assert scenarios["trusted_knowledge_answer"]["action_route"] == "/documents"
    assert scenarios["business_metric_review"]["action_route"] == "/databases"
    assert scenarios["decision_brief"]["action_route"] == "/work?tab=projects"
    assert scenarios["governed_skill_workflow"]["action_route"] == "/skills"
    for scenario in scenarios.values():
        if scenario["status"] == "setup_required":
            assert scenario["blockers"]
            assert all(str(blocker["route"]).startswith("/") for blocker in scenario["blockers"])


def test_ready_workspace_marks_adopted_processes_active_and_recommends_immediate_work() -> None:
    scenarios = _by_id(
        _scenarios(
            project_count=2,
            published_knowledge_count=5,
            active_data_source_count=2,
            installed_skill_count=1,
            company_skill_count=1,
            active_goal_count=1,
            active_task_count=1,
            active_alert_count=1,
        )
    )

    assert scenarios["decision_brief"]["status"] == "ready"
    assert scenarios["decision_brief"]["memory_scope"] == "project"
    assert scenarios["long_running_goal"]["status"] == "active"
    assert scenarios["recurring_management_brief"]["action_route"] == "/reports"
    assert scenarios["metric_risk_monitor"]["action_route"] == "/alerts"
    assert scenarios["governed_skill_workflow"]["status"] == "active"
    recommended = [item for item in scenarios.values() if item["recommended"]]
    assert len(recommended) == 3
    assert all(item["status"] != "setup_required" for item in recommended)


def test_scenario_capabilities_and_tools_resolve_to_runtime_truth() -> None:
    manifest = get_manifest()
    for scenario in ENTERPRISE_SCENARIO_CATALOG:
        for capability in scenario.capabilities:
            resolved, registry_name = manifest.resolve_capability_alias(capability)
            assert resolved == capability
            assert registry_name
        specs = [registry.get(tool_name) for tool_name in scenario.tools]
        assert all(spec is not None for spec in specs), scenario.id
        has_side_effect = any(
            spec and spec.side_effect in {"write", "destructive"} for spec in specs
        )
        if has_side_effect:
            assert scenario.approval_policy in {"required_before_write", "inherited"}
            assert scenario.risk in {"mixed", "write"}


def test_scenario_memory_and_evidence_contracts_match_business_processes() -> None:
    catalog = {item.id: item for item in ENTERPRISE_SCENARIO_CATALOG}
    assert catalog["trusted_knowledge_answer"].memory_scope == "conversation"
    assert "已发布知识引用" in catalog["trusted_knowledge_answer"].evidence_requirements
    assert catalog["business_metric_review"].memory_scope == "project"
    assert "只读 SQL 或查询依据" in catalog["business_metric_review"].evidence_requirements
    assert catalog["calendar_focus_plan"].memory_scope == "user"
    assert catalog["calendar_focus_plan"].approval_policy == "required_before_write"
    assert catalog["metric_risk_monitor"].tools == ("create_data_alert",)
    assert catalog["governed_skill_workflow"].capabilities == ("skill_execution",)


def test_workbench_projects_skill_counts_and_scenarios_with_tenant_boundaries() -> None:
    source = (ROOT / "services/enterprise_workbench.py").read_text(encoding="utf-8")
    for model in ("UserSkillInstallation", "EnterpriseSkill"):
        assert f"{model}.tenant_id == tenant_id" in source
        assert f"{model}.workspace_id == workspace_id" in source
    assert "UserSkillInstallation.user_id == user.id" in source
    assert "classification_allows(knowledge_context.clearance" in source
    assert '"scenarios": scenarios' in source
    assert '"installed_skills": installed_skill_count' in source
    assert '"company_skills": company_skill_count' in source
