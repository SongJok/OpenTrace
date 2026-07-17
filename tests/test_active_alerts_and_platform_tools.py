from pathlib import Path

from infra.alerts.scheduler import evaluate_condition, extract_alert_value
from tools.builtin_tools import platform_tools  # noqa: F401
from tools.registry.registry import registry


ROOT = Path(__file__).resolve().parents[1]


def test_alert_value_extraction_and_deterministic_conditions():
    rows = [{"metric": 10}, {"metric": 20}, {"metric": None}]
    assert extract_alert_value(rows, "metric", "sum") == 30
    assert extract_alert_value(rows, "metric", "avg") == 15
    assert extract_alert_value(rows, "metric", "count") == 3
    assert evaluate_condition("gt", 12, 10, None) == (True, 12)
    triggered, change = evaluate_condition("change_pct_gt", 120, 10, 100)
    assert triggered is True
    assert change == 20


def test_main_loop_platform_tools_have_governed_side_effect_levels():
    assert registry.get("list_scheduled_tasks").side_effect == "read"
    assert registry.get("list_data_alerts").side_effect == "read"
    assert registry.get("create_scheduled_task").side_effect == "write"
    assert registry.get("create_data_alert").side_effect == "write"
    runner = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    assert '"user_id": response.user_id' in runner
    assert '"tenant_id": response.tenant_id' in runner
    assert 'from tools.builtin_tools import platform_tools' in runner


def test_active_alert_migration_is_chained_after_project_knowledge():
    source = (ROOT / "alembic/versions/20260728_active_alerts.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260727_project_knowledge_scope"' in source
    assert "CREATE TABLE IF NOT EXISTS public.alert_rules" in source
    assert "CREATE TABLE IF NOT EXISTS public.alert_events" in source


def test_skill_subprocess_execution_is_disabled_in_managed_profiles():
    settings_source = (ROOT / "infra/config/settings.py").read_text(encoding="utf-8")
    assert settings_source.count("self.skills_subprocess_execution_enabled = False") >= 2
