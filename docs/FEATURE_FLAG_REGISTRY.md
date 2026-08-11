# OpenTrace — 高影响 Feature Flag 注册表

> 产品成熟度：**受控企业 Beta**。能力组合优先使用 `CAPABILITY_PROFILE`；本表只保留少量紧急熔断、迁移与实验例外。旧 Cognitive Runtime 细粒度字段仅兼容读取，不属于产品配置面。

## 能力 Profile（默认组合不超过 5 套）

| Profile | 内置 Agent | 用途 |
|---|---|---|
| `core` | 无专家 Agent | 仅 Manager 模型问答 |
| `data` | data | DataAgent / Text2SQL |
| `knowledge` | rag | 企业知识 RAG |
| `data_knowledge` | data + rag | 默认提问闭环 |

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

## 企业身份上线控制（自动生成）

| Control | 默认 | 阶段 | Owner | 引入版本 | 退出条件 | 最晚删除版本 | 影响面 |
|---|---:|---|---|---|---|---|---|
| `identity_oidc_enabled` | false | experimental | security | 0.1.0 | 完成两个受支持 IdP 的 JWKS、撤销和故障切换互操作认证 | 0.3.0 | authentication |

## 治理规则

- 新能力优先加入现有 Profile，不新增布尔开关。
- 实验开关必须同时声明 owner、引入版本、退出条件和最晚删除版本。
- deprecated 开关只用于滚动升级，禁止在新部署模板中默认开启。
- `development/staging/production` 决定安全强度；`CAPABILITY_PROFILE` 决定能力集合。

## 数据库 Schema 运行预算（非 Feature Flag）

| 配置 | 默认值 | 说明 |
|---|---:|---|
| `DATABASE_SCHEMA_SYNC_PAGE_SIZE` | 2000 | 元数据源端每批读取行数，不影响业务 SQL 返回上限 |
| `DATABASE_SCHEMA_SYNC_MAX_TABLES` | 100000 | 单数据源单次同步的表安全预算，达到后显式标记截断 |
| `DATABASE_SCHEMA_SYNC_MAX_COLUMNS` | 1000000 | 单数据源单次同步的列安全预算，达到后显式标记截断 |
| `SCHEMA_ANNOTATION_AUTO_SUGGEST_MAX_ITEMS` | 20000 | 单次同步自动生成的 Schema 业务标注建议安全预算 |
| `RESPONSES_DATA_KNOWLEDGE_CONTEXT_MAX_CHARS` | 12000 | 在线 Text2SQL 草案可注入的已审核数据知识字符预算 |
| `TEXT2SQL_GENERATION_MAX_TOKENS` | 1600 | 复杂 CTE/长 SQL 的单候选输出预算 |
| `TEXT2SQL_SCHEMA_HINT_MAX_CHARS` | 16000 | 查询计划优先排序后可交给 SQL 生成器的 Schema 字符预算 |

这些数值控制不是能力开关。表目录 API 固定采用有界分页响应，不能通过提高同步预算改回一次性
返回完整 Schema；生产调整预算前必须先验证 API 内存、目标数据库元数据查询和 PostgreSQL
`DataSourceSchema` 体积。
