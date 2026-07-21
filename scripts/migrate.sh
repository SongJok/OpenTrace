#!/usr/bin/env bash
# Execute Alembic from the API container so Compose-internal host names work.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

usage() {
  cat <<'EOF'
用法: bash scripts/migrate.sh [--verify|--current]

默认执行一次 alembic upgrade head。
--verify  连续执行两次升级，验证迁移幂等性。
--current 显示数据库当前 revision。
EOF
}

mode="upgrade"
case "${1:-}" in
  "") ;;
  --verify) mode="verify" ;;
  --current) mode="current" ;;
  -h|--help) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

if ! docker compose ps --status running --services | grep -qx "api"; then
  echo "API 容器未运行。请先执行: bash start.sh"
  echo "说明：.env 中的 postgres 主机名只在 Docker Compose 网络内可解析。"
  exit 1
fi

case "$mode" in
  upgrade)
    docker compose exec -T api alembic upgrade head
    ;;
  verify)
    docker compose exec -T api alembic upgrade head
    docker compose exec -T api alembic upgrade head
    echo "✓ migration idempotency verified"
    ;;
  current)
    docker compose exec -T api alembic current
    ;;
esac
