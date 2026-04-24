#!/bin/bash
# =============================================================================
# _lib.sh — scripts/ 共享函数库
# 由 start.sh / stop.sh / restart.sh source 引入，不直接执行
# =============================================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_info()  { echo -e "  ${CYAN}▸ $*${NC}"; }
_ok()    { echo -e "  ${GREEN}✓ $*${NC}"; }
_warn()  { echo -e "  ${YELLOW}⚠ $*${NC}"; }
_error() { echo -e "  ${RED}✗ $*${NC}" >&2; }

_banner() {
  echo ""
  echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
  echo -e "${BOLD}${GREEN}  $*${NC}"
  echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
  echo ""
}

_banner_ok() {
  local bp=$1 fp=$2
  echo ""
  echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  OpenTrace 已启动！${NC}"
  echo -e "${GREEN}════════════════════════════════════════════${NC}"
  echo -e "  ${BOLD}前端界面${NC}  →  ${YELLOW}http://localhost:$fp${NC}"
  echo -e "  ${BOLD}后端 API${NC}  →  ${YELLOW}http://localhost:$bp${NC}"
  echo -e "  ${BOLD}Swagger  ${NC}  →  ${YELLOW}http://localhost:$bp/docs${NC}"
  echo ""
  echo -e "  ${BOLD}登录账号${NC}  songts@tuwan.com  /  123456"
  echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
  echo ""
  echo -e "  日志:  ${CYAN}tail -f /tmp/opentrace-backend.log${NC}"
  echo -e "         ${CYAN}tail -f /tmp/opentrace-frontend.log${NC}"
  echo -e "  停止:  ${YELLOW}bash scripts/stop.sh${NC}"
  echo ""
}

_find_python() {
  for p in /opt/anaconda3/bin/python python3 python; do
    if command -v "$p" >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  _error "找不到 Python 可执行文件"
  exit 1
}

_kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    _info "已终止端口 $port 上的进程"
  fi
}

_stop_pid() {
  local pidfile=$1 label=$2
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(cat "$pidfile" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      # 强制终止
      kill -9 "$pid" 2>/dev/null || true
      _ok "已停止 $label (pid $pid)"
    else
      _warn "$label 未运行"
    fi
    rm -f "$pidfile"
  else
    _warn "$label PID 文件不存在，尝试按端口终止"
  fi
}

_wait_url() {
  local url=$1 retries=$2 label=$3
  echo -n "  等待 $label 就绪"
  for i in $(seq 1 "$retries"); do
    sleep 1
    if curl -sf "$url" >/dev/null 2>&1; then
      echo -e " ${GREEN}✓ 就绪${NC}"
      return 0
    fi
    echo -n "."
  done
  echo ""
  _warn "$label 在 ${retries}s 内未响应，请检查日志: /tmp/opentrace-backend.log"
}
