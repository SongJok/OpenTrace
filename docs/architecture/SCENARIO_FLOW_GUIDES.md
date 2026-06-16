# OpenTrace 场景过程走向指南

> 基于当前 **vNext 主路径**（`CognitiveKernel` → `CognitiveSupervisor` → `RuntimeGateway` → `RuntimeTurnDispatcher` → Runtime Registry）。  
> 权威约束见 [ADR-001](../adr/001-vnext-main-path.md)、[vnext_alignment.md](./vnext_alignment.md)。  
> **本文仅描述行为走向，不替代契约测试**；发布门禁见 `scripts/run_vnext_final_tests.sh`。

---

## 1. 总览：请求从哪里进、从哪里出

| 入口 | 模块 | 说明 |
|------|------|------|
| `POST /chat` | `gateway/api_gateway/routers/chat.py` | 同步或 SSE；**必须**经 `require_kernel_entrypoint` |
| `POST /chat/resume` | 同上 + `kernel/runtime/resume_turn.py` | 从 `TraceLog` 取历史 query 重跑 |
| 预检 | `gateway/api_gateway/chat_preflight.py` | PII + Control Plane（可异步 Redis 配额） |

| 唯一认知中枢 | `kernel/cognitive_kernel.py` | `run()` / `stream()`；禁止 Gateway 直连 LLM |
| 瘦路由 | `kernel/runtime_gateway.py` | Tier0 尝试、enrichment、委托 Supervisor + Dispatcher |
| 监督层 | `kernel/cognitive_supervisor/supervisor.py` | GoalGraph、治理、策略投影、World 注水 |
| 调度层 | `kernel/runtime/runtime_turn_dispatcher.py` | 解析 runtime 名、执行、artifact / SSE 收尾 |

**默认 Runtime 注册名**（`kernel/runtime/registry.py`）：

- `cognitive_executive` — 通用认知流水线（主路径）
- `data_intelligence` — 数据智能运行时（策略 `preferred_runtime=data_intelligence`）
- `multi_goal` — 多问 / 多子目标（`strategy_projection` 或 Goal 数 > 2）

---

## 2. 所有 Chat 场景共用的 Gateway 前奏

无论最终走哪条支路，进入 `chat()` 后通常按序执行（失败或跳过的步骤见各场景）：

```text
用户请求 ChatRequest
    │
    ├─► safety.guardrails 输入拦截 ──► 拒绝 PARAM_INVALID
    │
    ├─► tenant_middleware.build_tenant_metadata (X-Tenant-Id / Org / Workspace)
    │
    ├─► run_chat_preflight_async
    │       ├─ governance.pii_detector → tenant_md 标记 pii_*
    │       └─ control_plane.preflight_from_metadata_async
    │               └── 拒绝 → AppException policy_denied (JSON)
    │
    ├─► _ensure_session + set_session_tenant_context (RLS)
    │
    ├─► _load_conversation_history (多轮，默认 10 条)
    │       └─ [可选] kernel_conversation_branching_enabled + parent_message_id → 分支历史/检查点
    │
    ├─► assess_query_risk → tool_permission_token / confirmation_granted 门禁
    │
    ├─► data_source_context（force_database / data_source_id / 内部文档意图启发）
    │
    ├─► _load_previous_turn_context（plan + results）
    │
    ├─► 附件加载（attachment_ids 或会话内最近 active 附件，有上限）
    │
    ├─► 组装 KernelRequest + conversation_state / graph_controls / force_mode 等 metadata
    │
    └─► RuntimeGateway.try_tier0_chat（见 §3）── 未 handled 则进入 Kernel
```

**SSE 与同步**：Tier0 命中时 Gateway 直接组 SSE 或 `ChatResponse`；否则 `kernel.stream()` 或 `kernel.run()`。

---

## 3. 场景 A — Gateway Tier0（不经完整 Supervisor）

**触发条件**（`RuntimeGateway.try_tier0_chat` + `kernel/runtime/tier0_paths.py`）：

| 子场景 | 条件 | decision_type | 说明 |
|--------|------|---------------|------|
| A1 SQL 检索 | 用户意图为「取上一轮 SQL」等（`tier0_paths.is_sql_retrieval_intent`） | `sql_retrieval` | 读库/会话上下文返回 SQL 文本 |
| A2 库表直查 | `force_database` + `data_source_id` 且 A1 未命中 | `database_direct` | 调用 Gateway 注入的 `data_query_fn`，绕过完整认知图 |

**过程走向**：

```text
chat() 组装 Tier0ChatContext(db, user, data_query_fn, ...)
    │
    ▼
try_tier0_chat
    ├─► run_sql_retrieval_tier0 → handled? → 写 state_patch → 返回 / SSE stream_tier0_events
    │
    └─► run_database_direct_tier0 (force_database + data_source_id)
            → handled? → 同上
            → 失败且 force_database → 打日志 fallback 到 Kernel（§4+）
```

**注意**：Tier0 **不**经过 `CognitiveSupervisor.prepare_run`；但 `turn_bootstrap` 设计目标让 tier0/resume 与全路径共享 intent metadata（见 `kernel/turn_bootstrap.py` 注释）。

---

## 4. 场景 B — Kernel 极早退出（不进 RuntimeGateway 全路径）

在 `CognitiveKernel.run()` / `stream()` 内，按优先级短路：

### B1 — `bootstrap_turn_intent` + Intent Lock 直答

```text
bootstrap_turn_intent(request)
    ├─ multi_turn_resolution（可选改写 query）
    ├─ world_hydrate（session world model）
    └─ classify_intent → metadata.intent_lock

direct_answer_for_intent(intent_lock) 有值 且 无 force_mode
    → 直接返回答案（stream 走 _emit_streaming_answer）
```

### B2 — Tool Fast Path（Tier0 工具）

```text
should_use_tool_fast_path(intent_lock, force_mode)
    → run_tool_fast_path / stream_tool_fast_path
    → ToolAgent + manifest 审计信封（kernel/fast_tool_path.py）
```

### B3 — 身份缓存

```text
is_identity_user_query + 会话 WorkingMemory 缓存未过期
    → 返回缓存身份答复（route 含 identity 语义）
```

### B4 — V5 Routing Facade（`kernel/routing/v5_facade.py`）

**跳过条件**：`force_mode` 或带附件。

```text
kernel_v5_routing_enabled
    ├─ L0 规则路由（斜杠命令、force_mode 元数据等）→ 命中则返回
    ├─ 语义缓存（需 kernel_semantic_cache_enabled）
    └─ L1 轻量路径（FAQ 等）

特殊：L0 hit route=force_mode → 构造带 force_mode 的 request 再调 RuntimeGateway.run（进入 §5）
```

### B5 — Self Model 守卫

```text
self_model.introspect → CapabilityLevel.UNAVAILABLE
    → identity 特例或「无法处理」文案（route: self_model_guard）
```

**以上均未命中** → 进入 §5 全路径。

---

## 5. 场景 C — vNext 标准单轮（同步 `kernel.run`）

```text
enrich_turn_before_dispatch（memory / fabric / multi-turn 等，metadata.turn_enrichment_applied）
    │
    ▼
KernelRequest 携带 assembled_context、memory_context、intent_lock、tenant、force_mode…
    │
    ▼
RuntimeGateway.run
    ├─ _ensure_turn_enrichment（若 Kernel 未标记则补跑）
    │
    ├─ CognitiveSupervisor.prepare_run
    │       ├─ control_plane_gate → 拒绝 route_hint=control_plane_denied
    │       ├─ runtime_task（light vs full GoalGraph）
    │       ├─ RuntimePolicyEngine.evaluate_planning_phase
    │       ├─ RuntimeGovernor.evaluate_task
    │       ├─ build_runtime_context_from_kernel_request
    │       ├─ goal_lifecycle / goal_projection / world_decision_runtime
    │       ├─ strategy_projection、context_fabric_graph 种子
    │       └─ 产出 SupervisorPreparedRun
    │
    └─ RuntimeTurnDispatcher.run_turn
            ├─ governance 未允许 → KernelResponse 阻断文案
            ├─ resolve_runtime_name → cognitive_executive | data_intelligence | multi_goal
            ├─ [multi_goal] _try_multi_question 优先
            ├─ dispatch_runtime（registry_governance 门禁）
            └─ executive_result_to_kernel_response / multi_question_to_kernel_response
    │
    ▼
CognitiveKernel 收尾（非 Gateway 独有）
    ├─ WorkingMemory / Episodic / memory fabric bind_turn_memory
    ├─ semantic cache store、history index
    ├─ post_turn_enterprise_accounting
    └─ finalize_world_model_for_turn
```

---

## 6. 场景 D — SSE 流式 Chat（`req.stream=true`）

Tier0 未 handled 时：

```text
kernel.stream(kernel_request)
    │
    ├─ 与 run 相同的 B1–B4 早退（delta + final_answer 事件）
    │
    └─ RuntimeGateway.stream
            ├─ prepare_run；governance 拒绝 → type=error
            └─ RuntimeTurnDispatcher.stream_turn
                    ├─ multi_goal：reasoning_step → delta 切块 → final_answer（含 metadata）
                    └─ 其他：reasoning_step(runtime_v2) → executive 流式收集 → delta → final_answer
    │
Gateway _sse() 消费事件
    ├─ reasoning_step → cognitive_event_bus
    ├─ final_answer → 持久化 ConversationState（state_patch、confidence、compact）
    └─ 透出 clarification（若 metadata 含 clarification）
```

块大小与延迟：`CognitiveKernel` / Dispatcher 内 `_STREAM_CHUNK` ≈ 16 字符。

---

## 7. 场景 E — `force_mode` 强制能力域

**入参**：`ChatRequest.force_mode` ∈  
`rag | data_query | data_analysis | anomaly_tracking | product | rule_engine | vision`（及 L0/tool 的 `tool`）。

**走向**：

```text
metadata.force_mode 传入 Kernel
    │
bootstrap / classify_intent
    └─ force_mode 覆盖 task_type、allowed_capabilities（kernel/cognitive_controls.py）

跳过：V5 facade（有 force_mode）、Intent Lock 直答（stream/run 中显式判断）

Supervisor：complexity L0/L1 且无 force_mode 才用 runtime_task_light；
           有 force_mode 时走完整 runtime_task + GoalGraph

CognitiveExecutive 内按 intent_lock 限制能力链与 Agent 调度

单问：Executive + ExecutionRuntime；
复合问：multi_question_runtime + capability 过滤（见 vnext_alignment 行为说明）
```

与 **DataAgent V2** 的关系：`data_query` / `data_analysis` 等路由到数据能力；模糊查询可能触发 `DataClarificationGate`（`kernel/clarification_gate.py`），澄清结果经 metadata → 前端 `clarification` 字段。

---

## 8. 场景 F — 多问题 / Multi-Goal

**识别**：

- `CognitiveKernel._is_multi_question(query)` 或
- `strategy_projection.preferred_runtime == "multi_goal"` 或
- `goal_graph.goals` 数量 > 2（`resolve_runtime_name`）

**走向**：

```text
RuntimeTurnDispatcher
    ├─ run_turn: _try_multi_question → multi_question_to_kernel_response
    └─ stream_turn: 专用 reasoning_step node_multi_question + 流式正文

实现：kernel/runtime/multi_question_runtime.py
      （与 multi_execution_planner、ExecutionRuntime graph 联动）
```

**多轮 + force_mode**：`cognitive_controls` + `multi_execution_planner` 保持域粘性（契约：`test_force_mode_multi_turn_contract.py`）。

---

## 9. 场景 G — Data Intelligence Runtime

**识别**：Supervisor 注入的 `strategy_projection.preferred_runtime == "data_intelligence"`。

```text
dispatch_runtime("data_intelligence", request, ctx)
    └─ services/data_intelligence_runtime.run_data_intelligence_turn
            └─ 与 DataAgent V2 / DAG 产出合并；turn_outcomes 可 enrich_data_turn_outcomes
```

与 **场景 A2** 区别：A2 是 Gateway Tier0 直查；G 是认知栈内注册运行时，带 Goal、治理与 evidence 生命周期。

---

## 10. 场景 H — Cognitive Executive 内部流水线（runtime=cognitive_executive）

单轮主路径的「体内走向」（`kernel/runtime/cognitive_executive.py`）：

```text
execute(query, ctx, event_cb)
    │
    ├─ GoalRuntimeHooks（阶段回调）
    ├─ memory fabric evolve（phase=init）
    ├─ 复用 metadata.intent_lock（不重复 classify）
    │
    ├─ RewriteEngine → UnderstandingEngine → Strategy
    ├─ CognitivePlanner V2 → StrategyBuilder → ExecutionProjection
    ├─ ExecutionRuntime（Agent/DAG 执行，经 capability_runtime / agent_runtime）
    ├─ EvidenceBus（lifecycle + ranking）
    ├─ Fusion V2 → Critic → ArtifactComposer
    └─ Workspace + MemoryFabric + TMS（真值维护）

流式：event_cb 上报 DAG / reasoning 节点（前端 DagTimeline 消费 execution_graph）
```

**Agent 层**：`agents/*` 经 manifest 与 `kernel/agent_runtime` 调度，**禁止** agents import `cognitive_kernel`（import-linter）。

---

## 11. 场景 I — 治理与控制面拒绝（不执行 Executive）

| 阶段 | 位置 | 用户可见 route / 错误 |
|------|------|-------------------------|
| Gateway 预检 | `chat_preflight` | `policy_denied` JSON |
| Supervisor | `control_plane_gate` | `control_plane_denied` |
| Supervisor | `RuntimePolicyEngine` | `runtime_policy_denied` |
| Supervisor | `RuntimeGovernor` | `runtime_governance_denied` |
| Registry | `registry_governance` | `registry_dispatch_denied` |
| Stream | `RuntimeGateway.stream` | SSE `type=error` |

Goal 侧效果：violations 时 `mark_goals_blocked_for_governance`。

---

## 12. 场景 J — 多轮澄清（Clarification）

```text
用户首轮模糊数据问句
    └─ DataAgent V2 流水线 / DataClarificationGate.detect
            └─ metadata.clarification + question_id

用户次轮携带 clarify_context / clarify_question_id / parent_message_id
    └─ Gateway 写入 KernelRequest metadata
    └─ turn_enrichment / clarification_enrichment 合并上下文
    └─ 正常走 §5 或 §7
```

对话编排器兼容桩：`ClarificationGate`（空实现，历史兼容）。

---

## 13. 场景 K — Resume Turn

```text
POST /chat/resume { session_id, step_index }
    │
load_resume_context_from_trace(TraceLog) → query + prior execution_graph
    │
resume_turn_via_gateway → KernelRequest → RuntimeGateway.run（同 §5）
```

不保证复现 Tier0 短路；以 Trace 中 query 为准重跑认知路径。

---

## 14. 场景 L — 企业收尾（Turn Finalize）

在 **Kernel.run** 成功返回前、以及 **RuntimeGateway.run** 内均可能触发：

```text
post_turn_enterprise_accounting(request, response)
    ├─ 配额 consume（tenant / Redis 镜像可选）
    ├─ billing、usage metering
    └─ enterprise_outcomes / goal portfolio 元数据

finalize_world_model_for_turn
    └─ world / cross_process_world 切片写回 metadata.shared_world_state
```

Stream 路径：`final_answer` 的 metadata 可含 `enterprise_telemetry`、`control_plane` 等（契约：`test_stream_enterprise_metadata_contract.py`）。

---

## 15. 场景对照速查表

| 用户表象 | 首选路径 | 关键模块 |
|----------|----------|----------|
| 「把上次 SQL 给我」 | A1 Tier0 | `tier0_paths` |
| 选库 + 强制查数 | A2 或 fallback C/G | `try_tier0_chat` / `data_intelligence` |
| 天气 / 时间 / 单工具 | B2 | `fast_tool_path` |
| 你是谁 | B3 / B4 identity | WorkingMemory / L0 |
| 普通问答 | C + H | `cognitive_executive` |
| `/command` 类 L0 | B4 | `tiny_router` / L0 |
| `force_mode=rag` | E + H（能力过滤） | `cognitive_controls` |
| 一次问多件事 | F | `multi_question_runtime` |
| 超配额 / PII 策略 | I | `control_plane` / preflight |
| 澄清后再问 | J | `clarification_*` |
| 断点续跑 | K | `resume_turn` |

---

## 16. 与测试、文档的对应关系

| 验证手段 | 覆盖场景 |
|----------|----------|
| `scripts/run_vnext_final_tests.sh` | vNext 主路径、import 边界 |
| `scripts/run_enterprise_contract_tests.sh` | 租户、预检、finalize、遥测 |
| `tests/test_tier0_paths_contract.py` | A1/A2 |
| `tests/test_tool_fast_path_contract.py` | B2 |
| `tests/test_v5_routing_contract.py` | B4 |
| `tests/test_multi_question_runtime_contract.py` | F |
| `tests/test_chat_preflight_contract.py` | Gateway 预检 |
| `tests/test_clarification_*` | J |
| `tests/test_resume_turn_contract.py` | K |

---

## 17. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-15 | 初版：按代码库梳理 Gateway / Kernel / Supervisor / Dispatcher / Runtime 分场景走向 |