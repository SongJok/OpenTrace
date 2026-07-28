#!/usr/bin/env bash
# 在一次性数据库执行恢复、迁移和核心事实表完整性验证。
set -euo pipefail
: "${RESTORE_DATABASE_URL:?必须设置 RESTORE_DATABASE_URL}"
BACKUP_FILE="${1:?用法: scripts/verify_disaster_recovery.sh BACKUP.dump}"
RESTORE_DATABASE_URL="$RESTORE_DATABASE_URL" bash scripts/restore_postgres.sh "$BACKUP_FILE"
DATABASE_URL="$RESTORE_DATABASE_URL" python -m alembic upgrade head
psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
SELECT CASE WHEN COUNT(*) = 1 THEN 'single_alembic_head' ELSE 1/0::text END FROM alembic_version;
SELECT COUNT(*) AS orphan_events
FROM response_events e LEFT JOIN responses r ON r.id=e.response_id WHERE r.id IS NULL;
SELECT COUNT(*) AS orphan_items
FROM response_items i LEFT JOIN responses r ON r.id=i.response_id WHERE r.id IS NULL;
SELECT COUNT(*) AS pending_outbox FROM response_outbox WHERE status='pending';
SQL
