#!/bin/bash
# =============================================================================
# OpenTrace — 统一 Docker 重启入口
# 用法:
#   bash restart.sh
#   bash restart.sh --with-observability
#   bash restart.sh --verify
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "▸ [1/2] 停止现有服务..."
bash "$PROJECT_DIR/stop.sh"

echo "▸ [2/2] 启动服务..."
if ! bash "$PROJECT_DIR/start.sh" "$@"; then
  echo "✗ 启动失败，建议执行以下排障命令："
  echo "  - docker compose ps"
  echo "  - bash scripts/docker_logs.sh api"
  echo "  - bash scripts/docker_logs.sh agent-worker"
  exit 1
fi

echo "✓ 重启完成"
