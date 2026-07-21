#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 后端一键启动（Docker：依赖 + API + Agent Worker + 健康检查）
#
# 等价于: bash scripts/work/backend-start.sh
# 额外: 打印常用链接与排障命令
#
# 用法:
#   bash scripts/work/backend-boot-all-in-one.sh
#   bash scripts/work/backend-boot-all-in-one.sh --with-observability --verify
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
work_load_dotenv "$ROOT"
API_PORT="$(work_default_api_port)"

echo "=============================================="
echo " OpenTrace 后端一键启动"
echo "=============================================="

bash "$SCRIPT_DIR/backend-start.sh" "$@"

echo ""
echo "----------------------------------------------"
echo " 服务地址"
echo "  API:        http://127.0.0.1:${API_PORT}"
echo "  Swagger:    http://127.0.0.1:${API_PORT}/docs"
echo "  Health:     http://127.0.0.1:${API_PORT}/api/v1/health"
echo "  Health deps: http://127.0.0.1:${API_PORT}/api/v1/health/deps"
echo "----------------------------------------------"
echo " 排障: bash scripts/docker_logs.sh api"
echo " 停止: bash scripts/work/backend-stop.sh"
echo "=============================================="