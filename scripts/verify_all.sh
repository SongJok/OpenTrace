#!/bin/bash
# =============================================================================
# OpenTrace — 总体验证脚本
# 用法: bash scripts/verify_all.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

bash "$SCRIPT_DIR/verify_error_envelope.sh"
bash "$SCRIPT_DIR/verify_e2e.sh"
bash "$SCRIPT_DIR/verify_kernel_loop.sh"
bash "$SCRIPT_DIR/verify_code_plugin.sh"
bash "$SCRIPT_DIR/verify_agent_bus_e2e.sh"
python -m unittest \
  tests/test_memory_api_contract.py \
  tests/test_memory_evolve.py \
  tests/test_tasks_api_contract.py \
  tests/test_audit_replay_contract.py \
  tests/test_zero_trust_contract.py \
  tests/test_connectors_sdk.py \
  tests/test_skills_runtime.py \
  tests/test_skill_session_binding.py \
  tests/test_sandbox_runtime.py \
  tests/test_ui_settings_contract.py \
  tests/test_weather_city_routing_contract.py \
  tests/test_time_weather_tools_behavior.py \
  tests/test_frontend_tool_cards_contract.py \
  tests/test_orchestrator_v3_contract.py \
  tests/test_fusion_critic_flags_contract.py \
  tests/test_orchestrator_v4_contract.py \
  tests/test_rag_agent_contract.py \
  tests/test_alembic_idempotent_contract.py \
  tests/test_rag_fusion_output_contract.py \
  tests/test_all_agent_bus_routing_contract.py \
  tests/test_agent_bus_governance_contract.py

echo "✅ verify_all 完成"
