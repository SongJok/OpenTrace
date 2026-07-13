#!/bin/bash
# =============================================================================
# OpenTrace — 统一 Docker 启动入口
# 用法:
#   bash start.sh
#   bash start.sh --with-observability
#   bash start.sh --verify
#   bash start.sh --no-agent-worker
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

WITH_OBS=""
VERIFY="0"
for arg in "$@"; do
  case "$arg" in
    --with-observability) WITH_OBS="--with-observability" ;;
    --verify) VERIFY="1" ;;
    --no-agent-worker) echo "[WARN] --no-agent-worker is deprecated in docker mode; ignoring" ;;
  esac
done

# Ensure target API port is available before startup
if lsof -iTCP:14100 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "✗ 端口 14100 已被占用，请先释放后再启动"
  exit 1
fi

bash "$PROJECT_DIR/scripts/docker_up.sh" ${WITH_OBS}

# Post-start hard checks
if ! curl -sf "http://127.0.0.1:14100/api/v1/health" >/dev/null 2>&1; then
  echo "✗ health 检查失败"
  exit 1
fi
if ! curl -sf "http://127.0.0.1:14100/api/v1/health/deps" >/dev/null 2>&1; then
  echo "✗ health/deps 检查失败"
  exit 1
fi

# The API container intentionally does not run Alembic in its uvicorn command.
# Reconcile the database after the services are healthy so an existing
# database cannot silently miss columns introduced by a newer release.
echo "▸ 同步数据库迁移 (alembic upgrade head)..."
if ! docker compose exec -T api alembic upgrade head; then
  echo "✗ 数据库迁移失败，请查看: bash scripts/docker_logs.sh api"
  exit 1
fi
echo "✓ 数据库迁移完成"

if ! (cd "$PROJECT_DIR" && docker compose exec -T postgres psql -U postgres -d opentrace_v2 -c "\dt public.users" | grep -q "public | users"); then
  echo "✗ 核心表 public.users 不存在，请检查迁移"
  exit 1
fi

if [[ "$VERIFY" == "1" ]]; then
  bash "$PROJECT_DIR/scripts/verify_docker.sh"
fi
