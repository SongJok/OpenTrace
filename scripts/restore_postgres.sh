#!/usr/bin/env bash
# 仅恢复到显式指定的空数据库，防止误覆盖生产。
set -euo pipefail

: "${RESTORE_DATABASE_URL:?必须设置 RESTORE_DATABASE_URL，且必须指向隔离恢复库}"
BACKUP_FILE="${1:?用法: scripts/restore_postgres.sh BACKUP.dump}"
case "$RESTORE_DATABASE_URL" in
  *opentrace_v2*)
    if [ "${ALLOW_PRODUCTION_RESTORE:-false}" != "true" ]; then
      echo "拒绝恢复到名称包含 opentrace_v2 的数据库；灾难恢复需显式 ALLOW_PRODUCTION_RESTORE=true" >&2
      exit 2
    fi
    ;;
esac
sha256sum --check "$BACKUP_FILE.sha256"
pg_restore --dbname="$RESTORE_DATABASE_URL" --clean --if-exists --no-owner --no-acl "$BACKUP_FILE"
psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT COUNT(*) AS response_count FROM responses;'
