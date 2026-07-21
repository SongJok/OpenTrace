#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 全栈关闭（前端 + 后端 Docker）
#
# 用法:
#   bash scripts/work/dev-stop-all.sh
#   bash scripts/work/dev-stop-all.sh --volumes
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

VOLUMES=0
for arg in "$@"; do
  case "$arg" in
    --volumes) VOLUMES=1 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg"
      exit 1
      ;;
  esac
done

echo "▸ 停止前端..."
bash "$SCRIPT_DIR/frontend-stop.sh"

echo "▸ 停止后端..."
if [[ "$VOLUMES" == "1" ]]; then
  bash "$SCRIPT_DIR/backend-stop.sh" --volumes
else
  bash "$SCRIPT_DIR/backend-stop.sh"
fi

echo "✓ 全栈已关闭"