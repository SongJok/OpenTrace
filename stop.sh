#!/bin/bash
# =============================================================================
# OpenTrace — 统一 Docker 停止入口
# 用法: bash stop.sh [--volumes]
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

PID_FILE="$PROJECT_DIR/.runtime/agent_worker.pid"
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE" || true)
  if [[ -n "${PID:-}" ]] && kill -0 "$PID" >/dev/null 2>&1; then
    echo "stopping agent worker, pid=$PID"
    kill "$PID" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$PID" >/dev/null 2>&1; then
      kill -9 "$PID" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$PID_FILE"
fi

if [[ "${1:-}" == "--volumes" ]]; then
  bash "$PROJECT_DIR/scripts/docker_down.sh" --volumes
else
  bash "$PROJECT_DIR/scripts/docker_down.sh"
fi
