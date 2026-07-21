#!/bin/bash
# =============================================================================
# OpenTrace — Docker 日志脚本
# 用法: bash scripts/docker_logs.sh [service]
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

SERVICE="${1:-}"
if [[ -n "$SERVICE" ]]; then
  docker compose logs -f --tail=200 "$SERVICE"
else
  docker compose logs -f --tail=200
fi
