#!/bin/bash
# =============================================================================
# OpenTrace — bin 重启入口（委托 scripts/restart.sh）
# 用法: bash bin/restart.sh [--verify]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

bash "$PROJECT_DIR/scripts/restart.sh" "$@"
