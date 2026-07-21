#!/bin/bash
# 内部兼容入口：请优先使用仓库根目录 stop.sh
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
bash "$PROJECT_DIR/stop.sh" "$@"
