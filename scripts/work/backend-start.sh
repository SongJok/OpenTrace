#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 后端启动（Docker 全栈：postgres + redis + api + agent-worker）
#
# 用法:
#   bash scripts/work/backend-start.sh
#   bash scripts/work/backend-start.sh --with-observability
#   bash scripts/work/backend-start.sh --build
#   bash scripts/work/backend-start.sh --rebuild
#   bash scripts/work/backend-start.sh --verify
#   bash scripts/work/backend-start.sh --infra-only
#   bash scripts/work/backend-start.sh --native
#   bash scripts/work/backend-start.sh --skip-migrate   # 跳过自动迁移
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
cd "$ROOT"

work_ensure_dotenv "$ROOT"
work_load_dotenv "$ROOT"

MODE="docker"
VERIFY=0
INFRA_ONLY=0
SKIP_MIGRATE=0
DOCKER_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --with-observability)
      DOCKER_ARGS+=("$arg")
      ;;
    --build|--rebuild|--no-build|--pull) DOCKER_ARGS+=("$arg") ;;
    --verify) VERIFY=1 ;;
    --infra-only) INFRA_ONLY=1 ;;
    --native) MODE="native" ;;
    --skip-migrate) SKIP_MIGRATE=1 ;;
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

if ! work_dotenv_has_keys "$ROOT"; then
  echo "✗ .env 缺少 DATABASE_URL 或 REDIS_URL"
  exit 1
fi

API_PORT="$(work_default_api_port)"

if work_port_listening "$API_PORT"; then
  if [[ "$MODE" == "docker" && "$INFRA_ONLY" != "1" ]] \
    && docker compose ps api 2>/dev/null | grep -q "Up"; then
    echo "▸ 端口 ${API_PORT} 已由当前 Docker API 服务占用，将复用并刷新后端栈"
  else
    echo "✗ 端口 ${API_PORT} 已被占用，请先执行: bash scripts/work/backend-stop.sh"
    exit 1
  fi
fi

work_docker_preflight "$ROOT"

if [[ "$MODE" == "native" ]]; then
  RT="$(work_runtime_dir)"
  PID_FILE="$RT/api_native.pid"
  LOG_FILE="$RT/api_native.log"

  echo "▸ 启动基础设施 (postgres + redis)..."
  docker compose up -d postgres redis

  echo "▸ 等待 PostgreSQL / Redis..."
  for _ in $(seq 1 40); do
    if docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1 \
      && docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
      break
    fi
    sleep 2
  done

  export DATABASE_URL="$(work_host_db_url)"
  export TOKEN_DB_URL="$DATABASE_URL"
  export REDIS_URL="$(work_host_redis_url)"
  export PYTHONPATH="$ROOT"

  if [[ ! -d "$ROOT/.venv" ]]; then
    echo "▸ 创建 Python 虚拟环境并安装依赖..."
    python3 -m venv "$ROOT/.venv"
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
    pip install -q -r "$ROOT/requirements.txt"
    deactivate
  fi

  echo "▸ 启动 API (native, port=${API_PORT})..."
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  nohup python -m uvicorn gateway.api_gateway.main:app \
    --host 0.0.0.0 --port "$API_PORT" --reload \
    >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  deactivate 2>/dev/null || true

  if ! work_wait_http "http://127.0.0.1:${API_PORT}/api/v1/health" 40 2; then
    echo "✗ API 健康检查失败，日志: $LOG_FILE"
    exit 1
  fi
  echo "✓ API (native): http://127.0.0.1:${API_PORT}"
  echo "  日志: $LOG_FILE"
  exit 0
fi

if [[ "$INFRA_ONLY" == "1" ]]; then
  echo "▸ 仅启动 postgres + redis..."
  docker compose up -d postgres redis
  echo "✓ 基础设施已启动"
  echo "  DATABASE_URL (宿主机): $(work_host_db_url)"
  echo "  REDIS_URL (宿主机):    $(work_host_redis_url)"
  exit 0
fi

bash "$ROOT/scripts/docker_up.sh" ${DOCKER_ARGS+"${DOCKER_ARGS[@]}"}

if ! work_wait_http "http://127.0.0.1:${API_PORT}/api/v1/health/deps" 40 2; then
  echo "✗ health/deps 失败"
  echo "  bash scripts/docker_logs.sh api"
  exit 1
fi

if [[ "$SKIP_MIGRATE" != "1" ]]; then
  if ! work_ensure_db_schema "$ROOT"; then
    exit 1
  fi
else
  if ! work_postgres_users_table_exists "$ROOT"; then
    echo "⚠ 未检测到 public.users，请手动: docker compose exec -T api alembic upgrade head"
  fi
fi

work_seed_dev_user "$ROOT"

if [[ "$VERIFY" == "1" ]] && [[ -f "$ROOT/scripts/verify_docker.sh" ]]; then
  bash "$ROOT/scripts/verify_docker.sh"
fi

echo "✓ 后端 Docker 栈已就绪"
echo "  API:     http://127.0.0.1:${API_PORT}"
echo "  Swagger: http://127.0.0.1:${API_PORT}/docs"
