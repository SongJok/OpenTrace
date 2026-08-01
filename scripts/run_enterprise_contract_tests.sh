#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
python -m pytest \
  tests/test_enterprise_control_plane_contract.py \
  tests/test_multi_tenant_runtime_contract.py \
  tests/test_goal_portfolio_contract.py \
  tests/test_enterprise_observability_contract.py \
  tests/test_world_model_runtime_contract.py \
  tests/test_capability_os_contract.py \
  tests/test_cognitive_agent_contract.py \
  tests/test_control_plane_gate_contract.py \
  tests/test_capability_dispatch_os_contract.py \
  tests/test_data_intelligence_turn_outcomes_contract.py \
  tests/test_pii_and_memory_compression_contract.py \
  tests/test_preflight_contract.py \
  tests/test_evidence_graph_contract.py \
  tests/test_rag_evidence_intelligence_contract.py \
  tests/test_web_intelligence_agent_contract.py \
  tests/test_world_state_redis_contract.py \
  tests/test_tenant_policy_contract.py \
  tests/test_compliance_audit_contract.py \
  tests/test_tms_bridge_contract.py \
  tests/test_enterprise_admin_api_contract.py \
  tests/test_capability_execution_routing_contract.py \
  tests/test_chat_preflight_contract.py \
  tests/test_chat_kernel_entry_contract.py \
  tests/test_resume_turn_contract.py \
  tests/test_tier0_paths_contract.py \
  tests/test_chat_session_tenant_contract.py \
  tests/test_capability_dispatch_deep_contract.py \
  tests/test_data_agent_data_intelligence_contract.py \
  tests/test_data_agent_v2_extended_contract.py \
  tests/test_world_model_cross_process_contract.py \
  tests/test_data_agent_v2_clarification_contract.py \
  tests/test_turn_metering_contract.py \
  tests/test_finalize_turn_contract.py \
  tests/test_stream_enterprise_metadata_contract.py \
  tests/test_enterprise_evaluation_contract.py \
  tests/test_enterprise_slo_contract.py \
  tests/test_enterprise_deployment_contract.py \
  tests/test_enterprise_resilience_contract.py \
  tests/test_enterprise_governance_contract.py \
  tests/test_enterprise_object_storage_contract.py \
  tests/test_enterprise_identity_contract.py \
  tests/test_enterprise_interoperability_contract.py \
  tests/test_enterprise_protocol_server_contract.py \
  tests/test_enterprise_refactoring_contract.py \
  tests/test_enterprise_worker_metrics_contract.py \
  tests/test_enterprise_trace_contract.py \
  tests/test_enterprise_work_scenarios_contract.py \
  -q --tb=short "$@"
echo "=== Enterprise contracts OK ==="
