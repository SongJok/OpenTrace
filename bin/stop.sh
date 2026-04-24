#!/bin/bash
# =============================================================================
# OpenTrace — bin 停止入口（委托 scripts/stop.sh）
# 用法: bash bin/stop.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

bash "$PROJECT_DIR/scripts/stop.sh"
