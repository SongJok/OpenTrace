#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 后端重启（Docker 全栈，启动参数透传 backend-start.sh）
#
# 用法:
#   bash scripts/work/backend-restart.sh
#   bash scripts/work/backend-restart.sh --with-observability
#   bash scripts/work/backend-restart.sh --verify
#   bash scripts/work/backend-restart.sh --native
#   bash scripts/work/backend-restart.sh --volumes   # 停止时删除数据卷
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

STOP_VOLUMES=0
STOP_NATIVE_ONLY=0
STOP_INFRA_ONLY=0
START_WITH_OBS=0
START_VERIFY=0
START_INFRA_ONLY=0
START_NATIVE=0
START_DOCKER_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --volumes) STOP_VOLUMES=1 ;;
    --native-only) STOP_NATIVE_ONLY=1 ;;
    --infra-only) STOP_INFRA_ONLY=1 ;;
    --with-observability) START_WITH_OBS=1 ;;
    --build|--rebuild|--no-build|--pull) START_DOCKER_ARGS+=("$arg") ;;
    --verify) START_VERIFY=1 ;;
    --native) START_NATIVE=1 ;;
    *)
      echo "未知参数: $arg"
      exit 1
      ;;
  esac
done

echo "▸ [1/2] 停止后端..."
stop_cmd=(bash "$SCRIPT_DIR/backend-stop.sh")
[[ "$STOP_VOLUMES" == "1" ]] && stop_cmd+=(--volumes)
[[ "$STOP_NATIVE_ONLY" == "1" ]] && stop_cmd+=(--native-only)
[[ "$STOP_INFRA_ONLY" == "1" ]] && stop_cmd+=(--infra-only)
"${stop_cmd[@]}"

echo "▸ [2/2] 启动后端..."
start_cmd=(bash "$SCRIPT_DIR/backend-start.sh")
[[ "$START_WITH_OBS" == "1" ]] && start_cmd+=(--with-observability)
[[ "$START_VERIFY" == "1" ]] && start_cmd+=(--verify)
[[ "$START_INFRA_ONLY" == "1" ]] && start_cmd+=(--infra-only)
[[ "$START_NATIVE" == "1" ]] && start_cmd+=(--native)
if [ ${#START_DOCKER_ARGS[@]} -gt 0 ]; then
  start_cmd+=("${START_DOCKER_ARGS[@]}")
fi
if ! "${start_cmd[@]}"; then
  echo "✗ 启动失败"
  echo "  docker compose ps"
  echo "  bash scripts/docker_logs.sh api"
  exit 1
fi

echo "✓ 后端重启完成"
