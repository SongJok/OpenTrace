#!/bin/bash
# =============================================================================
# OpenTrace — Kernel Agent Loop 回归验证
# 用法: bash scripts/verify_kernel_loop.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"

if [ -f "$SCRIPT_DIR/_lib.sh" ]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/_lib.sh"
  _banner "Kernel Agent Loop 回归验证"
fi

cd "$ROOT_DIR"
"$PYTHON_BIN" -m unittest tests.test_kernel_agent_loop -v

echo "✅ verify_kernel_loop 完成"
