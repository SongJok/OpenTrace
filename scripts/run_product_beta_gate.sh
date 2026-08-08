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
      echo "产品 Beta 放量门禁需要 ENTERPRISE_EVAL_RESULTS_DIR（真实 Responses 主链结果）。"
      exit 2
    fi
    ;;
  *)
    echo "Usage: bash scripts/run_product_beta_gate.sh [--contract|--release]"
    exit 2
    ;;
esac

echo "== OpenTrace controlled Beta gate: $MODE =="
python scripts/check_public_release.py
python scripts/check_architecture_manifest.py
python scripts/check_migration_policy.py
python scripts/check_enterprise_boundaries.py
python -m pytest -q
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
  echo "合同模式使用 fixture 验证评测器；真实租户放量仍必须执行 --release。"
fi

(
  cd frontend
  npm test
  npm run build
)

echo "OpenTrace controlled Beta gate passed: $MODE"
