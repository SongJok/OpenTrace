#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 前端一键启动（安装依赖 + Vite dev + 就绪检查）
#
# 用法:
#   bash scripts/work/frontend-boot-all-in-one.sh
#   bash scripts/work/frontend-boot-all-in-one.sh --install
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
work_load_dotenv "$ROOT"
FE_PORT="$(work_default_frontend_port)"
API_PORT="$(work_default_api_port)"

echo "=============================================="
echo " OpenTrace 前端一键启动"
echo "=============================================="

INSTALL_ARG=()
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL_ARG=(--install) ;;
    *) ;;
  esac
done

if [[ ${#INSTALL_ARG[@]} -eq 0 ]] && [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  INSTALL_ARG=(--install)
fi

bash "$SCRIPT_DIR/frontend-start.sh" "${INSTALL_ARG[@]}"

echo ""
echo "----------------------------------------------"
echo "  UI:      http://127.0.0.1:${FE_PORT}"
echo "  API 代理: ${VITE_API_URL:-http://127.0.0.1:${API_PORT}}"
echo "----------------------------------------------"
echo " 停止: bash scripts/work/frontend-stop.sh"
echo "=============================================="