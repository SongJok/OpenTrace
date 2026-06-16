# Cognitive OS 需求对照矩阵（与 `ARCHITECTURE_REQUIREMENTS_MATRIX.md` 对齐）

> **权威矩阵**：`docs/ARCHITECTURE_REQUIREMENTS_MATRIX.md`（16+1 项 + CI 回归）。  
> 本文件记录 **细粒度缺口** 与 **已关闭项**，避免与权威矩阵矛盾。

| # | 需求项 | 状态 | 实现 / 缺口 |
|---|--------|------|-------------|
| 1 | RuntimeGateway 去中心化 | done | Supervisor + 瘦 Gateway；契约 `TestRuntimeGatewaySlimContract` |
| 2 | Cognitive Supervisor | done | `prepare_run` / `run_outcomes` |
| 3 | GoalGraph 一等公民 | done | `goal_projection`、`plan_from_goal_context`；`TestGoalDrivenPlanning` |
| 4 | State-based Runtime | partial | store + phase strict；多副本 cognitive_state 一致性待加强 |
| 5 | Strategic Planner 分层 | done | `planner_facade` + Executive |
| 6 | Capability OS | done | `capability_runtime` + registry strict + dispatch pipeline |
| 7 | Memory Fabric | partial | retrieval + redis graph + bind；跨集群 graph 待加强 |
| 8 | Governance 前置 | done | Executive phase gov + `kernel_evidence_contract_strict` |
| 9 | Context Fabric | partial | `context_fabric` + **DST/ReferenceResolver 已实装**（`multi_turn_resolution`）；composer 仍可深化 |
| 10 | World Model | partial | **turn begin/end**：`world_turn_begin` hydrate + `world_turn_finalize` + slice hooks；跨进程 Redis 待生产验证 |
| 11 | Multi-Goal | done | scheduler + `multi_goal_resources` + outcomes 契约 |
| 12 | Runtime Contract | done | replay + phase strict + `TestReplayContract` |
| 13 | Semantic OS Metrics | done | semantic_metrics_pipeline |
| 14 | V4 legacy | done | `legacy/v4`；默认关闭 |
| 15 | DataAgent V2 | done | supervisor + `data_intelligence_runtime` |
| 16 | Architecture Governance | done | import boundaries + vnext/enterprise contract runners |
| 17 | Agent Runtime V3 | done | manifest、bootstrap parity、executor evidence、bus_eligible、agents 无 gateway |

## 与规划 2.7 落地顺序对照

| Phase | 规划目标 | 实现一致？ |
|-------|----------|------------|
| A 收敛主路径 | V2 默认、凭据 SSOT、web 单轨、evidence attach | **是**（代码 + 契约） |
| B 证据同构 | Tier-1 `evidence_objects`、strict profile | **是**（dev 默认 soft strict；staging/prod 强制） |
| C 企业化 | tenant RLS、计费持久化 | **否**（控制面/Redis 有；DB RLS 外部工程） |
| D 减负 | learning hook、CAPABILITY_MATURITY、V4 删除 | **部分**（hook + 文档；V4 未删源码） |

## Agent / 认知能力深化（本轮已落地）

| 能力 | 模块 | 契约 |
|------|------|------|
| 多轮 DST + 指代 | `multi_turn_resolution` + `cognitive_kernel` run/stream | `test_multi_turn_resolution_contract` |
| RAG V3 矛盾门控 + 学习 | `rag_agent` + `rag_evidence_intelligence` | `test_rag_evidence_intelligence_contract` |
| 偏好注入 | `preference_injection` | `test_preference_world_data_learning_contract` |
| Data V2 自动学习 | `supervisor` auto_mode + pattern/knowledge | 同上 |
| World turn hydrate/finalize | `world_turn_begin` / `world_turn_finalize` | 同上 |
| Capability 学习闭环 | `learning_hook` + Data 熔断 | `test_capability_intelligence`（可选） |

## 后续优化（按 ROI）

1. **契约**：`test_architecture_requirements_alignment` — `TestAgentRuntimeV3Alignment`（manifest bootstrap、agents 无 gateway）。
2. **文档**：对外以 `ARCHITECTURE_REQUIREMENTS_MATRIX.md` 为准；本文件只记 partial 债。
3. **企业**：tenant RLS + billing store 与 `test_multi_tenant_runtime_contract` 闭环。
4. **Strict dev**：本地 `KERNEL_AGENT_RUNTIME_V3_STRICT=false`；CI 用 `APP_ENV=staging` 覆盖 strict。
5. **仍外部/大工程**：生产 RAG LLM 事实核验、真 RL 训练环、V4 源码删除、多副本 cognitive state 强一致。