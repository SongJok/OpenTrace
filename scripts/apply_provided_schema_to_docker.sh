#!/bin/bash
# =============================================================================
# 一键清空并重建 Docker Postgres（使用仓库内 SQL）
# 用法：bash scripts/apply_provided_schema_to_docker.sh
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SQL_FILE="$PROJECT_DIR/scripts/sql/provided_schema.sql"

DOCKER_PG_SERVICE="${DOCKER_PG_SERVICE:-postgres}"
DOCKER_PG_USER="${DOCKER_PG_USER:-postgres}"
DOCKER_PG_PASSWORD="${DOCKER_PG_PASSWORD:-950514abc}"
DOCKER_PG_DB="${DOCKER_PG_DB:-opentrace_v2}"

echo "== OpenTrace: apply provided schema to docker postgres =="

test -f "$SQL_FILE" || { echo "✗ SQL 文件不存在: $SQL_FILE"; exit 1; }

cd "$PROJECT_DIR"

echo "▸ 检查 docker compose postgres 服务..."
docker compose ps "$DOCKER_PG_SERVICE" >/dev/null

echo "▸ 清空目标数据库 public schema..."
docker compose exec -T "$DOCKER_PG_SERVICE" sh -lc \
  "PGPASSWORD='$DOCKER_PG_PASSWORD' psql -U '$DOCKER_PG_USER' -d '$DOCKER_PG_DB' -v ON_ERROR_STOP=1 -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'"

echo "▸ 预处理 SQL（按依赖顺序重排关键段落）..."
TMP_SQL="$(mktemp)"
python3 - "$SQL_FILE" "$TMP_SQL" <<'PY'
import re
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding='utf-8')
out = Path(sys.argv[2])

# Split by section marker: -- public.<table> definition
parts = re.split(r'(?=^-- public\.[a-z_]+ definition\n)', src, flags=re.M)
header = []
sections = {}
for p in parts:
    m = re.match(r'^-- public\.([a-z_]+) definition\n', p)
    if not m:
        header.append(p)
        continue
    sections[m.group(1)] = p

order = [
    'users',
    'chat_sessions',
    'documents',
    'document_chunks',
    'trace_logs',
]

assembled = ''.join(header)
used = set()
for name in order:
    if name in sections:
        assembled += sections[name]
        used.add(name)

# Append remaining sections in original appearance order
for p in parts:
    m = re.match(r'^-- public\.([a-z_]+) definition\n', p)
    if not m:
        continue
    name = m.group(1)
    if name in used:
        continue
    assembled += p

out.write_text(assembled, encoding='utf-8')
PY

echo "▸ 导入提供的 SQL..."
cat "$TMP_SQL" | docker compose exec -T "$DOCKER_PG_SERVICE" sh -lc \
  "PGPASSWORD='$DOCKER_PG_PASSWORD' psql -U '$DOCKER_PG_USER' -d '$DOCKER_PG_DB' -v ON_ERROR_STOP=1"
rm -f "$TMP_SQL"

echo "▸ 校验关键表..."
docker compose exec -T "$DOCKER_PG_SERVICE" sh -lc \
  "PGPASSWORD='$DOCKER_PG_PASSWORD' psql -U '$DOCKER_PG_USER' -d '$DOCKER_PG_DB' -Atc \"select tablename from pg_tables where schemaname='public' and tablename in ('users','documents','document_chunks','chat_sessions','trace_logs') order by tablename;\""

echo "▸ 重启业务容器..."
docker compose restart api agent-worker >/dev/null

echo "✓ 已完成：数据库已按提供脚本重建并重启服务"
echo "✓ 建议验证：curl -s http://127.0.0.1:14100/api/v1/health/deps"
