#!/usr/bin/env bash
# Final vNext contract suite (no full integration / no live LLM required for most tests).
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

echo "=== vNext final test suite ==="
python -m pytest \
  tests/test_vnext_architecture_contract.py \
  tests/test_vnext_full_stack_contract.py \
  tests/test_architecture_requirements_alignment.py \
  tests/test_architecture_governance_phase2.py \
  tests/test_vnext_requirements_matrix.py \
  tests/test_cognitive_supervisor_contract.py \
  tests/test_multi_goal_runtime_contract.py \
  tests/test_cognitive_runtime_contract.py \
  tests/test_multi_question_runtime_contract.py \
  tests/test_force_mode_multi_turn_contract.py \
  tests/test_turn_enrichment_contract.py \
  tests/test_multi_turn_resolution_contract.py \
  tests/test_multi_turn_scenarios_fixture.py \
  tests/test_documents_rag_retrieval_contract.py \
  tests/test_execution_projection_enrichment_runtime.py \
  tests/test_clarification_enrichment_contract.py \
  tests/test_turn_bootstrap_contract.py \
  tests/test_p2_p3_completion_contract.py \
  tests/test_cognitive_controls_contract.py \
  tests/test_clarification_gate.py \
  tests/test_runtime_cognitive_executive.py \
  tests/test_runtime_phase_strict_integration.py \
  tests/test_kernel_import_boundaries.py \
  tests/test_config_truth_contract.py \
  tests/test_orchestrator_label_contract.py \
  tests/test_goal_driven_dag_contract.py \
  tests/test_memory_graph_redis_contract.py \
  tests/test_capability_dispatch_pipeline.py \
  tests/test_semantic_metrics_alerts_contract.py \
  tests/test_governance_single_source_contract.py \
  tests/test_data_agent_v2_dag_builder_contract.py \
  tests/test_agent_runtime_v3_contract.py \
  tests/test_agent_runtime_v3_strict_contract.py \
  tests/test_agent_bus_eligibility_contract.py \
  tests/test_all_agent_bus_routing_contract.py \
  tests/test_agents_import_boundaries.py \
  tests/test_data_intelligence_runtime_v3_contract.py \
  tests/test_p0_cognitive_platform_contract.py \
  tests/test_p1_decision_intelligence_contract.py \
  tests/test_p2_completion_contract.py \
  tests/test_rag_evidence_intelligence_contract.py \
  tests/test_evidence_graph_contract.py \
  -q --tb=short "$@"

echo "=== OK ==="
