#!/bin/bash
# =============================================================================
# OpenTrace — 清理记忆 / 会话 / 文档信息
# 用法: bash scripts/clean_info.sh
# 说明:
#   - 清空 Redis DB 10/11/12（session / cache / memory）
#   - 清空 chat_sessions / trace_logs / documents / document_chunks
#   - 清空 redis_shadow_kv 中 redis_db=10/11/12 的影子记录
#   - 为确保进程内 working memory 失效，若服务正在运行会先停止
#   - 保留 users 等账号基础数据
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$PROJECT_DIR/scripts"
source "$SCRIPT_DIR/_lib.sh"

PYTHON="$(_find_python)"
BACKEND_PORT=14101
FRONTEND_PORT=14108
STOPPED_RUNNING_SERVICES=0

_print_counts() {
  local label="$1"
  echo "  [$label]"
  "$PYTHON" - <<'PY'
import asyncio
import logging
from sqlalchemy import text

from infra.storage.database import AsyncSessionLocal

logging.disable(logging.CRITICAL)

QUERIES = [
    ("chat_sessions", "select count(*) from chat_sessions"),
    ("trace_logs", "select count(*) from trace_logs"),
    ("documents", "select count(*) from documents"),
    ("document_chunks", "select count(*) from document_chunks"),
    ("shadow_db10", "select count(*) from redis_shadow_kv where redis_db = 10"),
    ("shadow_db11", "select count(*) from redis_shadow_kv where redis_db = 11"),
    ("shadow_db12", "select count(*) from redis_shadow_kv where redis_db = 12"),
]


async def main():
    async with AsyncSessionLocal() as db:
        for key, sql in QUERIES:
            result = await db.execute(text(sql))
            print(f"    {key}={result.scalar() or 0}")


asyncio.run(main())
PY
  printf "    redis_db10="
  redis-cli -n 10 DBSIZE
  printf "    redis_db11="
  redis-cli -n 11 DBSIZE
  printf "    redis_db12="
  redis-cli -n 12 DBSIZE
}

_cleanup_database() {
  "$PYTHON" - <<'PY'
import asyncio
import logging

from sqlalchemy import text

from infra.storage.database import AsyncSessionLocal
from memory.working_memory import working_memory as wm

logging.disable(logging.CRITICAL)


SQLS = [
    "delete from document_chunks",
    "delete from documents",
    "delete from trace_logs",
    "delete from chat_sessions",
    "delete from redis_shadow_kv where redis_db in (10, 11, 12)",
]


async def main():
    async with AsyncSessionLocal() as db:
        for sql in SQLS:
            await db.execute(text(sql))
        await db.commit()
    wm._SESSION_WORKING_MEMORIES.clear()
    print("    working_memory_sessions=0")


asyncio.run(main())
PY
}

_banner "OpenTrace — 清理记忆 / 会话 / 文档信息"

if ! command -v redis-cli >/dev/null 2>&1; then
  _error "找不到 redis-cli，无法清理 Redis 记忆分库"
  exit 1
fi

if lsof -ti :"$BACKEND_PORT" >/dev/null 2>&1 || \
   lsof -ti :"$FRONTEND_PORT" >/dev/null 2>&1 || \
   [ -f /tmp/opentrace-backend.pid ] || \
   [ -f /tmp/opentrace-frontend.pid ]; then
  _warn "检测到本地服务正在运行，将先停止服务以确保进程内记忆一并失效"
  bash "$PROJECT_DIR/stop.sh"
  STOPPED_RUNNING_SERVICES=1
fi

_info "清理前统计"
_print_counts "before"

_info "清空 Redis DB 10 / 11 / 12"
redis-cli -n 10 FLUSHDB >/dev/null
redis-cli -n 11 FLUSHDB >/dev/null
redis-cli -n 12 FLUSHDB >/dev/null
_ok "Redis 分库已清空"

_info "清空数据库中的会话 / trace / 文档 / 影子缓存"
_cleanup_database
_ok "数据库记录已清空"

_info "清理后统计"
_print_counts "after"

_ok "信息清理完成"
_info "保留数据: users 等账号基础数据未删除"

if [ "$STOPPED_RUNNING_SERVICES" -eq 1 ]; then
  _warn "服务已停止。如需继续使用，请执行: bash start.sh"
fi
