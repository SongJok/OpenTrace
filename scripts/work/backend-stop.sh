#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 后端关闭
#
# 用法:
#   bash scripts/work/backend-stop.sh              # 停止 Docker 栈 + 本地 native API
#   bash scripts/work/backend-stop.sh --volumes    # 同时删除 Docker 数据卷
#   bash scripts/work/backend-stop.sh --native-only # 仅停宿主机 uvicorn
#   bash scripts/work/backend-stop.sh --infra-only  # 仅停 postgres + redis 容器
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
cd "$ROOT"

NATIVE_ONLY=0
INFRA_ONLY=0
VOLUMES=0

for arg in "$@"; do
  case "$arg" in
    --volumes) VOLUMES=1 ;;
    --native-only) NATIVE_ONLY=1 ;;
    --infra-only) INFRA_ONLY=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg"
      exit 1
      ;;
  esac
done

RT="$(work_runtime_dir)"
work_stop_pidfile "$RT/api_native.pid" "native API"
work_stop_pidfile "$RT/agent_worker.pid" "agent worker"

if [[ "$NATIVE_ONLY" == "1" ]]; then
  echo "✓ 已停止本地 native 进程"
  exit 0
fi

if [[ "$INFRA_ONLY" == "1" ]]; then
  echo "▸ 停止 postgres + redis..."
  docker compose stop postgres redis 2>/dev/null || true
  echo "✓ 基础设施已停止"
  exit 0
fi

if [[ "$VOLUMES" == "1" ]]; then
  bash "$ROOT/scripts/docker_down.sh" --volumes
else
  bash "$ROOT/scripts/docker_down.sh"
fi

echo "✓ 后端已关闭"