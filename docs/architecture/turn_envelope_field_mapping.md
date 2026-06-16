# Turn / Stream Envelope — 字段映射（后端 → 前端）

> 规范实现：`frontend/src/utils/streamEnvelope.ts`（`normalizeFinalAnswerEnvelope`）  
> 后端合并：`kernel/agent_runtime/stream_metadata.py`、`kernel/cognitive_supervisor/run_outcomes.py`、chat SSE `final_answer` 载荷。

## 顶层 `final_answer` / 同步 chat 响应

| 前端 `TurnMetaEnvelope` | 后端来源（优先级从高到低） | 说明 |
|---------------------------|----------------------------|------|
| `content` | `data.content` → `data.answer` | 用户可见正文 |
| `execution_graph` | `data.execution_graph` | DAG / 执行图（对象） |
| `citations` | `data.citations` | RAG 引用列表 |
| `annotations` | `data.annotations` | 冲突、 grounding 等注解 |
| `metadata` | `data.metadata`（浅拷贝） | 全量 turn 元数据；子字段见下表 |
| `control_plane` | `data.control_plane` → `metadata.control_plane` | 企业控制面决策 |
| `capabilities_used` | `data.capabilities_used` → `metadata.capabilities_used` | 本 turn 能力列表 |
| `prompt_tokens` | `data.prompt_tokens` → `metadata.prompt_tokens` | Token 计量 |
| `completion_tokens` | `data.completion_tokens` → `metadata.completion_tokens` | Token 计量 |
| `enterprise_telemetry` | `data.enterprise_telemetry` → `metadata.semantic_observability.enterprise_telemetry` | 企业遥测 |
| `result_refs` | `data.result_refs` → `metadata.result_refs` | SQL/表等结果引用 |
| `needs_clarification` | `data.needs_clarification` → `metadata.needs_clarification` 或 `turn_outcome===clarification` | 澄清门 |
| `clarification` | `data.clarification` → `metadata.clarification` | 澄清问题载荷 |
| `turn_outcome` | `data.turn_outcome` → `metadata.turn_outcome` | `success` / `error` / `clarification` / `degraded` 等 |
| `governance_warnings` | 派生：`metadata.runtime_degraded[].subsystem` + `control_plane.allowed===false` | 前端聚合，非后端单字段 |

## `metadata` 常用子字段（Agent / Kernel）

| 子字段 | 写入方 | 前端用途 |
|--------|--------|----------|
| `semantic_observability` | `GovernanceCenter.evaluate_turn` | 降级、合规、enterprise_telemetry |
| `runtime_degraded` | 各子系统降级 | → `governance_warnings` |
| `goal_graph` | Goal runtime / dispatcher | 多目标进度 |
| `goal_participation` | `attach_goal_participation` | Agent 对 goal 的贡献 |
| `cognitive_state_graph` | `persist_graph_on_context` | CognitiveStateGraph 快照（staging/prod） |
| `cognitive_runtime_state` | `cognitive_state/bus.py` | phase、evidence_ids、memory_bindings |
| `agent_runtime_v3` | stream_metadata merge | V3 运行时标记 |
| `data_intelligence` / `data_intelligence_turn` | Data V2 / DI runtime | 数据智能 turn 摘要 |
| `advanced_analytics` | DataAgent V2 Supervisor Phase 4 | mode、degraded、各分析是否执行 |
| `verification_report` | Data V2 verify 节点 | 质量门禁 |
| `turn_outcome` / `pipeline_stage` | Data V2 `turn_metadata` | 流水线阶段 |
| `billing_attribution` | `finalize_turn` | 计费归因 |
| `tenant_id` / `org_id` / `workspace_id` | tenant middleware | 多租户 UI |

## SSE 事件类型（Chat）

| 事件 | 载荷要点 | 与 envelope 关系 |
|------|----------|------------------|
| `token` / `delta` | 流式文本 | 累积为 `content` |
| `dag_node` | node_id、status、agent_type | `execution_graph` / DagTimeline |
| `final_answer` | 上表顶层字段 | `normalizeFinalAnswerEnvelope` 入口 |
| `error` | message、code | 非 envelope；Chat 错误态 |

## 契约测试

- `frontend/src/utils/__tests__/streamEnvelope.contract.test.ts`
- `tests/test_stream_enterprise_metadata_contract.py`

更新后端字段时：**先改本文档与 `streamEnvelope.ts`，再补契约测试**。