"""Migration entrypoint must execute where the Compose database hostname resolves."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_migration_script_uses_api_container_and_supports_idempotency_check() -> None:
    text = (ROOT / "scripts/migrate.sh").read_text(encoding="utf-8")
    assert "docker compose exec -T api alembic upgrade head" in text
    assert "--verify" in text
    assert "postgres 主机名只在 Docker Compose 网络内可解析" in text


def test_backend_start_always_reconciles_existing_databases() -> None:
    text = (ROOT / "scripts/work/lib.sh").read_text(encoding="utf-8")
    start = text.index("work_ensure_db_schema()")
    end = text.index("\n}\n", start) + 2
    function = text[start:end]
    assert "work_run_alembic_upgrade \"$root\"" in function
    # A legacy users table is not proof that newer response/conversation
    # columns exist; startup must not return early on that check.
    assert "if work_postgres_users_table_exists \"$root\"; then" not in function


def test_root_start_runs_migrations_after_api_readiness() -> None:
    text = (ROOT / "start.sh").read_text(encoding="utf-8")
    assert "docker compose exec -T api alembic upgrade head" in text
    assert text.index("health/deps") < text.index("alembic upgrade head")


def test_response_lease_migration_tolerates_runtime_schema_repair() -> None:
    text = (ROOT / "alembic/versions/20260720_response_leases.py").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS request_payload" in text
    assert "CREATE INDEX IF NOT EXISTS ix_responses_lease_owner" in text
    assert "CREATE TABLE IF NOT EXISTS response_tool_executions" in text
