#!/bin/bash
# =============================================================================
# OpenTrace — 纯 Docker 全量验证脚本
# 用法: bash scripts/verify_all_docker.sh
# 说明: 所有 unittest 在 api 容器内执行，避免本机 Python 环境差异
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "✗ docker 未安装或不可用"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "✗ docker daemon 未启动"
  exit 1
fi

if ! docker compose ps api >/dev/null 2>&1; then
  echo "✗ api 容器未运行，请先执行: bash start.sh"
  exit 1
fi

echo "== OpenTrace verify_all (docker mode) =="

bash scripts/verify_error_envelope.sh
bash scripts/verify_e2e.sh
bash scripts/verify_kernel_loop.sh
bash scripts/verify_code_plugin.sh
bash scripts/verify_agent_bus_e2e.sh
bash scripts/verify_migration_idempotent.sh

echo "▸ 在 api 容器内执行 unittest..."
docker compose exec -T api python -m unittest \
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
  tests/test_orchestrator_v3_contract.py \
  tests/test_fusion_critic_flags_contract.py \
  tests/test_orchestrator_v4_contract.py \
  tests/test_rag_agent_contract.py \
  tests/test_alembic_idempotent_contract.py \
  tests/test_rag_fusion_output_contract.py \
  tests/test_time_weather_tools_behavior.py \
  tests/test_all_agent_bus_routing_contract.py \
  tests/test_agent_bus_governance_contract.py

echo "✅ verify_all_docker 完成"
