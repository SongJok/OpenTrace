#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
python -m pytest \
  tests/test_responses_contract.py \
  tests/test_kernel_agent_loop.py \
  tests/test_agent_runtime_v3_contract.py \
  tests/test_capability_manifest_routing_contract.py \
  tests/test_enterprise_cognition.py \
  tests/test_enterprise_knowledge_base.py \
  tests/test_enterprise_p0_security.py \
  tests/test_enterprise_evaluation_contract.py \
  tests/test_enterprise_skill_distillation.py \
  tests/test_rag_agent_contract.py \
  tests/test_data_agent_v2_extended_contract.py \
  tests/test_task_notifications.py \
  tests/test_main_path_scripts_contract.py \
  -q --tb=short "$@"
echo "=== Enterprise contracts OK ==="
