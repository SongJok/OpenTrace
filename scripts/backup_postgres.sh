#!/usr/bin/env bash
# 一致性 PostgreSQL 逻辑备份；生产环境应由托管服务 PITR 作为第一恢复手段。
set -euo pipefail

: "${DATABASE_URL:?必须设置 DATABASE_URL}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
TARGET="$BACKUP_DIR/opentrace-$STAMP.dump"
TMP="$TARGET.tmp"
trap 'rm -f "$TMP"' EXIT

pg_dump --dbname="$DATABASE_URL" --format=custom --compress=9 --no-owner --no-acl --file="$TMP"
pg_restore --list "$TMP" >/dev/null
sha256sum "$TMP" > "$TARGET.sha256.tmp"
mv "$TMP" "$TARGET"
mv "$TARGET.sha256.tmp" "$TARGET.sha256"
find "$BACKUP_DIR" -type f \( -name 'opentrace-*.dump' -o -name 'opentrace-*.dump.sha256' \) \
  -mtime "+$RETENTION_DAYS" -delete
printf 'backup=%s\nchecksum=%s\n' "$TARGET" "$TARGET.sha256"
