#!/usr/bin/env bash
# OpenTrace — scripts/work 公共函数
set -euo pipefail

work_project_dir() {
  local script_path="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  cd "$(dirname "$script_path")/../.." && pwd
}

work_runtime_dir() {
  local root
  root="$(work_project_dir)"
  mkdir -p "$root/.runtime"
  echo "$root/.runtime"
}

work_load_dotenv() {
  local root="$1"
  if [[ -f "$root/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$root/.env"
    set +a
  fi
}

work_default_api_port() {
  echo "${API_PORT:-${APP_PORT:-14100}}"
}

work_default_frontend_port() {
  echo "${FRONTEND_PORT:-14108}"
}

work_port_listening() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    return $?
  fi
  return 1
}

work_wait_http() {
  local url="$1"
  local attempts="${2:-50}"
  local sleep_s="${3:-2}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -sf "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_s"
  done
  return 1
}

work_docker_preflight() {
  local root="$1"
  if ! command -v docker >/dev/null 2>&1; then
    echo "✗ 未找到 docker"
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "✗ docker daemon 未运行"
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "✗ docker compose 不可用"
    return 1
  fi
  return 0
}

work_ensure_dotenv() {
  local root="$1"
  if [[ -f "$root/.env" ]]; then
    return 0
  fi
  if [[ ! -f "$root/.env.example" ]]; then
    echo "✗ 缺少 .env 与 .env.example，无法初始化环境"
    return 1
  fi
  echo "▸ 从 .env.example 创建 .env（请按需填写 LLM API Key）..."
  cp "$root/.env.example" "$root/.env"
  # 本地 Docker Compose 常用默认值
  if ! grep -q '^POSTGRES_PASSWORD=' "$root/.env"; then
    echo "POSTGRES_PASSWORD=changeme" >>"$root/.env"
  fi
  if ! grep -q '^POSTGRES_PORT=' "$root/.env"; then
    echo "POSTGRES_PORT=5432" >>"$root/.env"
  fi
  if ! grep -q '^REDIS_PORT=' "$root/.env"; then
    echo "REDIS_PORT=6380" >>"$root/.env"
  fi
  # 宿主机访问 compose 映射端口
  if grep -q '@postgres:5432' "$root/.env" 2>/dev/null; then
    sed -i.bak 's|@postgres:5432|@127.0.0.1:5432|g' "$root/.env" 2>/dev/null || \
      sed -i '' 's|@postgres:5432|@127.0.0.1:5432|g' "$root/.env" 2>/dev/null || true
    rm -f "$root/.env.bak"
  fi
  if grep -q 'redis://redis:6379' "$root/.env" 2>/dev/null; then
    sed -i.bak 's|redis://redis:6379|redis://127.0.0.1:6380|g' "$root/.env" 2>/dev/null || \
      sed -i '' 's|redis://redis:6379|redis://127.0.0.1:6380|g' "$root/.env" 2>/dev/null || true
    rm -f "$root/.env.bak"
  fi
  if grep -q 'PASSWORD@' "$root/.env" 2>/dev/null; then
    sed -i.bak 's|postgres:PASSWORD@|postgres:changeme@|g' "$root/.env" 2>/dev/null || \
      sed -i '' 's|postgres:PASSWORD@|postgres:changeme@|g' "$root/.env" 2>/dev/null || true
    rm -f "$root/.env.bak"
  fi
  if ! grep -q '^REGISTRATION_ALLOWED_EMAIL_DOMAIN=' "$root/.env"; then
    echo "REGISTRATION_ALLOWED_EMAIL_DOMAIN=example.com" >>"$root/.env"
  fi
  if ! grep -q '^DEV_SEED_USER_EMAIL=' "$root/.env"; then
    echo "DEV_SEED_USER_EMAIL=dev@example.com" >>"$root/.env"
    echo "DEV_SEED_USER_PASSWORD=opentrace123" >>"$root/.env"
  fi
  echo "✓ 已创建 $root/.env"
  return 0
}

work_dotenv_has_keys() {
  local root="$1"
  [[ -f "$root/.env" ]] || return 1
  grep -q '^DATABASE_URL=' "$root/.env" && grep -q '^REDIS_URL=' "$root/.env"
}

work_ensure_frontend_env() {
  local root="$1"
  local api_port
  api_port="$(work_default_api_port)"
  local fe_env="$root/frontend/.env"
  local fe_example="$root/frontend/.env.example"
  if [[ -f "$fe_env" ]]; then
    return 0
  fi
  if [[ -f "$fe_example" ]]; then
    cp "$fe_example" "$fe_env"
  else
    cat >"$fe_env" <<EOF
VITE_API_URL=http://127.0.0.1:${api_port}
VITE_WS_URL=ws://127.0.0.1:${api_port}
EOF
  fi
  echo "✓ 前端环境: $fe_env"
}

work_node_preflight() {
  if ! command -v node >/dev/null 2>&1; then
    echo "✗ 未找到 node（请安装 Node.js 18+）"
    return 1
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "✗ 未找到 npm"
    return 1
  fi
  return 0
}

work_host_db_url() {
  local pw="${POSTGRES_PASSWORD:-changeme}"
  echo "postgresql://postgres:${pw}@127.0.0.1:${POSTGRES_PORT:-5432}/opentrace_v2"
}

work_host_redis_url() {
  echo "redis://127.0.0.1:${REDIS_PORT:-6380}/10"
}

work_stop_pidfile() {
  local pid_file="$1"
  local name="${2:-process}"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "▸ 停止 ${name} (pid=${pid})"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$pid_file"
}

work_postgres_users_table_exists() {
  local root="$1"
  cd "$root"
  docker compose exec -T postgres psql -U postgres -d opentrace_v2 -c "\dt public.users" 2>/dev/null \
    | grep -q "public | users"
}

work_run_alembic_upgrade() {
  local root="$1"
  cd "$root"
  echo "▸ 检查迁移前 schema..."
  if ! docker compose exec -T api python scripts/reconcile_pre_migration_schema.py; then
    echo "✗ 迁移前 schema 检查失败；为避免数据损失，已停止自动升级"
    return 1
  fi
  echo "▸ 执行数据库迁移 (alembic upgrade head)..."
  if ! docker compose exec -T api alembic upgrade head; then
    echo "✗ 迁移失败，查看: bash scripts/docker_logs.sh api"
    return 1
  fi
  echo "✓ 数据库迁移完成"
  return 0
}

work_ensure_db_schema() {
  local root="$1"
  cd "$root"
  # Do not use the presence of `users` as a migration sentinel.  Existing
  # databases can have all legacy tables while still missing newer columns
  # (for example chat_sessions.active_response_id).  Always reconcile to
  # Alembic head; revisions are expected to be idempotent for dev restarts.
  work_run_alembic_upgrade "$root" || return 1
  if ! work_postgres_users_table_exists "$root"; then
    echo "✗ 迁移后仍缺少 public.users"
    return 1
  fi
  return 0
}

work_seed_dev_user() {
  local root="$1"
  cd "$root"
  if ! docker compose ps api 2>/dev/null | grep -q "Up"; then
    echo "⚠ 跳过开发账号种子：api 容器未运行"
    return 0
  fi
  echo "▸ 确保本地开发登录账号..."
  if docker compose exec -T api python scripts/seed_dev_user.py; then
    return 0
  fi
  echo "⚠ 开发账号种子失败（可手动: docker compose exec -T api python scripts/seed_dev_user.py）"
  return 0
}

work_print_dev_banner() {
  local api_port fe_port
  api_port="$(work_default_api_port)"
  fe_port="$(work_default_frontend_port)"
  echo ""
  echo "=============================================="
  echo " OpenTrace 已就绪"
  echo "=============================================="
  echo "  聊天 UI:    http://127.0.0.1:${fe_port}"
  echo "  API:        http://127.0.0.1:${api_port}"
  echo "  Swagger:    http://127.0.0.1:${api_port}/docs"
  echo "  Health:     http://127.0.0.1:${api_port}/api/v1/health"
  echo "----------------------------------------------"
  echo "  开发登录:   dev@example.com / opentrace123"
  echo "  (仅 APP_ENV=development；启动时已自动写入数据库)"
  echo "----------------------------------------------"
  echo "  停止全栈:   bash scripts/work/dev-stop-all.sh"
  echo "  仅停后端:   bash scripts/work/backend-stop.sh"
  echo "  仅停前端:   bash scripts/work/frontend-stop.sh"
  echo "=============================================="
}
