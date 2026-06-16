# Cognitive OS vNext — 需求与实现对照矩阵

> 与 `tests/test_architecture_requirements_alignment.py` 及 `scripts/run_vnext_final_tests.sh` 联动回归。

| # | 原需求 | 实现状态 | 关键模块 | 契约测试 | 运营成熟度 |
|---|--------|----------|----------|----------|------------|
| 1 | Runtime 去中心化 | ✅ | `runtime_gateway.py` 瘦路由；enrichment 在 `dispatch_enrichment`（Supervisor） | `TestRuntimeGatewaySlimContract` | 实现 ✅ / Runbook ✅ / CI 边界 ✅ |
| 2 | Cognitive Supervisor | ✅ | `kernel/cognitive_supervisor/` + `dispatch_enrichment` | `test_cognitive_supervisor_contract` | 实现 ✅ / Runbook ✅ |
| 3 | GoalGraph 一等公民 | ✅ | `plan_from_goal_context`；`kernel_goal_driven_dag_enabled` 默认 ON | `TestGoalDrivenPlanning` | 实现 ✅ / 观测 部分 |
| 4 | State-based Runtime | ✅ | `cognitive_state/store` + `state_transition`；phase strict 默认 ON | phase strict tests | staging persist ✅ / 多副本 ⚠️ |
| 5 | Planner 四层 | ✅ | Goal → Strategic → Execution → Projection | `TestStrategicPlannerContext` | 实现 ✅ |
| 6 | Capability OS | ✅ | registry/contract strict + guardrails + capability_runtime | `TestRegistryDispatchGovernance` | 实现 ✅ / dispatch pipeline ✅ |
| 7 | Memory Fabric | ✅ | fabric retrieval + redis graph shadow + evidence bind | `TestMemoryFabricRetrieval` | primary_only ✅ / 集群 graph ⚠️ |
| 8 | Governance 前置 | ✅ | plan/evidence/memory + `kernel_evidence_contract_strict` | Executive `_apply_phase_governance` | Runbook ✅ / ADR-002 ✅ |
| 9 | Context Fabric 动态 | ✅ | `evolve_runtime` per phase + `fabric_graph_live` | phase2 fabric | 实现 ✅ |
| 10 | World Model | ✅ | `runtime_grounding` 七切片（user/env/cap/risk/temporal/memory/exec） | vnext full stack | 单进程 ✅ / 跨进程 ⚠️ |
| 11 | Multi-Goal | ✅ | scheduler + multi_execution_planner + outcomes | multi_goal + multi_question | 实现 ✅ |
| 12 | 强 Runtime Contract | ✅ | phase/evidence/capability/replay；strict 默认 ON | replay + strict | replay doc ✅ |
| 13 | Semantic OS Metrics | ✅ | `semantic_metrics_pipeline` + alerts | phase2 pipeline | `OBSERVABILITY_COGNITIVE_HEALTH.md` ✅ |
| 14 | V4 隔离 | ✅ | `legacy/v4`, thin re-export | `TestV4Isolation` | `report_v4_imports.sh` ✅ |
| 15 | DataAgent V2 融入 | ✅ | `services/data_intelligence_runtime` | registry + alignment | `CAPABILITY_MATURITY.md` ✅ |
| 16 | Architecture Governance | ✅ | 本矩阵 + `run_vnext_final_tests.sh` | alignment + phase2–6 contract tests | `RELEASE_GATE.md` + import-linter 可选 |
| 17 | Agent Runtime V3（Tier-1 融入） | ✅ | manifest + `AgentRuntimeExecutor` + `evidence_helpers` + bus_eligible | `TestAgentRuntimeV3Alignment` + `test_agent_runtime_v3_*` | staging/production strict ✅ |
| 18 | Goal Intelligence (GoalSupervisor) | ✅ | `kernel/goal/goal_supervisor.py` + `prepare_dispatch` | `test_p0_cognitive_platform_contract` | 实现 ✅ |
| 19 | Business Semantic (Data V3 core) | ✅ | `business_semantic_agent` + DAG + manifest `data_business_semantic` | P0 contract + `test_data_agent_v2_dag_manifest_contract` | 实现 ✅ |
| 20 | Cognitive Iteration (Executive) | ✅ | `kernel/runtime/cognitive_iteration.py` + Executive 9.7 | `test_p0_cognitive_platform_contract` | 实现 ✅ |
| 21 | Strategy Memory → Planner | ✅ | `strategy_pattern.py` + Supervisor `strategy_patterns` | P0 contract | 实现 ✅ |
| 22 | Claim Graph / Fusion 元数据 | ✅ | `claim_graph.py` + `rag_evidence_intelligence` | `test_p1_decision_intelligence_contract` | 实现 ✅ |
| 23 | RAG Cluster + Conflict | ✅ | `rag_retrieval_clusters` + `detect_contradictions` | evidence + P1 contract | 实现 ✅ |
| 24 | Web Coverage Evaluator | ✅ | `coverage_evaluator` + 补搜循环 | P1 + web contract | 实现 ✅ |
| 25 | Capability Score 排序 | ✅ | `capability_score.py` + `selector` | P1 contract | 实现 ✅ |
| 26 | Predictive World 切片 | ✅ | `predictive_world.py` + `world_decision_runtime` | P1 contract | 启发式 ✅ / 模型 ⏳ |
| 27 | World Simulation 入门 | 🟡 | `world_decision_runtime` counterfactual | world contract | counterfactual ✅ / 全仿真 ⏳ |
| 28 | Capability Evolution 回合尾 | ✅ | Executive 9.5 + `evolution_hook` + `finalize_semantic_and_evolution` | `test_p2_completion_contract` | 去重 executive/finalize ✅ |
| 29 | Kernel finalize 语义闭环 | ✅ | `record_kernel_turn_health` + `post_turn_enterprise_accounting` | P2 contract | 非 executive 路径 ✅ |
| 30 | Cross-process World 发布 | 🟡 | `world_turn_finalize` + `CrossProcessWorldFacade` | P2 wiring | flag 默认 off / redis staging ⏳ |
| 31 | Capability Evolution 回合尾 | ✅ | `evolution_hook` + `finalize_semantic_and_evolution` | `test_p2_completion_contract` | 每 N 轮 analyze ✅ |
| 32 | Kernel 回合语义健康 | ✅ | `record_kernel_turn_health` + finalize | P2 contract | executive + kernel 双路径 ✅ |
| 33 | 跨进程 World 发布 | 🟡 | `world_turn_finalize` + `CrossProcessWorldFacade` | P2 contract | flag ON + redis ⏳ |
| 28 | Self-Optimizing Runtime | ✅ | `self_optimizing_runtime.py` + `semantic_helpers` | `test_p2_completion_contract` | hints ✅ / apply 默认 OFF |
| 29 | Semantic Health P0/P1 信号 | ✅ | `compute_cognitive_health` extra + `record_executive_turn_health` | P2 contract | stream `semantic_observability` ✅ |
| 30 | Autonomous Goal Proposals | ✅ | `autonomous_goal_discovery` + dispatch | P2 contract | 元数据 ✅ / 自动执行 ⏳ |

**主路径（必须遵守）**

```
CognitiveKernel → RuntimeGateway
  → CognitiveSupervisor.prepare_run (Goal, governance, strategy, fabric seed, dispatch_enrichment)
  → RuntimeTurnDispatcher (lookup, lifecycle, dispatch only)
  → runtime.registry → cognitive_executive | data_intelligence | multi_goal
  → run_outcomes (Artifact, GoalEvidenceBinding, governance, semantic health)
```

**vNext 默认开关（`AppSettings`）**

| 开关 | 默认 |
|------|------|
| `kernel_goal_driven_dag_enabled` | true |
| `kernel_runtime_phase_transition_strict` | true |
| `kernel_registry_dispatch_strict` | true |
| `kernel_capability_contract_strict` | true |
| `kernel_evidence_contract_strict` | true |
| `kernel_memory_fabric_retrieval_enabled` | true |
| `kernel_memory_graph_redis_enabled` | true |
| `kernel_memory_fabric_primary_only` | **true**（全环境；legacy router 仅在显式 `false` 时合并） |
| `kernel_cognitive_state_persist_enabled` | false（**staging/production 强制 true**） |
| `kernel_goal_supervisor_enabled` | true |
| `data_agent_business_semantic_enabled` | true |
| `kernel_cognitive_iteration_enabled` | true |
| `kernel_strategy_memory_planner_enabled` | true |
| `kernel_agent_runtime_v3_enabled` | true |
| `kernel_agent_runtime_v3_strict` | false（**staging/production 强制 true**） |
| `kernel_unified_evidence_strict` | false（**staging/production 强制 true**） |

**Staging / Production 自动强化（`app_env` ∈ {staging, production}）**

| 开关 | 行为 |
|------|------|
| `kernel_memory_fabric_primary_only` | 强制 true |
| `kernel_cognitive_state_persist_enabled` | 强制 true |
| `kernel_world_state_persist_enabled` | 强制 true |
| `kernel_policy_mutation_fail_closed` | 强制 true |
| `kernel_agent_runtime_v3_strict` | 强制 true |
| `kernel_unified_evidence_strict` | 强制 true |
| `kernel_runtime_phase_transition_strict` | staging：若 `kernel_staging_phase_transition_strict` 则强制 strict |

**剩余架构债（可选演进）**

- 跨进程/集群级 World Model（非单进程 grounding store）
- 生产代码应使用 `legacy.v4`；`kernel/orchestrator_v4.py` 仅 re-export。跟踪：`bash scripts/report_v4_imports.sh`
- V4 源码物理删除（`legacy/` 隔离已满足契约）

**企业控制面（阶段 7）**

| 能力 | 模块 | 开关 |
|------|------|------|
| 配额 Redis | `tenant/quota_redis_store.py` | `enterprise_quota_redis_enabled` |
| 用量 Redis | `tenant/usage_redis_store.py` | `enterprise_usage_redis_enabled` |
| 异步预检 | `chat_preflight` + `control_plane_gate` | 同上 |
| Turn 计费收尾 | `kernel/runtime/finalize_turn.py` | — |

**近期深化（实现）**

- `kernel/runtime/cognitive_state/bus.py` — 认知态统一写路径（与 Executive / dispatch_enrichment 同步）
- `kernel/goal/multi_goal_resources.py` — 多目标资源槽与并行/串行决策
- `RuntimeGateway.stream` 不再写入 `goal_graph`（由 Dispatcher 负责）
- `EvolutionMemoryRouter.store` 写入 Fabric 关系绑定
- `data_intelligence_runtime` 接入 `GoalRuntimeHooks`
- `dispatch_enrichment` + `GovernanceCenter.evaluate_turn`：`AdaptiveRiskEngine` 与 risk/semantic_observability 闭环
- `governance_kwargs_from_ctx` 传递 `adaptive_risk_*` 至回合治理
- **RuntimeContribution 全链**：`evidence_runtime` → `dispatch_pipeline.attach_goal_participation` → `CognitiveStateGraph`（ctx）
- **Goal progress**：`goal_progress.sync_goal_lifecycle_from_metadata` + Executive turn 末 `persist_goal_progress`