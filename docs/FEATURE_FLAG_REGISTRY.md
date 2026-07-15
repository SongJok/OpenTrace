# OpenTrace — Feature Flag 注册表（内核与数据）

新增开关请在本表追加一行。完整列表见 `infra/config/settings.py` 与 `.env.example`。

| Flag | 默认 | 影响面 | Owner 域 |
|------|------|--------|----------|
| `kernel_goal_driven_dag_enabled` | true | Goal→DAG 1:1 | goal |
| `kernel_runtime_phase_transition_strict` | true | 非法 phase 阻断 | runtime |
| `kernel_registry_dispatch_strict` | true | registry 违规阻断 | runtime |
| `kernel_evidence_contract_strict` | true | 证据契约 | governance |
| `kernel_capability_contract_strict` | true | 能力拓扑 | capability |
| `kernel_memory_fabric_primary_only` | true | 记忆读路径 | memory |
| `kernel_memory_fabric_retrieval_enabled` | true | Fabric 检索 | memory |
| `kernel_memory_graph_redis_enabled` | true | 关系图 Redis | memory |
| `kernel_cognitive_state_persist_enabled` | false* | Redis 认知态 | runtime |
| `kernel_governance_evidence_gate_enabled` | true | 证据门控 | governance |
| `kernel_governance_risk_gate_enabled` | true | 风险门控 | governance |
| `kernel_semantic_alerts_enabled` | true | 语义告警导出 | observability |
| `kernel_runtime_replay_enabled` | true | 回放快照 | replay |
| `kernel_capability_intelligence_enabled` | true | Profiler Phase1 | capability |
| `kernel_capability_intelligence_phase2_enabled` | true | KG/策略记忆 | capability |
| `kernel_clarification_gate_enabled` | true | 澄清问句 | cognition |
| `kernel_conversation_state_enabled` | true | 结构化多轮 | cognition |
| `kernel_refine_replan_enabled` | true | 失败重规划 | runtime |
| `kernel_data_intelligence_routing_enabled` | true | Data V2 runtime | data |
| `kernel_data_intelligence_route_executive` | false | Data tier → full Executive | data |
| `data_agent_v2_enabled` | true | DataAgent V2 | data |
| `data_agent_v2_fallback_to_v1` | false | V1 回退 | data |
| `kernel_agent_bus_enabled` | true | Redis Bus | agents |
| `kernel_agent_bus_mode` | pubsub | stream/pubsub | agents |
| `kernel_agent_runtime_v3_enabled` | true | Manifest SSOT、UnifiedEvidence、GoalParticipation | agents |
| `kernel_agent_runtime_v3_strict` | false | Contribution 契约 fail-closed | agents |
| `kernel_unified_evidence_strict` | false | 成功 turn 必须有 UnifiedEvidence | governance |
| `kernel_agent_runtime_p3_enabled` | true | Hypothesis/Contradiction/Reflection 元数据 | cognition |

\* staging 下强制 `true`，见 `ENV_PROFILES.md`。

## 内核注册表（自动生成）

<!-- KERNEL_REGISTRY_AUTO_START -->
| Flag | 默认 | Phase | 依赖 | 影响面 |
|------|------|-------|------|--------|
| `kernel_runtime_phase_transition_strict` | false | stable | — | runtime |
| `kernel_cognitive_state_persist_enabled` | false | stable | — | runtime |
| `kernel_staging_phase_transition_strict` | false | stable | kernel_runtime_phase_transition_strict | runtime |
| `kernel_refine_replan_enabled` | true | stable | — | planning |
| `kernel_memory_fabric_primary_only` | false | stable | — | memory |
| `kernel_runtime_replay_enabled` | false | experimental | — | replay |
| `kernel_agent_runtime_v3_enabled` | true | stable | — | agent_runtime |
| `kernel_agent_runtime_v3_strict` | false | experimental | kernel_agent_runtime_v3_enabled | agent_runtime |
| `kernel_unified_evidence_strict` | false | experimental | kernel_agent_runtime_v3_enabled | evidence |
| `kernel_web_intelligence_preferred` | true | stable | — | routing |
| `enterprise_quota_redis_enabled` | false | experimental | — | control_plane |
| `enterprise_usage_redis_enabled` | false | experimental | — | control_plane |
| `enterprise_tenant_rls_enabled` | false | experimental | tenants migration | tenant |
| `enterprise_billing_prompt_per_million` | 0.15 | stable | — | billing |
| `enterprise_billing_completion_per_million` | 0.60 | stable | — | billing |
| `enterprise_tenant_rls_enabled` | false | experimental | Postgres `tenants` + `app.tenant_id` | tenant |
<!-- KERNEL_REGISTRY_AUTO_END -->
