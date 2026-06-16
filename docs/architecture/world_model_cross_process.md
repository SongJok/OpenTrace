# World Model — 跨进程 / 多副本设计（vNext 演进）

> **状态**：设计冻结 + 空实现契约（`world/cross_process_world.py`）。单进程主路径仍使用 `kernel/cognition/runtime_grounding` + 可选 `world/world_state_redis.py`。

## 问题陈述

| 现状 | 限制 |
|------|------|
| `RuntimeGroundingState` 进程内 dict | Gateway 与 Agent Worker 不共享 grounding |
| `persist_world_state`（Redis） | 会话级快照，无版本向量 / 租约 |
| `build_shared_world_state` | 回合内投影，非集群 SSOT |

**目标**：在多个 API / Worker 副本间提供 **可合并、可观测、可回滚** 的 World Model 切片，而不阻塞当前 vNext 发布。

## 非目标（本阶段）

- 强一致分布式事务
- 实时 CRDT 全图合并
- 替代 Memory Fabric / Evidence Bus

## 架构分层

```
┌─────────────────────────────────────────────────────────┐
│  Cognitive Executive / Supervisor                        │
│  reads: WorldProjectionBundle + RuntimeGroundingState    │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│  world/cross_process_world.py  (facade — 本设计)         │
│  - publish_slice(session, slice_type, payload, version)  │
│  - fetch_merged(session) → MergedWorldSnapshot           │
│  - backend: noop | redis_json (future)                   │
└───────────────────────────┬─────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   Redis HASH         Postgres JSONB      (future) event log
   opentrace:wm:{sid}  wm_snapshots
```

## 数据模型（契约）

### `WorldSliceEnvelope`

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | str | 会话键 |
| `slice_type` | enum | `goal` \| `capability` \| `risk` \| `temporal` \| `execution` |
| `payload` | dict | 与 `runtime_grounding` 对应切片 JSON |
| `version` | int | 单调递增（per session + slice_type） |
| `writer_id` | str | `pod:{hostname}` 或 `worker:{consumer}` |
| `updated_at` | ISO8601 | UTC |

### `MergedWorldSnapshot`

| 字段 | 说明 |
|------|------|
| `session_id` | |
| `slices` | `slice_type → payload`（last-write-wins by version） |
| `merge_policy` | `lww_version`（默认） |
| `stale` | 任一副本版本落后阈值时为 true |
| `backend` | `noop` \| `redis` |

## 合并策略（Phase 1）

1. **LWW by version**：同 `slice_type` 取最大 `version`。
2. **冲突标记**：若两写入 `version` 相同且 `payload` 不同 → `stale=true`，`conflicts[]` 记录。
3. **Hydrate**：`fetch_merged` 结果经 `merge_persisted_into_grounding` 注入进程内 store（与现有 Redis 路径兼容）。

## 开关

| Flag | 默认 | 行为 |
|------|------|------|
| `kernel_world_state_persist_enabled` | false（staging true） | 现有单进程 Redis 快照 |
| `kernel_world_model_cross_process_enabled` | **false** | 启用 `CrossProcessWorldBackend`（非 noop） |
| `kernel_world_model_cross_process_backend` | `noop` | `noop` \| `redis`（redis 待实现） |

##  rollout 阶段

| 阶段 | 交付 | 验收 |
|------|------|------|
| **P0** | 设计 doc + noop facade + 契约测试 | `test_world_model_cross_process_contract.py` |
| **P1** | ✅ Redis HASH（`world/cross_process_world_redis.py`）+ execution→grounding 桥接 | mock Redis 契约 + `KERNEL_WORLD_MODEL_CROSS_PROCESS_BACKEND=redis` |
| **P2** | Worker 发布 execution/risk 切片 | E2E agent_bus + world merge |
| **P3** | 版本向量 / 租约（可选） | 混沌测试 |

## 与 Data V2 的交界

Data Intelligence Runtime 在 SQL 成功后应发布 `execution` 切片（`phase=verified`, `sql_hash`），供多副本会话恢复 — 见 `test_data_agent_v2_extended_contract.py` 的规划项 `world_slice_hook`（metadata 占位）。

## 参考实现

- 单进程：`kernel/cognition/runtime_grounding.py`
- Redis 快照：`kernel/cognition/runtime_grounding.persist_world_state`
- Facade：`world/cross_process_world.py`
- 契约：`tests/test_world_model_cross_process_contract.py`