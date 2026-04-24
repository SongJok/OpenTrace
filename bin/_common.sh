#!/bin/bash
# =============================================================================
# _common.sh — Shared helpers for bin/ scripts
# Source this file; do not execute directly.
# =============================================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_info()  { echo -e "${CYAN}  ▸ $*${NC}"; }
_ok()    { echo -e "${GREEN}  ✓ $*${NC}"; }
_warn()  { echo -e "${YELLOW}  ⚠ $*${NC}"; }
_error() { echo -e "${RED}  ✗ $*${NC}"; }

_banner() {
  echo ""
  echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}${GREEN}  $*${NC}"
  echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
  echo ""
}

_banner_done() {
  local bp=$1 fp=$2
  echo ""
  echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  OpenTrace is running!${NC}"
  echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
  echo -e "  ${BOLD}Frontend${NC}  →  ${YELLOW}http://localhost:$fp${NC}"
  echo -e "  ${BOLD}Backend ${NC}  →  ${YELLOW}http://localhost:$bp${NC}"
  echo -e "  ${BOLD}API Docs${NC}  →  ${YELLOW}http://localhost:$bp/docs${NC}"
  echo ""
  echo -e "  ${BOLD}Login${NC}  songts@tuwan.com  /  123456"
  echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
  echo ""
  echo -e "  Logs:  ${CYAN}tail -f /tmp/opentrace-backend.log${NC}"
  echo -e "         ${CYAN}tail -f /tmp/opentrace-frontend.log${NC}"
  echo ""
  echo -e "  Stop:  ${YELLOW}bash bin/stop.sh${NC}"
  echo ""
}

_find_python() {
  for p in /opt/anaconda3/bin/python python3 python; do
    if command -v "$p" >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  _error "Python not found"
  exit 1
}

_kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    _info "Killed process(es) on port $port"
  fi
}

_stop_pid() {
  local pidfile=$1 label=$2
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      _ok "Stopped $label (pid $pid)"
    fi
    rm -f "$pidfile"
  else
    _warn "$label PID file not found ($pidfile)"
  fi
}

_wait_for_url() {
  local url=$1 retries=$2 label=$3
  echo -n "  Waiting for $label"
  for i in $(seq 1 "$retries"); do
    sleep 1
    if curl -sf "$url" >/dev/null 2>&1; then
      echo -e " ${GREEN}ready!${NC}"
      return 0
    fi
    echo -n "."
  done
  echo ""
  _warn "$label did not respond after ${retries}s — check /tmp/opentrace-backend.log"
}
