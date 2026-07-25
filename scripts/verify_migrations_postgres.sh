#!/usr/bin/env bash
# 在两个一次性真实 PostgreSQL 数据库上验证重复执行、单步降级和生产基线升级。
set -euo pipefail
cd "$(dirname "$0")/.."

: "${MIGRATION_TEST_DATABASE_URL:?必须设置 MIGRATION_TEST_DATABASE_URL，且必须指向一次性测试库}"
if [[ "$MIGRATION_TEST_DATABASE_URL" != *migration_test* ]] && [[ "${ALLOW_DESTRUCTIVE_MIGRATION_TEST:-false}" != "true" ]]; then
  echo "拒绝操作非 migration_test 数据库；如确认是一次性库，设置 ALLOW_DESTRUCTIVE_MIGRATION_TEST=true" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
BASELINE="$("$PYTHON_BIN" -c 'import json; print(json.load(open("alembic/migration_policy.json"))["production_baseline_revision"])')"
BASELINE_TEST_DATABASE_URL="${MIGRATION_BASELINE_TEST_DATABASE_URL:-$($PYTHON_BIN - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
url = urlsplit(os.environ["MIGRATION_TEST_DATABASE_URL"])
name = url.path.lstrip("/")
print(urlunsplit((url.scheme, url.netloc, f"/{name}_baseline", url.query, url.fragment)))
PY
)}"
export MIGRATION_BASELINE_TEST_DATABASE_URL="$BASELINE_TEST_DATABASE_URL"

"$PYTHON_BIN" - <<'PY'
import os
from urllib.parse import unquote, urlsplit

import psycopg2
from psycopg2 import sql

for env_name in ("MIGRATION_TEST_DATABASE_URL", "MIGRATION_BASELINE_TEST_DATABASE_URL"):
    parsed = urlsplit(os.environ[env_name])
    database = parsed.path.lstrip("/")
    if "migration_test" not in database:
        raise SystemExit(f"refusing to reset non-test database: {database}")
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=unquote(parsed.username or "postgres"),
        password=unquote(parsed.password or ""),
        dbname="postgres",
    )
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database,),
        )
        cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    conn.close()
PY

run_alembic() {
  local database_url="$1"
  shift
  ALEMBIC_DATABASE_URL="$database_url" "$PYTHON_BIN" -m alembic "$@"
}

echo "== fresh upgrade to head =="
run_alembic "$MIGRATION_TEST_DATABASE_URL" upgrade head

echo "== repeated upgrade is idempotent =="
run_alembic "$MIGRATION_TEST_DATABASE_URL" upgrade head

echo "== downgrade one revision and restore =="
run_alembic "$MIGRATION_TEST_DATABASE_URL" downgrade -1
run_alembic "$MIGRATION_TEST_DATABASE_URL" upgrade head

echo "== fresh production baseline upgrade: $BASELINE =="
run_alembic "$BASELINE_TEST_DATABASE_URL" upgrade "$BASELINE"
run_alembic "$BASELINE_TEST_DATABASE_URL" upgrade head
run_alembic "$BASELINE_TEST_DATABASE_URL" current

echo "== enterprise knowledge ACL and publication lifecycle =="
ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL="$MIGRATION_TEST_DATABASE_URL" \
  "$PYTHON_BIN" scripts/verify_enterprise_knowledge_postgres.py

echo "== durable knowledge connector sync queue =="
ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL="$MIGRATION_TEST_DATABASE_URL" \
  "$PYTHON_BIN" scripts/verify_durable_knowledge_sync_postgres.py

echo "OK: real PostgreSQL migration verification passed"
