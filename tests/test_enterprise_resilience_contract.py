from pathlib import Path

from scripts.chaos_responses import SCENARIOS

ROOT = Path(__file__).resolve().parents[1]


def test_required_failure_scenarios_are_defined():
    assert {
        "redis-outage",
        "worker-kill",
        "duplicate-delivery",
        "model-timeout",
        "unknown-side-effect",
    }.issubset(SCENARIOS)
    assert all(item.expected for item in SCENARIOS.values())


def test_backup_and_restore_scripts_are_fail_closed():
    backup = (ROOT / "scripts" / "backup_postgres.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts" / "restore_postgres.sh").read_text(encoding="utf-8")
    assert "pg_restore --list" in backup
    assert "sha256sum" in backup
    assert "RESTORE_DATABASE_URL" in restore
    assert "ALLOW_PRODUCTION_RESTORE" in restore
