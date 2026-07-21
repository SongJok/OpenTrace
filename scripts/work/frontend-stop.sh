#!/usr/bin/env bash
# =============================================================================
# OpenTrace — 前端开发服务关闭（Vite，默认 14108）
#
# 用法:
#   bash scripts/work/frontend-stop.sh
#   bash scripts/work/frontend-stop.sh --port=14108
#   bash scripts/work/frontend-stop.sh 14108
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ROOT="$(work_project_dir)"
work_load_dotenv "$ROOT"
FE_PORT="$(work_default_frontend_port)"
FORCE_PORT=0

for arg in "$@"; do
  case "$arg" in
    --port=*)
      FE_PORT="${arg#*=}"
      FORCE_PORT=1
      ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      if [[ "$arg" =~ ^[0-9]+$ ]]; then
        FE_PORT="$arg"
        FORCE_PORT=1
      else
        echo "未知参数: $arg"
        exit 1
      fi
      ;;
  esac
done

RT="$(work_runtime_dir)"
PID_FILE="$RT/frontend_dev.pid"
SCREEN_NAME="opentrace-vite-${FE_PORT}"

screen_sessions=""
if command -v screen >/dev/null 2>&1; then
  screen_sessions="$(screen -ls 2>&1 || true)"
fi
if [[ "$screen_sessions" == *"${SCREEN_NAME}"* ]]; then
  echo "▸ 停止前端开发会话 (${SCREEN_NAME})"
  screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
fi

if [[ "$FORCE_PORT" != "1" ]]; then
  work_stop_pidfile "$PID_FILE" "前端开发服务"
fi

stopped_by_port=0
if work_port_listening "$FE_PORT" && command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [[ -n "${pid:-}" ]] || continue
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$cmd" == *"$ROOT/frontend"* && "$cmd" == *"vite"* ]]; then
      echo "▸ 停止前端开发服务 (pid=${pid}, port=${FE_PORT})"
      kill "$pid" >/dev/null 2>&1 || true
      sleep 1
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
      stopped_by_port=1
    fi
  done < <(lsof -tiTCP:"$FE_PORT" -sTCP:LISTEN 2>/dev/null || true)
fi

rm -f "$PID_FILE"

if work_port_listening "$FE_PORT"; then
  if [[ "$stopped_by_port" == "1" ]]; then
    echo "⚠ 前端端口 ${FE_PORT} 仍被占用，请检查残留进程"
  else
    echo "⚠ 前端端口 ${FE_PORT} 被非本项目进程占用，未自动停止"
  fi
else
  echo "✓ 前端已停止"
fi
