from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from infra.alerts.scheduler import (
    _mark_rule_error,
    _record_rule_error,
    evaluate_condition,
    extract_alert_value,
)
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


def test_alert_failure_is_persisted_and_rescheduled_for_early_retry(monkeypatch):
    from infra.alerts import scheduler

    monkeypatch.setattr(scheduler.settings, "alert_scheduler_retry_seconds", 60)
    original_next_run = datetime.now(UTC) + timedelta(hours=1)
    rule = SimpleNamespace(status="active", last_error=None, next_run_at=original_next_run)

    message = _mark_rule_error(rule, "database unavailable")

    assert message == "database unavailable"
    assert rule.last_error == message
    assert datetime.now(UTC) + timedelta(seconds=50) <= rule.next_run_at
    assert rule.next_run_at < original_next_run


@pytest.mark.asyncio
async def test_repeated_alert_error_does_not_spam_notifications() -> None:
    db = MagicMock()
    rule = SimpleNamespace(
        id="alert-1",
        user_id="user-1",
        name="销售额预警",
        status="active",
        last_error=None,
        next_run_at=datetime.now(UTC) + timedelta(hours=1),
    )

    await _record_rule_error(db, rule, "database unavailable")
    assert db.add.call_count == 1
    assert db.add.call_args.args[0].title == "销售额预警 检查失败"

    db.add.reset_mock()
    await _record_rule_error(db, rule, "database unavailable")
    db.add.assert_not_called()


def test_main_loop_platform_tools_have_governed_side_effect_levels():
    assert registry.get("list_scheduled_tasks").side_effect == "read"
    assert registry.get("list_data_alerts").side_effect == "read"
    assert registry.get("create_scheduled_task").side_effect == "write"
    assert registry.get("create_data_alert").side_effect == "write"
    runner = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    assert '"user_id": response.user_id' in runner
    assert '"tenant_id": response.tenant_id' in runner
    assert "from tools.builtin_tools import platform_tools" in runner


def test_active_alert_migration_is_chained_after_project_knowledge():
    source = (ROOT / "alembic/versions/20260728_active_alerts.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260727_project_knowledge_scope"' in source
    assert "CREATE TABLE IF NOT EXISTS public.alert_rules" in source
    assert "CREATE TABLE IF NOT EXISTS public.alert_events" in source


def test_skill_subprocess_execution_is_disabled_in_managed_profiles():
    settings_source = (ROOT / "infra/config/settings.py").read_text(encoding="utf-8")
    assert settings_source.count("self.skills_subprocess_execution_enabled = False") >= 2
