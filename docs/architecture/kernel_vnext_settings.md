# Cognitive OS vNext — Kernel Feature Flags

All flags live in `infra/config/settings.py` (env prefix varies by pydantic nesting; most are top-level on `Settings`).

## Production path (must stay on)

| Flag | Default | Role |
|------|---------|------|
| `kernel_orchestrator_v4_enabled` | **False** | V4 orchestrator; must remain off in prod |
| `kernel_cognitive_planner_v2_enabled` | True | ExecutionPlanner V2 (required for main path) |
| `kernel_multi_question_runtime_v2_enabled` | True | Multi-question via GoalGraph + P2 |
| `kernel_multi_goal_sequential_enabled` | True | Sub-goal `depends_on` chain across sub-questions |
| `kernel_data_intelligence_routing_enabled` | True | `data_query` → `services/data_intelligence_runtime` |
| `kernel_governance_evidence_gate_enabled` | True | Evidence governor on turn |
| `kernel_governance_risk_gate_enabled` | True | Risk governor on turn |
| `kernel_refine_replan_enabled` | True | RefinementPlanner after agent failures |
| `kernel_refine_reexec_enabled` | True | Re-run ExecutionRuntime after replan |
| `kernel_context_composer_enabled` | True | ContextFabric / assembler |
| `kernel_memory_context_enabled` | True | Episodic + semantic injection + turn save |

## Runtime / Executive

| Flag | Default | Role |
|------|---------|------|
| `kernel_runtime_rewrite_enabled` | True | Query rewrite phase |
| `kernel_runtime_understanding_enabled` | True | Understanding engine |
| `kernel_runtime_capability_graph_enabled` | True | Capability graph build |
| `kernel_agent_capability_executor_mode` | True | Capability executor vs legacy agents |
| `kernel_runtime_artifact_composer_enabled` | True | Artifact composition |
| `kernel_runtime_workspace_enabled` | True | Session workspace artifacts |
| `kernel_runtime_replay_enabled` | True | Snapshots + goal_replay_snapshot |
| `kernel_context_compressor_enabled` | True | Context compression |
| `kernel_evidence_lifecycle_enabled` | True | Evidence bus lifecycle |

## Routing (Kernel L0–L1)

| Flag | Default | Role |
|------|---------|------|
| `kernel_v5_routing_enabled` | True | Master switch for L0/L1/cache |
| `kernel_l0_rule_router_enabled` | True | Rule router; slash → RuntimeGateway |
| `kernel_l1_tiny_router_enabled` | True | Tiny router for simple queries |
| `kernel_semantic_cache_enabled` | True | Semantic answer cache |

## Capability intelligence

| Flag | Default | Role |
|------|---------|------|
| `kernel_capability_intelligence_enabled` | True | Feedback loop |
| `kernel_capability_intelligence_phase2_enabled` | True | Execution/strategy memory + evolution |
| `kernel_memory_truth_maintenance_enabled` | True | Truth maintenance (memory runtime) |

## DataAgent (in-repo)

| Env / setting | Role |
|---------------|------|
| `data_agent_v2_enabled` | DataAgent → V2 supervisor |
| `data_agent_v2_fallback_to_v1` | Low confidence / errors → V1 |

## Legacy import

- Prefer: `from legacy.v4 import CognitiveOrchestratorV4`
- Avoid: new code importing `kernel.orchestrator_v4` (thin re-export only)

See also: [vnext_alignment.md](vnext_alignment.md)