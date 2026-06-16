# Runbook — 单轮对话追踪

## 1. 获取 trace

- 客户端响应或 SSE 中的 `trace_id` / `conversation_id`。
- Jaeger（`--with-observability`）：`http://localhost:14186`，按 `trace_id` 搜索。

## 2. 主路径检查点

| 阶段 | 模块 | 日志/字段关键词 |
|------|------|-----------------|
| 入口 | `gateway/.../chat.py` | session_id, user_id |
| 内核 | `cognitive_kernel.py` | memory inject, route tier |
| 准备 | `cognitive_supervisor/supervisor.py` | GoalGraph, intent_lock, governance_meta |
| 分发 | `runtime_gateway.py` | dispatcher, runtime_key |
| 执行 | `cognitive_executive` / `data_intelligence` / `multi_goal` | phase, capability |
| 收尾 | `run_outcomes.py` | artifact, goal_evidence, semantic_alerts |

## 3. 健康 API

```bash
curl -s http://127.0.0.1:14100/api/v1/health/deps | jq .
curl -s http://127.0.0.1:14100/api/v1/health/runtime | jq .
```

## 4. 确定性回放

```bash
python scripts/opentrace_replay.py <trace_id>
```

需 `kernel_runtime_replay_enabled=true` 且回合已写入快照。

## 5. 常见分叉

- **L0/L1 快答**：未进入 Executive 全图 — 查 `kernel_v5_routing_enabled` 与 semantic cache 命中。
- **Data 路径**：`kernel_data_intelligence_routing_enabled` → `services/data_intelligence_runtime`。
- **多问题**：`multi_question_runtime` / `multi_goal` registry 键。