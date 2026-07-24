#!/usr/bin/env bash
# <30 分钟完整合同门禁；服务型迁移/故障测试由专用脚本并行执行。
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:---backend}"
PYTHON_BIN="${PYTHON_BIN:-python}"
export PATH="$(dirname "$PYTHON_BIN"):$PATH"

case "$MODE" in
  --backend)
    PYTHON_BIN="$PYTHON_BIN" bash scripts/ci_fast.sh --backend
    "$PYTHON_BIN" -m pytest -q --tb=short
    bash scripts/run_vnext_final_tests.sh
    bash scripts/run_enterprise_contract_tests.sh
    lint-imports --config importlinter.ini
    ;;
  --frontend)
    bash scripts/ci_fast.sh --frontend
    ;;
  *) echo "usage: $0 [--backend|--frontend]" >&2; exit 2 ;;
esac
