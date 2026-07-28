# OpenTrace — 高影响 Feature Flag 注册表

> 产品成熟度：**Alpha**。能力组合优先使用 `CAPABILITY_PROFILE`；本表只保留少量紧急熔断、迁移与实验例外。旧 Cognitive Runtime 细粒度字段仅兼容读取，不属于产品配置面。

## 能力 Profile（默认组合不超过 5 套）

| Profile | 内置 Agent | 用途 |
|---|---|---|
| `core` | tool / skills / rules | 最小 Responses 工具执行 |
| `data` | core + data | DataAgent / Text2SQL |
| `knowledge` | core + rag | 企业知识问答 |
| `data_knowledge` | data + knowledge + web_intelligence + vision | 默认完整产品闭环 |

## 公开高影响开关（自动生成）

| Flag | 默认 | 阶段 | Owner | 引入版本 | 退出条件 | 最晚删除版本 | 影响面 | 依赖 |
|---|---:|---|---|---|---|---|---|---|
| `kernel_runtime_phase_transition_strict` | true | stable | runtime | 0.1.0 | — | — | responses-runtime | — |
| `kernel_registry_dispatch_strict` | true | stable | runtime | 0.1.0 | — | — | tool-dispatch | — |
| `kernel_runtime_replay_enabled` | true | stable | observability | 0.1.0 | — | — | audit-replay | — |
| `kernel_agent_runtime_v3_strict` | false | stable | agent-runtime | 0.1.0 | — | — | agent-contribution-contract | kernel_agent_runtime_v3_enabled |
| `kernel_agent_learning_auto_apply` | false | experimental | agent-quality | 0.1.0 | 连续两个 Beta 发布中通过回放评测且无越权策略写入 | 0.3.0 | learning | kernel_capability_intelligence_enabled |
| `data_agent_v2_fallback_to_v1` | false | deprecated | data-agent | 0.1.0 | — | — | data | — |
| `enterprise_tenant_rls_enabled` | false | experimental | security | 0.1.0 | 核心事实表 RLS 与跨租户负向测试全部进入发布门禁 | 0.3.0 | tenant-isolation | — |
| `web_fetch_enabled` | false | experimental | security | 0.1.0 | 独立网络出口、域名白名单、凭据隔离和配额全部落地 | 0.3.0 | network-egress | — |

## 企业协议上线控制（自动生成）

| Control | 默认 | 阶段 | Owner | 引入版本 | 退出条件 | 最晚删除版本 | 影响面 |
|---|---:|---|---|---|---|---|---|
| `identity_oidc_enabled` | false | experimental | security | 0.1.0 | 完成两个受支持 IdP 的 JWKS、撤销和故障切换互操作认证 | 0.3.0 | authentication |
| `mcp_client_enabled` | false | experimental | runtime | 0.1.0 | 工具 allowlist、审批和幂等账本互操作矩阵全部通过 | 0.3.0 | interoperability |
| `mcp_server_enabled` | false | experimental | runtime | 0.1.0 | MCP 兼容矩阵和 durable Responses 适配连续两个版本稳定 | 0.3.0 | interoperability |
| `a2a_protocol_enabled` | false | experimental | runtime | 0.1.0 | 服务身份、租户绑定、防重放与端到端互操作测试全部通过 | 0.3.0 | interoperability |

## 治理规则

- 新能力优先加入现有 Profile，不新增布尔开关。
- 实验开关必须同时声明 owner、引入版本、退出条件和最晚删除版本。
- deprecated 开关只用于滚动升级，禁止在新部署模板中默认开启。
- `development/staging/production` 决定安全强度；`CAPABILITY_PROFILE` 决定能力集合。
