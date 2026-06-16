# Kernel / Cognitive OS feature flags (`kernel_*`)

Production orchestration path (always when V4 is off):

`CognitiveKernel` → `CognitiveSupervisor` → `RuntimeGateway` → `CognitiveExecutive` | `data_intelligence_runtime` | `multi_question_runtime`

## Must-not-change in production

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_orchestrator_v4_enabled` | **False** | Legacy V4 orchestrator; `RuntimeError` if instantiated |

## Runtime V2 (main path)

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_cognitive_planner_v2_enabled` | True | ExecutionPlanner P2 (required for Executive) |
| `kernel_runtime_rewrite_enabled` | True | Query rewrite phase |
| `kernel_runtime_understanding_enabled` | True | Understanding phase |
| `kernel_runtime_capability_graph_enabled` | True | Capability graph for execution |
| `kernel_agent_capability_executor_mode` | True | Capability executor vs legacy agent bus |
| `kernel_runtime_evidence_fusion_critic_enabled` | True | Evidence + fusion + critic pipeline |
| `kernel_runtime_artifact_composer_enabled` | True | Artifact composition |
| `kernel_runtime_workspace_enabled` | True | Session workspace artifacts |
| `kernel_runtime_replay_enabled` | True | Deterministic trace / snapshots |

## Routing & fast paths (V5)

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_v5_routing_enabled` | True | L0/L1/semantic cache tier |
| `kernel_l0_rule_router_enabled` | True | Rule router (identity, slash → gateway) |
| `kernel_l1_tiny_router_enabled` | True | Tiny router for simple queries |
| `kernel_semantic_cache_enabled` | True | Semantic answer cache |

## Multi-question & data

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_multi_question_runtime_v2_enabled` | True | GoalGraph + P2 multi path |
| `kernel_multi_goal_sequential_enabled` | True | Sub-goals chained with `depends_on` |
| `kernel_data_intelligence_routing_enabled` | True | `data_query` → `services.data_intelligence_runtime` |

## Governance & refine

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_governance_evidence_gate_enabled` | True | Evidence governor in Executive |
| `kernel_governance_risk_gate_enabled` | True | Risk governor in Executive |
| `kernel_refine_replan_enabled` | True | RefinementPlanner after agent failures |
| `kernel_refine_reexec_enabled` | True | Re-run ExecutionRuntime after replan |

## Memory & context

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_memory_context_enabled` | True | Episodic + semantic injection in Kernel |
| `kernel_context_composer_enabled` | True | Context Fabric assemble in Kernel |
| `kernel_context_compressor_enabled` | True | Compress context in Executive |

## Capability intelligence

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_capability_intelligence_enabled` | True | Feedback loop + profiles |
| `kernel_capability_intelligence_phase2_enabled` | True | Execution/strategy memory + evolution |

## Agents / bus

| Flag | Default | Meaning |
|------|---------|---------|
| `kernel_agent_enabled` | True | Agent worker path |
| `kernel_agent_bus_enabled` | True | Redis agent bus |
| `kernel_agent_timeout_sec` | 30 | Per-task timeout |
| `kernel_agent_max_parallel` | 5 | Parallel capability nodes |

## Legacy V4 import paths

- Prefer: `from legacy.v4 import CognitiveOrchestratorV4` (tests only)
- Shim: `kernel.orchestrator_v4_shim`, thin re-export: `kernel.orchestrator_v4`
- Implementation file: `legacy/v4/orchestrator.py`