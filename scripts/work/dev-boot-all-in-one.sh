#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 全栈一键启动（推荐入口）
#
# 1. 确保 .env / 前端 .env
# 2. Docker: postgres + redis + api + agent-worker + 自动 Alembic 迁移
# 3. Vite 前端 (14108)
#
# 用法:
#   bash scripts/work/dev-boot-all-in-one.sh
#   bash scripts/work/dev-boot-all-in-one.sh --with-observability
#   bash scripts/work/dev-boot-all-in-one.sh --backend-only
#   bash scripts/work/dev-boot-all-in-one.sh --frontend-only
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
BACKEND_ONLY=0
FRONTEND_ONLY=0
EXTRA_BACKEND_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --backend-only) BACKEND_ONLY=1 ;;
    --frontend-only) FRONTEND_ONLY=1 ;;
    --with-observability|--verify) EXTRA_BACKEND_ARGS+=("$arg") ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg（可用 --backend-only / --frontend-only / --with-observability）"
      exit 1
      ;;
  esac
done

if [[ "$BACKEND_ONLY" == "1" ]] && [[ "$FRONTEND_ONLY" == "1" ]]; then
  echo "✗ 不能同时指定 --backend-only 与 --frontend-only"
  exit 1
fi

work_ensure_dotenv "$ROOT"
work_load_dotenv "$ROOT"

echo "=============================================="
echo " OpenTrace 全栈一键启动"
echo "=============================================="

if [[ "$FRONTEND_ONLY" != "1" ]]; then
  # bash 3.2 + set -u: empty "${arr[@]}" is treated as unbound
  bash "$SCRIPT_DIR/backend-boot-all-in-one.sh" ${EXTRA_BACKEND_ARGS+"${EXTRA_BACKEND_ARGS[@]}"}
fi

if [[ "$BACKEND_ONLY" != "1" ]]; then
  work_ensure_frontend_env "$ROOT"
  bash "$SCRIPT_DIR/frontend-boot-all-in-one.sh"
fi

work_print_dev_banner