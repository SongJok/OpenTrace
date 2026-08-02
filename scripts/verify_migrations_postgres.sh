#!/usr/bin/env bash
# 在一次性真实 PostgreSQL 数据库上验证重复执行、单步降级和历史 schema 恢复。
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

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
RUNTIME_COLLISION_TEST_DATABASE_URL="${MIGRATION_RUNTIME_COLLISION_TEST_DATABASE_URL:-$($PYTHON_BIN - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
url = urlsplit(os.environ["MIGRATION_TEST_DATABASE_URL"])
name = url.path.lstrip("/")
print(urlunsplit((url.scheme, url.netloc, f"/{name}_runtime_collision", url.query, url.fragment)))
PY
)}"
EMPTY_REVISION_TEST_DATABASE_URL="${MIGRATION_EMPTY_REVISION_TEST_DATABASE_URL:-$($PYTHON_BIN - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
url = urlsplit(os.environ["MIGRATION_TEST_DATABASE_URL"])
name = url.path.lstrip("/")
print(urlunsplit((url.scheme, url.netloc, f"/{name}_empty_revision", url.query, url.fragment)))
PY
)}"
export MIGRATION_BASELINE_TEST_DATABASE_URL="$BASELINE_TEST_DATABASE_URL"
export MIGRATION_RUNTIME_COLLISION_TEST_DATABASE_URL="$RUNTIME_COLLISION_TEST_DATABASE_URL"
export MIGRATION_EMPTY_REVISION_TEST_DATABASE_URL="$EMPTY_REVISION_TEST_DATABASE_URL"

"$PYTHON_BIN" - <<'PY'
import os
from urllib.parse import unquote, urlsplit

import psycopg2
from psycopg2 import sql

for env_name in (
    "MIGRATION_TEST_DATABASE_URL",
    "MIGRATION_BASELINE_TEST_DATABASE_URL",
    "MIGRATION_RUNTIME_COLLISION_TEST_DATABASE_URL",
    "MIGRATION_EMPTY_REVISION_TEST_DATABASE_URL",
):
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

echo "== recover empty tables created by legacy runtime create_all =="
run_alembic "$RUNTIME_COLLISION_TEST_DATABASE_URL" upgrade 20260803_chatgpt_five_pillars
DATABASE_URL="$RUNTIME_COLLISION_TEST_DATABASE_URL" "$PYTHON_BIN" - <<'PY'
import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

import infra.storage.models  # noqa: F401
from infra.storage.database import Base

url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)


async def create_runtime_tables() -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


asyncio.run(create_runtime_tables())
PY
DATABASE_URL="$RUNTIME_COLLISION_TEST_DATABASE_URL" \
  "$PYTHON_BIN" scripts/reconcile_pre_migration_schema.py
run_alembic "$RUNTIME_COLLISION_TEST_DATABASE_URL" upgrade head
run_alembic "$RUNTIME_COLLISION_TEST_DATABASE_URL" current

echo "== preserve legacy runtime schema and data when alembic revision is empty =="
DATABASE_URL="$EMPTY_REVISION_TEST_DATABASE_URL" "$PYTHON_BIN" - <<'PY'
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import infra.storage.models  # noqa: F401
from infra.storage.database import Base
from infra.storage.models import (
    CompanyBrainSource,
    CompanyBrainVersion,
    CompanyProfile,
    User,
)

engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as connection:
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(connection)
with Session(engine) as session:
    user = User(
        id="migration-user",
        email="migration@example.com",
        hashed_password="not-a-login-secret",
        status="active",
        role="admin",
    )
    session.add(user)
    session.flush()
    profile = CompanyProfile(
        id="migration-company",
        legal_name="迁移验收公司",
        short_name="迁移验收",
        description="必须在无版本升级后保留",
        created_by=user.id,
    )
    session.add(profile)
    session.flush()
    version = CompanyBrainVersion(
        id="migration-company-version",
        company_id=profile.id,
        version=1,
        status="published",
        content="# 企业大脑\n\n印章借用必须审批并留痕。",
        char_count=20,
        long_term_chars=20,
        published_by=user.id,
        created_by=user.id,
    )
    profile.current_version_id = version.id
    session.add(version)
    session.flush()
    session.add(
        CompanyBrainSource(
            id="migration-company-source",
            company_id=profile.id,
            folder="行政",
            memory_tier="long",
            source_type="manual",
            title="印章制度",
            source_content="印章借用必须审批并留痕。",
            processed_content="印章借用必须审批并留痕。",
            status="processed",
            created_by=user.id,
        )
    )
    session.commit()
engine.dispose()
PY
DATABASE_URL="$EMPTY_REVISION_TEST_DATABASE_URL" \
  "$PYTHON_BIN" scripts/reconcile_pre_migration_schema.py
run_alembic "$EMPTY_REVISION_TEST_DATABASE_URL" upgrade head
run_alembic "$EMPTY_REVISION_TEST_DATABASE_URL" upgrade head
DATABASE_URL="$EMPTY_REVISION_TEST_DATABASE_URL" "$PYTHON_BIN" - <<'PY'
import os

import psycopg2

url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
with psycopg2.connect(url) as conn, conn.cursor() as cursor:
    cursor.execute("SELECT version_num FROM alembic_version")
    assert cursor.fetchone() == ("r0012_company_brain",)
    cursor.execute(
        "SELECT count(*) FROM company_brain_versions "
        "WHERE id = 'migration-company-version' "
        "AND content LIKE '%印章借用必须审批并留痕%'"
    )
    assert cursor.fetchone() == (1,)
PY

echo "== enterprise knowledge ACL and publication lifecycle =="
ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL="$MIGRATION_TEST_DATABASE_URL" \
  "$PYTHON_BIN" scripts/verify_enterprise_knowledge_postgres.py

echo "== durable knowledge connector sync queue =="
ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL="$MIGRATION_TEST_DATABASE_URL" \
  "$PYTHON_BIN" scripts/verify_durable_knowledge_sync_postgres.py

echo "OK: real PostgreSQL migration verification passed"
