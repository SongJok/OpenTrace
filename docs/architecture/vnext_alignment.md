# OpenTrace Cognitive OS vNext — 需求对齐审查

> **Compatibility / Experimental（Alpha）**：本文只用于旧 Cognitive Runtime 架构合约，不是当前 `/api/v2/responses` 在线入口说明。


> 对照重构蓝图 Phase 1 与当前代码库（不含 DataAgent 独立产品化）。

## 已实现 ✅

| 蓝图项 | 实现位置 |
|--------|----------|
| Runtime V2 单一路径 | `CognitiveKernel` → `CognitiveSupervisor` → `RuntimeGateway` → runtimes |
| Cognitive Supervisor | `kernel/cognitive_supervisor/` — GoalGraph、治理、多问、策略投影 |
| RuntimeGateway 瘦身 | 仅 dispatch / artifact；不再内嵌 Goal 与 multi_question |
| Strategic Planner | `planner_facade.StrategicPlanner` — budget / runtime 选择 |
| Goal 状态机 | `kernel/goal/state_machine.py` + `goal_lifecycle` |
| Data Intelligence（项目内） | `services/data_intelligence_runtime/` → `DataAgent` V2 |
| Memory Fabric 关系 | `memory/fabric/relation_engine.py` |
| Runtime Policy Engine | `governance/runtime_policy_engine.py` |
| Capability Runtime 元数据 | `kernel/capability_runtime/` |
| 认知状态演化 | `kernel/runtime/cognitive_state/` |
| Goal 世界投影 | `kernel/goal/goal_projection.py` → Supervisor `goal_world_projection` |
| Context 动态图 | `kernel/context_fabric_graph.py` → `FabricContext.metadata.fabric_graph` |
| Capability 治理回退 | `apply_governance_with_fallback` + `failure_memory` |
| Multi-Goal 调度 | `multi_goal_scheduler` + `kernel_multi_goal_sequential_enabled` |
| V4 清理 | V4 实现、shim 与运行时开关均已删除 |
| Runtime Contract | `kernel/protocol/runtime_contract.py` |
| Goal Graph 第一实体 | `GoalPlanner` + `runtime_task_from_request` |
| Protocol Layer | `cognition_protocol`, `runtime_protocol`, `agent_protocol` |
| Governance Center | `kernel/governance/*` + `evaluate_turn` on run/stream/multi |
| Context Fabric | `kernel/context_fabric.py` |
| ExecutionPlanner 门面 | Executive + multi P2（无 `generate_multi_plan`） |
| Multi-question V2 | `multi_question_runtime` + ExecutionRuntime graph |
| force_mode 多轮/多问 | `cognitive_controls` + multi_execution_planner |
| RefinementPlanner 钩子 | Executive post-execute + `kernel_refine_replan_enabled` |
| Strategy / Capability 链 | `kernel/strategy/capability_chain.py` |
| Cognitive World Model | `kernel/cognition/cognitive_world_model.py` |
| Evidence / Memory / CI | runtime + `capability_intelligence` |
| DataAgent V2（项目内） | `agents/data_agent` + settings |

## 部分实现 🟡

| 蓝图项 | 缺口 |
|--------|------|
| 六域物理目录 | `cognition/`、`strategy/` 门面已有；`runtime/` 仍为主实现体 |
| plan_agent 单问 | 主路径已不用 `PlanAgent.generate_plan` |
| Refine 重执行 | 检测+局部 plan 元数据；未自动二次 `ExecutionRuntime` |

## 未做 / 后续 Phase ⏳

- Phase 2–5：分布式 Runtime、Memory Graph、Capability Market
- Evidence / Reasoning / Artifact 三引擎命名完全统一
- Multi-Goal **资源竞争**（优先级 + 顺序依赖已接入；预算竞争未建模）
- Context Fabric **全动态演化**（`context_fabric_graph` 节点图已接入 assemble 元数据）
- Goal `goal_evolution` / `goal_replay` 专用模块（projection + memory_binding 已有）

## 行为说明

- **`/rag` 等 force_mode**：单问 Executive；复合问 multi + capability 过滤。
- **多轮**：sticky domain + force_mode 追问 memory/context 预算。
- **L0 斜杠**：`RuntimeGateway`。
