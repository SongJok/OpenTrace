# ADR-003: Memory Fabric 为主读路径

## 状态

已接受

## 决策

- `kernel_memory_fabric_primary_only=true`（默认）：Fabric 有命中时跳过 legacy `MemoryRouter` 桶合并。
- `kernel_memory_fabric_retrieval_enabled` 控制是否在回合前注入 Fabric 检索。
- Redis graph shadow：`kernel_memory_graph_redis_enabled`；绑定/检索时 hydrate/persist。
- staging 强制 `primary_only` 与 `kernel_cognitive_state_persist_enabled=true`。

## 变更 primary_only=false

仅用于对比实验或迁移；需架构评审并在非生产环境进行。

## 验证

`tests/test_memory_graph_redis_contract.py`、`TestStagingFabricPrimaryDefaults`