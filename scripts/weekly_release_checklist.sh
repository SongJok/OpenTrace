#!/usr/bin/env bash
# Weekly / pre-merge checklist for the unified Responses runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT"

echo "== OpenTrace weekly release checklist =="

echo "[1/8] vNext final contracts"
bash scripts/run_vnext_final_tests.sh

echo "[2/8] Enterprise contracts"
bash scripts/run_enterprise_contract_tests.sh

echo "[3/8] Architecture requirements alignment"
python -m pytest -q tests/test_architecture_requirements_alignment.py --tb=no

echo "[4/8] Import boundaries (shell)"
bash scripts/check_import_boundaries.sh

echo "[5/8] Import linter (importlinter)"
lint-imports --config importlinter.ini

echo "[6/8] Gateway + kernel silent-failure guards"
bash scripts/check_gateway_silent_failures.sh
bash scripts/check_kernel_silent_failures.sh

echo "[7/8] Env example ↔ flag registry"
PYTHONPATH=. python scripts/sync_env_example_to_docs.py

echo "[8/8] Config truth contracts"
python -m pytest -q tests/test_config_truth_contract.py --tb=no

echo "=== Weekly checklist OK ==="
