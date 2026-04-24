#!/bin/bash
# =============================================================================
# 将本机 PostgreSQL 指定数据库完整迁移到 docker compose 的 postgres 服务
#
# 用法：
#   bash scripts/migrate_local_pg_to_docker.sh
#
# 可选环境变量（不填则使用默认值）：
#   LOCAL_PG_HOST=127.0.0.1
#   LOCAL_PG_PORT=5432
#   LOCAL_PG_USER=postgres
#   LOCAL_PG_PASSWORD=950514abc
#   LOCAL_PG_DB=opentrace_v2
#
#   DOCKER_PG_SERVICE=postgres
#   DOCKER_PG_USER=postgres
#   DOCKER_PG_PASSWORD=950514abc
#   DOCKER_PG_DB=opentrace_v2
#
# 说明：
# - 这是“全量覆盖导入”：会清空目标库 public schema 后再导入
# - 会保留一份 SQL 备份到 .runtime/ 目录
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"
mkdir -p "$RUNTIME_DIR"

LOCAL_PG_HOST="${LOCAL_PG_HOST:-127.0.0.1}"
LOCAL_PG_PORT="${LOCAL_PG_PORT:-5432}"
LOCAL_PG_USER="${LOCAL_PG_USER:-postgres}"
LOCAL_PG_PASSWORD="${LOCAL_PG_PASSWORD:-950514abc}"
LOCAL_PG_DB="${LOCAL_PG_DB:-opentrace_v2}"

DOCKER_PG_SERVICE="${DOCKER_PG_SERVICE:-postgres}"
DOCKER_PG_USER="${DOCKER_PG_USER:-postgres}"
DOCKER_PG_PASSWORD="${DOCKER_PG_PASSWORD:-950514abc}"
DOCKER_PG_DB="${DOCKER_PG_DB:-opentrace_v2}"

STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="$RUNTIME_DIR/local_pg_dump_${LOCAL_PG_DB}_${STAMP}.sql"

echo "== OpenTrace: 本地 PostgreSQL -> Docker PostgreSQL 全量迁移 =="
echo "本地:  ${LOCAL_PG_USER}@${LOCAL_PG_HOST}:${LOCAL_PG_PORT}/${LOCAL_PG_DB}"
echo "目标:  ${DOCKER_PG_SERVICE}:${DOCKER_PG_DB} (user=${DOCKER_PG_USER})"

action_check_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "✗ 缺少命令: $cmd"
    exit 1
  fi
}

action_check_cmd pg_dump
action_check_cmd docker
action_check_cmd sed

echo "▸ 检查 docker compose postgres 服务是否可用..."
cd "$PROJECT_DIR"
docker compose ps "$DOCKER_PG_SERVICE" >/dev/null

# 1) 从本地库导出全量 SQL（schema + data）
echo "▸ 导出本地数据库到 SQL 文件..."
PGPASSWORD="$LOCAL_PG_PASSWORD" pg_dump \
  -h "$LOCAL_PG_HOST" \
  -p "$LOCAL_PG_PORT" \
  -U "$LOCAL_PG_USER" \
  -d "$LOCAL_PG_DB" \
  --no-owner \
  --no-privileges \
  --encoding=UTF8 \
  > "$DUMP_FILE"

echo "✓ 导出完成: $DUMP_FILE"

# 2) 清空目标库 public schema（彻底覆盖）
echo "▸ 清空目标数据库 public schema..."
docker compose exec -T "$DOCKER_PG_SERVICE" sh -lc \
  "PGPASSWORD='$DOCKER_PG_PASSWORD' psql -U '$DOCKER_PG_USER' -d '$DOCKER_PG_DB' -v ON_ERROR_STOP=1 -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'"

# 3) 导入 SQL
echo "▸ 导入 SQL 到目标数据库..."
cat "$DUMP_FILE" | docker compose exec -T "$DOCKER_PG_SERVICE" sh -lc \
  "PGPASSWORD='$DOCKER_PG_PASSWORD' psql -U '$DOCKER_PG_USER' -d '$DOCKER_PG_DB' -v ON_ERROR_STOP=1"

# 4) 校验关键表
echo "▸ 校验核心表..."
docker compose exec -T "$DOCKER_PG_SERVICE" sh -lc \
  "PGPASSWORD='$DOCKER_PG_PASSWORD' psql -U '$DOCKER_PG_USER' -d '$DOCKER_PG_DB' -Atc \"select tablename from pg_tables where schemaname='public' and tablename in ('users','documents','document_chunks','chat_sessions') order by tablename;\""

echo "✓ 迁移完成。"
echo "  备份文件保留在: $DUMP_FILE"
echo "  建议下一步执行:"
echo "    docker compose restart api agent-worker"
echo "    curl -s http://127.0.0.1:14100/api/v1/health/deps"
