#!/bin/bash
# =============================================================================
# Verify Alembic upgrade is idempotent in docker api container
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "== Verify migration idempotency =="

if ! docker compose ps api >/dev/null 2>&1; then
  echo "✗ api 容器未运行，请先执行: bash restart.sh"
  exit 1
fi

echo "▸ first upgrade head"
docker compose exec -T api alembic upgrade head >/dev/null

echo "▸ second upgrade head"
docker compose exec -T api alembic upgrade head >/dev/null

echo "✓ migration idempotent check passed"
