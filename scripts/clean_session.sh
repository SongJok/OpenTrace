#!/bin/bash
# =============================================================================
# OpenTrace — 清理会话与记忆数据（恢复接近初始状态）
# 用法:
#   bash scripts/clean_session.sh
#   bash scripts/clean_session.sh --with-users
# 说明:
#   默认保留 users 表，仅清理业务数据。
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

WITH_USERS="0"
if [[ "${1:-}" == "--with-users" ]]; then
  WITH_USERS="1"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "✗ docker 未安装或不可用"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "✗ docker daemon 未启动"
  exit 1
fi

echo "▸ 清理数据库中的会话/记忆/任务/审计/文档数据..."
SQL="
TRUNCATE TABLE
  trace_logs,
  chat_sessions,
  user_memories,
  feedback,
  task_runs,
  task_notifications,
  task_definitions,
  audit_logs,
  document_chunks,
  documents,
  reasoning_traces,
  tool_stats
RESTART IDENTITY CASCADE;
"

if [[ "$WITH_USERS" == "1" ]]; then
  SQL="$SQL
TRUNCATE TABLE
  user_memory_settings,
  user_ui_settings,
  users
RESTART IDENTITY CASCADE;
"
else
  SQL="$SQL
DELETE FROM user_memory_settings;
DELETE FROM user_ui_settings;
"
fi

docker compose exec -T postgres psql -U postgres -d opentrace_v2 -v ON_ERROR_STOP=1 -c "$SQL"

echo "▸ 清理 Redis 缓存数据..."
docker compose exec -T redis redis-cli FLUSHALL >/dev/null

echo "✓ 会话与记忆数据已清理完成"
if [[ "$WITH_USERS" == "1" ]]; then
  echo "⚠ users 也已清理，需重新 seed 用户"
fi
