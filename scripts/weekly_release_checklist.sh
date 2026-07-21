#!/usr/bin/env bash
# Weekly / pre-merge checklist for the unified Responses runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT"

echo "== OpenTrace weekly release checklist =="

echo "[1/9] Public release safety"
python scripts/check_public_release.py

echo "[2/9] vNext final contracts"
bash scripts/run_vnext_final_tests.sh

echo "[3/9] Enterprise contracts"
bash scripts/run_enterprise_contract_tests.sh

echo "[4/9] Architecture requirements alignment"
python -m pytest -q tests/test_architecture_requirements_alignment.py --tb=no

echo "[5/9] Import boundaries (shell)"
bash scripts/check_import_boundaries.sh

echo "[6/9] Import linter (importlinter)"
lint-imports --config importlinter.ini

echo "[7/9] Gateway + kernel silent-failure guards"
bash scripts/check_gateway_silent_failures.sh
bash scripts/check_kernel_silent_failures.sh

echo "[8/9] Env example ↔ flag registry"
PYTHONPATH=. python scripts/sync_env_example_to_docs.py

echo "[9/9] Config truth contracts"
python -m pytest -q tests/test_config_truth_contract.py --tb=no

echo "=== Weekly checklist OK ==="
