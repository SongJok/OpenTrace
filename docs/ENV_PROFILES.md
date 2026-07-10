# OpenTrace — 环境 Profile（推荐开关）

基于 `infra/config/settings.py` 与 staging 校验器。复制到 `.env` 时仅调整 `APP_ENV` 与下列差异项。

## development（本地默认）

| 开关 | 推荐 |
|------|------|
| `APP_ENV` | `development` |
| `DEBUG` | `true`（可选） |
| `kernel_orchestrator_v4_enabled` | **false** |
| `kernel_runtime_phase_transition_strict` | true |
| `kernel_registry_dispatch_strict` | true |
| `kernel_evidence_contract_strict` | true |
| `kernel_capability_contract_strict` | true |
| `kernel_memory_fabric_primary_only` | true |
| `kernel_cognitive_state_persist_enabled` | false（单进程开发可关） |
| `kernel_memory_graph_redis_enabled` | true（需 Redis） |

## staging

| 开关 | 行为 |
|------|------|
| `APP_ENV` | `staging` |
| `APP_SECRET_KEY` / `JWT_SECRET` / `DATA_SECRET_KEY` | **必须为非占位值** |
| `GATEWAY_PORT` / `APP_PORT` | **必须一致** |
| `kernel_memory_fabric_primary_only` | **强制 true**（即使 .env 写 false） |
| `kernel_cognitive_state_persist_enabled` | **强制 true** |
| `kernel_world_state_persist_enabled` | **强制 true**（Redis `world_state:{session_id}`） |
| `kernel_policy_mutation_fail_closed` | **强制 true**（策略拒绝即中断回合） |
| `kernel_runtime_phase_transition_strict` | 当 `kernel_staging_phase_transition_strict=true` 时 **强制 strict** |
| `kernel_agent_runtime_v3_strict` | **强制 true**（Tier-1 `AgentContribution` 契约违例即失败） |
| `kernel_unified_evidence_strict` | **强制 true**（成功回合须带 `UnifiedEvidence`） |
| `enterprise_quota_redis_enabled` | **true**（日额度/成本走 Redis 原子 INCR；多副本一致） |
| `enterprise_usage_redis_enabled` | **true**（租户用量 HINCRBY 日聚合） |
| `kernel_agent_learning_auto_apply` | **false**（仅记录 `strategy_shadow`；候选策略经离线评估和审批后再发布） |
| `data_agent_v2_verification_replan_enabled` | true（校验 fail 有限次重跑 DAG） |
| `rag_rrf_fusion_enabled` | true（document/llmwiki/memory 分路 RRF 后再 evidence intelligence） |

Supervisor prepare 会写入 `ctx.metadata["effective_runtime_flags"]`（`infra/config/flag_governance.py` 快照）。

### Agent Runtime V3 strict（staging → production 渐进）

| 开关 | development | staging | production |
|------|-------------|---------|------------|
| `kernel_agent_runtime_v3_enabled` | true | true | true |
| `kernel_agent_runtime_v3_strict` | false（默认） | **true**（profile 强制） | **true**（profile 强制） |
| `kernel_unified_evidence_strict` | false | **true** | **true** |

Worker 与 in-process dispatch 在 `kernel_agent_runtime_v3_enabled=true` 时走 `AgentRuntimeExecutor`；strict 打开后空成功载荷、缺 unified evidence 会 `RuntimeError`（见 `kernel/agent_runtime/executor.py`）。

## production

| 开关 | 行为 |
|------|------|
| `APP_ENV` | `production` |
| `DEBUG` | **false** |
| `APP_SECRET_KEY` / `JWT_SECRET` / `DATA_SECRET_KEY` | **必须为非占位值** |
| `GATEWAY_PORT` / `APP_PORT` | **必须一致** |
| `kernel_memory_fabric_primary_only` | **强制 true** |
| `kernel_cognitive_state_persist_enabled` | **强制 true** |
| `kernel_world_state_persist_enabled` | **强制 true** |
| `kernel_policy_mutation_fail_closed` | **强制 true** |
| `kernel_agent_runtime_v3_strict` | **强制 true** |
| `kernel_unified_evidence_strict` | **强制 true** |
| `kernel_orchestrator_v4_enabled` | **false**（勿开） |
| `kernel_semantic_alerts_enabled` | true |
| `TRACE_ENABLED` | true（配合 OTLP） |

实现见 `infra/config/settings.py` 中 `_apply_staging_profile` / `_apply_production_profile` / `_require_runtime_secrets_for_managed_envs`。`staging` / `production` 启动前必须执行 Alembic 迁移；应用启动只做只读 schema readiness 校验，不再自动补 DDL。

## 降本 / 调试（仅非生产）

可临时关闭以缩短延迟（需记录原因）：

- `kernel_semantic_cache_enabled`
- `kernel_capability_intelligence_phase2_enabled`
- `kernel_runtime_replay_enabled`
- `data_agent_v2_advanced_analytics_mode=off`

主路径仍应走 vNext；勿在生产打开 `kernel_orchestrator_v4_enabled`。
