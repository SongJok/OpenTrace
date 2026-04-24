#!/bin/bash
# =============================================================================
# OpenTrace — Docker 停止脚本
# 用法: bash scripts/docker_down.sh
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

REMOVE_VOLUMES=""
if [[ "${1:-}" == "--volumes" ]]; then
  REMOVE_VOLUMES="--volumes"
fi

echo "▸ 停止并移除容器..."
docker compose down --remove-orphans $REMOVE_VOLUMES

echo "✓ Docker 服务已停止"
