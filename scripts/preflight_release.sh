#!/bin/bash
# =============================================================================
# OpenTrace — 发布前预检查
# 用法:
#   bash scripts/preflight_release.sh            # 默认 full
#   bash scripts/preflight_release.sh --quick    # 仅健康检查 + 最小合同测试
#   bash scripts/preflight_release.sh --full     # 全量验证 + 健康检查 + 合同测试
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
MODE="${1:---full}"
RESULTS_DIR="${ENTERPRISE_EVAL_RESULTS_DIR:-}"
CAPACITY_REPORT="${ENTERPRISE_CAPACITY_REPORT:-}"
RELEASE_SUBJECT=""

check_cmd() {
  local c="$1"
  if ! command -v "$c" >/dev/null 2>&1; then
    echo "✗ 缺少命令: $c"
    exit 1
  fi
}

usage() {
  cat <<'EOF'
OpenTrace preflight release

Usage:
  bash scripts/preflight_release.sh [--quick|--full]

Options:
  --quick   执行合同结构校验、健康检查和 stage9 最小合同测试
  --full    另执行 verify_all、真实主链 Golden Results 和 stage6~stage9（默认）
EOF
}

echo "== OpenTrace preflight release =="

case "$MODE" in
  --quick|--full)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "✗ 未知参数: $MODE"
    usage
    exit 1
    ;;
esac

check_cmd python
check_cmd curl

echo "▸ 检查 .env"
if [ ! -f .env ]; then
  echo "✗ 缺少 .env"
  exit 1
fi

echo "▸ 检查关键端口(14100/14108)"
if ! lsof -i :14100 >/dev/null 2>&1; then
  echo "⚠ 14100 未监听（后端可能未启动）"
fi
if ! lsof -i :14108 >/dev/null 2>&1; then
  echo "⚠ 14108 未监听（前端可能未启动）"
fi

if [ "$MODE" = "--full" ]; then
  if [ -z "$CAPACITY_REPORT" ]; then
    echo "✗ full 发布检查需要 ENTERPRISE_CAPACITY_REPORT（真实端到端容量证据）。"
    exit 2
  fi
  if [ -n "$(git status --porcelain)" ]; then
    echo "✗ full 发布检查拒绝未提交工作区；容量证据必须绑定确定的候选提交。"
    exit 2
  fi
  RELEASE_SUBJECT="$(git rev-parse HEAD)"
  echo "▸ 运行全量验证"
  bash scripts/verify_all.sh
fi

echo "▸ 企业边界与 Golden Dataset"
python scripts/check_enterprise_boundaries.py
if [ "$MODE" = "--full" ]; then
  if [ -z "$RESULTS_DIR" ]; then
    echo "✗ full 发布检查需要 ENTERPRISE_EVAL_RESULTS_DIR（真实 Responses v2 结果）。"
    exit 2
  fi
  python scripts/load_responses.py \
    --verify-report "$CAPACITY_REPORT" \
    --release-subject "$RELEASE_SUBJECT"
  python scripts/run_enterprise_evals.py \
    --require-results \
    --results-dir "$RESULTS_DIR" \
    --minimum-pass-rate 1.0
else
  python scripts/run_enterprise_evals.py --validate-contracts
fi

echo "▸ API 健康检查"
if ! curl -sf "$BASE_URL/api/v1/health" >/dev/null; then
  echo "✗ 健康检查失败：$BASE_URL/api/v1/health"
  exit 1
fi

if ! curl -sf "$BASE_URL/api/v1/health/runtime" >/dev/null; then
  echo "✗ 运行时认知健康检查失败：$BASE_URL/api/v1/health/runtime"
  exit 1
fi

if [ "$MODE" = "--quick" ]; then
  echo "▸ 最小合同测试(stage9)"
  python -m pytest -q tests/test_stage9_release_checklist_contract.py
else
  echo "▸ 关键认知链合同测试(stage6~stage9)"
  python -m pytest -q \
    tests/test_stage9_release_checklist_contract.py \
    tests/test_stage8_publish_ready_contract.py \
    tests/test_stage7_stream_fallback_sync_contract.py \
    tests/test_stage6_sync_annotations_contract.py
fi

echo "✅ preflight release 通过 ($MODE)"
