"""Migration entrypoint must execute where the Compose database hostname resolves."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_migration_script_uses_api_container_and_supports_idempotency_check() -> None:
    text = (ROOT / "scripts/migrate.sh").read_text(encoding="utf-8")
    assert "docker compose exec -T api alembic upgrade head" in text
    assert "--verify" in text
    assert "postgres 主机名只在 Docker Compose 网络内可解析" in text
