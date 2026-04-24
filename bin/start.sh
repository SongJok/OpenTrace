#!/bin/bash
# =============================================================================
# OpenTrace — bin 启动入口（委托 scripts/start.sh）
# 用法: bash bin/start.sh [--verify]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

bash "$PROJECT_DIR/scripts/start.sh" "$@"
