# Enterprise Cognitive OS — 需求拆分与实现映射

> **最终结论（架构定位）**  
> OpenTrace 当前已是 **Agent Operating System** 量级（Runtime / Goal / Governance / Capability / Memory / Replay 主路径闭合）。  
> 下一阶段目标是 **Cognitive Operating System（企业级）**：在现有四平面（Runtime / Capability / Memory / Governance）之上补齐 **Control Plane**，并落地五块企业能力：**Capability OS、World Model Runtime、Enterprise Observability、Multi-Tenant Runtime、Goal Portfolio Runtime**。

## 一、需求 → 仓库映射（拆分理解）

| 需求块 | 现状（代码锚点） | 企业级缺口 | 本迭代实现 |
|--------|------------------|------------|------------|
| Control Plane | `kernel/capability_runtime/capability_control_plane.py`（能力描述符） | 租户/配额/成本/合规统一入口 | `control_plane/` 统一门面 + 与 Governance 联动 |
| Capability OS | `lifecycle.py`（draft→retired）、`capability_control_plane` | Degraded、SLA 指标、Marketplace | 扩展 lifecycle + `capability_sla` + registry 指标 |
| World Model Runtime | `kernel/cognition/runtime_grounding.py`（7 slice） | Tenant/Org/Resource + world_graph | `world/` 扩展 slice + `world_graph` |
| Enterprise Observability | `semantic_metrics*`、`run_outcomes` | Cognitive/Business/Cost 遥测 | `observability/enterprise_telemetry.py` |
| Multi-Tenant | 仅 `user_id`/`session_id` 散落 | 六层隔离 + quota/billing | `tenant/` 运行时模型 |
| Goal Portfolio | `kernel/goal/*` lifecycle | Program → Initiative → Task | `kernel/goal/goal_portfolio.py` |
| Cognitive Agent | `agents/base.py` Request→Execute | perception…learning 环 | `agents/cognitive_agent.py` |
| Compliance | `governance_center` + policy_runtime | GDPR/SOC2 框架钩子 | `kernel/governance/compliance_runtime.py` |
| Memory 企业化 | `truth_maintenance.py` 已有 | 压缩/归档策略暴露到 Control Plane | 遥测 + policy 钩子 |

## 二、平面架构（目标态）

```text
                    ┌─────────────────────────┐
                    │     Control Plane       │
                    │ tenant · quota · cost   │
                    │ compliance · capability │
                    └───────────┬─────────────┘
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
 Governance Plane      Capability Plane          Memory Plane
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
                        Runtime Plane
              CognitiveSupervisor → TurnDispatcher → Executives
                                │
                                ▼
                     World Model Runtime (shared state)
```

## 三、成熟度评分（文档口径，非阻塞）

| 模块 | 当前 | 目标 | 补齐后（设计） |
|------|------|------|----------------|
| Multi-Tenant | 4.0 | 9.8 | 6.5（本迭代骨架） |
| Cost Governance | 5.0 | 9.8 | 7.0 |
| Observability | 8.2 | 9.8 | 8.8 |
| World Model | 8.0 | 9.7 | 8.6 |
| 综合 | 9.1 | 9.7 | 9.4（路线图） |

## 四、第二轮优化（接线）

| 能力 | 变更 |
|------|------|
| Control Plane 门禁 | `prepare_run` → `control_plane_gate`；拒绝路由 `control_plane_denied` |
| Gateway 预检 | `chat` → PII 检测 + `preflight_from_metadata`；拒绝返回 `policy_denied` |
| Gateway 多租户 | `X-Tenant-Id` / `X-Org-Id` / `X-Workspace-Id` → `RuntimeContext.metadata` |
| Capability OS | `dispatch_pipeline` → SLA + `DEGRADED`；Prometheus `opentrace_capability_success_rate` |
| Prometheus | `opentrace_enterprise_*`、`control_plane_denials`、goal stability |
| Governance | `evaluate_turn` 附带 `compliance_runtime`；`governance/pii_detector.py` |
| Data Intelligence | `turn_outcomes` 在 data 路由合并 `enrich_data_turn_outcomes` |
| Memory 压缩 | `memory/fabric/memory_compression.py`；fabric 节点超 64 时输出 `memory_maintenance_plan` |
| Turn 后企业元数据 | `enterprise_outcomes` → quota consume、billing、telemetry、portfolio |

## 五、验收

```bash
bash scripts/run_enterprise_contract_tests.sh
```

与 `scripts/run_vnext_final_tests.sh` 并列，作为 Enterprise 门禁。**CI：`vnext-contract.yml` 已纳入 `run_enterprise_contract_tests.sh`（28 项）。**

## 六、第三轮优化（Agent V3 + 跨进程骨架）

| 能力 | 变更 |
|------|------|
| Evidence Graph | `services/evidence_graph/` — rank / contradiction / synthesis |
| RAG V3 | `services/rag_evidence_intelligence.py` → `RagAgent` metadata `rag_evidence_intelligence` |
| Web Intelligence | `agents/web_intelligence_agent.py`（CognitiveAgent + evidence graph）+ bootstrap 注册 |
| World Redis 门面 | `world/world_state_redis.py`；turn 结束 `save_session_world_state`（flag 开启时） |
| Tenant Policy | `tenant/policy_manager.py` + Gateway `build_tenant_metadata` |
| Tenant 持久化骨架 | `tenant/tenant_store.py`（无表时静默 fallback 内存） |

## 七、仍依赖外部工程（非代码骨架）

- `tenants` 表 migration + RLS
- 真实 LLM 用量计费 / 发票
- DLP 与合规审计落库
- Web/RAG 生产级 rerank + LLM 事实核验