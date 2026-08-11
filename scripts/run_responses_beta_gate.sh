#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

MODE="${1:---contract}"
RESULTS_DIR="${ENTERPRISE_EVAL_RESULTS_DIR:-}"

case "$MODE" in
  --contract)
    ;;
  --release)
    if [ -z "$RESULTS_DIR" ]; then
      echo "企业 Beta 发布门禁需要 ENTERPRISE_EVAL_RESULTS_DIR（真实 Responses 主链结果）。"
      exit 2
    fi
    ;;
  *)
    echo "Usage: bash scripts/run_responses_beta_gate.sh [--contract|--release]"
    exit 2
    ;;
esac

echo "== Responses Enterprise Beta gate: $MODE =="
python -m pytest -q --tb=short \
  tests/test_responses_contract.py \
  tests/test_tenant_rls_contract.py \
  tests/test_scheduler_v2.py \
  tests/test_agent_resources_runtime.py \
  tests/test_enterprise_evaluation_contract.py
bash scripts/check_import_boundaries.sh

HEADS="$(python -m alembic heads | wc -l | tr -d ' ')"
if [ "$HEADS" != "1" ]; then
  echo "Alembic 必须保持单 head，当前为 $HEADS。"
  exit 1
fi

if [ "$MODE" = "--release" ]; then
  python scripts/run_enterprise_evals.py \
    --require-results \
    --results-dir "$RESULTS_DIR" \
    --minimum-pass-rate 1.0
else
  python scripts/run_enterprise_evals.py --minimum-pass-rate 1.0 >/dev/null
  echo "合同模式使用 fixture 只验证评测器；不得据此批准 Beta 放量。"
fi

(
  cd frontend
  npm run build
  npm test -- src/pages/__tests__/ChatPage.contract.test.tsx
)

echo "Responses Enterprise Beta gate passed: $MODE"
