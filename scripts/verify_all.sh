#!/bin/bash
# =============================================================================
# OpenTrace — 总体验证脚本
# 用法: bash scripts/verify_all.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"

bash "$SCRIPT_DIR/verify_error_envelope.sh"
bash "$SCRIPT_DIR/verify_e2e.sh"
"$PYTHON_BIN" "$SCRIPT_DIR/verify_business_flows_e2e.py"
bash "$SCRIPT_DIR/verify_memory_e2e.sh"
bash "$SCRIPT_DIR/verify_kernel_loop.sh"
bash "$SCRIPT_DIR/verify_code_plugin.sh"
bash "$SCRIPT_DIR/verify_agent_bus_e2e.sh"
"$PYTHON_BIN" -m unittest \
  tests/test_memory_api_contract.py \
  tests/test_memory_evolve.py \
  tests/test_tasks_api_contract.py \
  tests/test_zero_trust_contract.py \
  tests/test_skills_runtime.py \
  tests/test_sandbox_runtime.py \
  tests/test_ui_settings_contract.py \
  tests/test_time_weather_tools_behavior.py \
  tests/test_frontend_tool_cards_contract.py \
  tests/test_fusion_critic_flags_contract.py \
  tests/test_rag_agent_contract.py \
  tests/test_alembic_idempotent_contract.py \
  tests/test_responses_contract.py \
  tests/test_scheduler_v2.py \
  tests/test_agent_bus_governance_contract.py

echo "✅ verify_all 完成"
