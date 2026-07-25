#!/bin/bash
# =============================================================================
# OpenTrace — 统一 Docker 启动入口
# 用法:
#   bash start.sh
#   bash start.sh --build
#   bash start.sh --rebuild
#   bash start.sh --pull
#   bash start.sh --with-observability
#   bash start.sh --verify
#   bash start.sh --no-agent-worker
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

frontend_port="${FRONTEND_PORT:-}"
if [[ -z "$frontend_port" && -f "$PROJECT_DIR/.env" ]]; then
  frontend_port="$(sed -n 's/^FRONTEND_PORT=//p' "$PROJECT_DIR/.env" | tail -n 1)"
fi
frontend_port="${frontend_port:-14108}"
if ! [[ "$frontend_port" =~ ^[0-9]+$ ]]; then
  echo "✗ FRONTEND_PORT 必须是端口号，当前值: $frontend_port"
  exit 1
fi

VERIFY="0"
DOCKER_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --with-observability)
      DOCKER_ARGS+=("$arg")
      ;;
    --build|--rebuild|--no-build|--pull) DOCKER_ARGS+=("$arg") ;;
    --verify) VERIFY="1" ;;
    --no-agent-worker) echo "[WARN] --no-agent-worker is deprecated in docker mode; ignoring" ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg"
      exit 1
      ;;
  esac
done

# Ensure target API port is available before startup
if lsof -iTCP:14100 -sTCP:LISTEN >/dev/null 2>&1; then
  if (cd "$PROJECT_DIR" && docker compose ps --status running -q api | grep -q .); then
    echo "▸ 当前项目 API 已运行，将复用现有容器"
  else
    echo "✗ 端口 14100 已被占用，请先释放后再启动"
    exit 1
  fi
fi

# Ensure target production frontend port is available before startup.
if lsof -iTCP:"$frontend_port" -sTCP:LISTEN >/dev/null 2>&1; then
  if (cd "$PROJECT_DIR" && docker compose ps --status running -q frontend | grep -q .); then
    echo "▸ 当前项目生产前端已运行，将复用现有容器"
  else
    echo "✗ 端口 $frontend_port 已被占用，请停止 Vite 或释放端口后再启动"
    exit 1
  fi
fi

# bash 3.2 + set -u: empty "${arr[@]}" is treated as unbound
bash "$PROJECT_DIR/scripts/docker_up.sh" ${DOCKER_ARGS+"${DOCKER_ARGS[@]}"}

# Post-start hard checks
if ! curl -sf "http://127.0.0.1:14100/api/v1/health" >/dev/null 2>&1; then
  echo "✗ health 检查失败"
  exit 1
fi
if ! curl -sf "http://127.0.0.1:14100/api/v1/health/deps" >/dev/null 2>&1; then
  echo "✗ health/deps 检查失败"
  exit 1
fi
if ! curl -sf "http://127.0.0.1:${frontend_port}/chat" >/dev/null 2>&1; then
  echo "✗ 生产前端健康检查失败"
  exit 1
fi

# The API container intentionally does not run Alembic in its uvicorn command.
# Reconcile the database after the services are healthy so an existing
# database cannot silently miss columns introduced by a newer release.
echo "▸ 检查迁移前 schema..."
if ! docker compose exec -T api python scripts/reconcile_pre_migration_schema.py; then
  echo "✗ 迁移前 schema 检查失败；为避免数据损失，已停止自动升级"
  exit 1
fi
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

# 开发环境必须有一个与当前认证状态机一致的可登录账号；脚本会在非开发环境自行跳过。
echo "▸ 确保本地开发登录账号..."
if ! (cd "$PROJECT_DIR" && docker compose exec -T api python scripts/seed_dev_user.py); then
  echo "✗ 开发登录账号初始化失败"
  exit 1
fi

if [[ "$VERIFY" == "1" ]]; then
  bash "$PROJECT_DIR/scripts/verify_docker.sh"
fi
