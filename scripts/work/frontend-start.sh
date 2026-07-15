#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 前端开发服务启动（Vite，默认 14108）
#
# 用法:
#   bash scripts/work/frontend-start.sh
#   bash scripts/work/frontend-start.sh --install   # 启动前 npm install
#   bash scripts/work/frontend-start.sh --no-wait   # 不等待 HTTP 就绪
#
# 环境变量（可选，来自 .env）:
#   FRONTEND_PORT / VITE_API_URL
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
FRONTEND_DIR="$ROOT/frontend"
work_ensure_dotenv "$ROOT"
work_load_dotenv "$ROOT"
work_ensure_frontend_env "$ROOT"

DO_INSTALL=0
WAIT_HTTP=1

for arg in "$@"; do
  case "$arg" in
    --install) DO_INSTALL=1 ;;
    --no-wait) WAIT_HTTP=0 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg"
      exit 1
      ;;
  esac
done

FE_PORT="$(work_default_frontend_port)"
API_PORT="$(work_default_api_port)"
RT="$(work_runtime_dir)"
PID_FILE="$RT/frontend_dev.pid"
LOG_FILE="$RT/frontend_dev.log"
SCREEN_NAME="opentrace-vite-${FE_PORT}"

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "✗ 未找到 frontend 目录: $FRONTEND_DIR"
  exit 1
fi

work_node_preflight

if work_port_listening "$FE_PORT"; then
  screen_sessions=""
  if command -v screen >/dev/null 2>&1; then
    screen_sessions="$(screen -ls 2>&1 || true)"
  fi
  if [[ "$screen_sessions" == *"${SCREEN_NAME}"* ]]; then
    echo "✓ 前端已在运行 (${SCREEN_NAME}, port=${FE_PORT})"
    echo "  UI: http://127.0.0.1:${FE_PORT}"
    exit 0
  fi
  if [[ -f "$PID_FILE" ]]; then
    old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
      echo "✓ 前端已在运行 (pid=${old_pid}, port=${FE_PORT})"
      echo "  UI: http://127.0.0.1:${FE_PORT}"
      exit 0
    fi
  fi
  echo "✗ 端口 ${FE_PORT} 已被占用，请先: bash scripts/work/frontend-stop.sh"
  exit 1
fi

cd "$FRONTEND_DIR"

if [[ "$DO_INSTALL" == "1" ]] || [[ ! -d node_modules ]]; then
  echo "▸ npm install..."
  npm install
fi

export VITE_API_URL="${VITE_API_URL:-http://127.0.0.1:${API_PORT}}"
export VITE_WS_URL="${VITE_WS_URL:-ws://127.0.0.1:${API_PORT}}"

echo "▸ 启动 Vite (port=${FE_PORT}, API=${VITE_API_URL})..."
# The Codex/macOS development runner reaps ordinary nohup descendants when
# the launcher exits.  A detached screen session gives Vite an independent
# session while retaining the nohup fallback for minimal Linux hosts.
if command -v screen >/dev/null 2>&1; then
  screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
  screen -dmS "$SCREEN_NAME" bash -lc \
    "cd '$FRONTEND_DIR' && exec npm run dev -- --port '$FE_PORT' --host >>'$LOG_FILE' 2>&1"
  # The screen socket becomes visible asynchronously; store a stable marker
  # instead of racing its OS pid.  frontend-stop resolves the named session.
  echo "screen:${SCREEN_NAME}" >"$PID_FILE"
else
  nohup npm run dev -- --port "$FE_PORT" --host \
    >"$LOG_FILE" 2>&1 < /dev/null &
  echo $! >"$PID_FILE"
fi

if [[ "$WAIT_HTTP" == "1" ]]; then
  if ! work_wait_http "http://127.0.0.1:${FE_PORT}/" 30 2; then
    echo "⚠ 等待前端 HTTP 超时，进程可能仍在编译，请查看: $LOG_FILE"
  else
    echo "✓ 前端已就绪"
  fi
else
  sleep 2
  echo "✓ 前端进程已启动"
fi

echo "  UI:  http://127.0.0.1:${FE_PORT}"
echo "  日志: $LOG_FILE"
echo "  停止: bash scripts/work/frontend-stop.sh"
