# OpenTrace — 高影响 Feature Flag 注册表

> 产品成熟度：**受控企业 Beta**。能力组合优先使用 `CAPABILITY_PROFILE`；本表只保留少量紧急熔断、迁移与实验例外。旧 Cognitive Runtime 细粒度字段仅兼容读取，不属于产品配置面。

## 能力 Profile（默认组合不超过 5 套）

| Profile | 内置 Agent | 用途 |
|---|---|---|
| `core` | 无专家 Agent | 仅 Manager 模型问答 |
| `data` | data | DataAgent |
| `knowledge` | rag | 企业知识 RAG |
| `data_knowledge` | data + rag | 默认提问闭环 |
| `production_intelligence` | production + data + config + rag | 企业生产智能平台（默认） |

## 公开高影响开关（自动生成）

| Flag | 默认 | 阶段 | Owner | 引入版本 | 退出条件 | 最晚删除版本 | 影响面 | 依赖 |
|---|---:|---|---|---|---|---|---|---|
| `kernel_runtime_phase_transition_strict` | true | stable | runtime | 0.1.0 | — | — | responses-runtime | — |
| `kernel_registry_dispatch_strict` | true | stable | runtime | 0.1.0 | — | — | tool-dispatch | — |
| `kernel_runtime_replay_enabled` | true | stable | observability | 0.1.0 | — | — | audit-replay | — |
| `kernel_agent_runtime_v3_strict` | false | stable | agent-runtime | 0.1.0 | — | — | agent-contribution-contract | kernel_agent_runtime_v3_enabled |
| `kernel_agent_learning_auto_apply` | false | experimental | agent-quality | 0.1.0 | 连续两个 Beta 发布中通过回放评测且无越权策略写入 | 0.3.0 | learning | kernel_capability_intelligence_enabled |
| `enterprise_tenant_rls_enabled` | false | experimental | security | 0.1.0 | 核心事实表 RLS 与跨租户负向测试全部进入发布门禁 | 0.3.0 | tenant-isolation | — |
| `data_agent_source_resolution_enabled` | true | stable | data-platform | 0.2.0 | — | — | data-agent-source-resolution | — |
| `data_agent_learning_enabled` | true | experimental | data-platform | 0.2.0 | 核心业务域 Golden Case 连续两个发布周期无错误晋升或跨 Scope 复用 | 0.4.0 | data-agent-governed-learning | — |

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
| `RESPONSES_DATA_KNOWLEDGE_CONTEXT_MAX_CHARS` | 12000 | 在线 DataAgent 草案可注入的已审核数据知识字符预算 |
| `DATA_AGENT_GENERATION_MAX_TOKENS` | 1600 | 复杂 CTE/长 SQL 的单候选输出预算 |
| `DATA_AGENT_SCHEMA_HINT_MAX_CHARS` | 16000 | 查询计划优先排序后可交给 SQL 生成器的 Schema 字符预算 |
| `DATA_AGENT_PROFILE_SAMPLE_ROWS` | 1000 | 单表有界真实数据画像的最大样本行数 |
| `DATA_AGENT_PROFILE_TTL_HOURS` | 24 | 画像进入过期状态前的有效小时数 |
| `DATA_AGENT_PREFLIGHT_MAX_ESTIMATED_ROWS` | 10000000 | EXPLAIN 预计扫描行数上限 |
| `DATA_AGENT_PREFLIGHT_MAX_ESTIMATED_BYTES` | 1073741824 | EXPLAIN 预计扫描字节数上限 |
| `DATA_AGENT_SOURCE_MIN_SCORE` | 0.25 | 多数据源自动选择的最低企业证据评分 |
| `DATA_AGENT_SOURCE_AMBIGUITY_DELTA` | 0.08 | 前两名评分差低于该值时要求用户澄清 |
| `DATA_AGENT_LEARNING_TRUST_MIN_SUCCESS` | 2 | 执行经验晋升 trusted 前所需成功次数 |
| `DATA_AGENT_LEARNING_MIN_CONFIDENCE` | 0.85 | 执行经验进入学习和晋升的最低计划置信度 |
| `RAG_LANE_TIMEOUT_SECONDS` | 5 | 知识、文档、LLMWiki 和记忆单次检索的最长等待秒数 |
| `CONNECTOR_ADAPTER_ENTRYPOINTS` | 空 | 已安装 Connector Adapter 的启动期供应链 allowlist；不是在线功能开关 |
| `CONNECTOR_SECRET_RESOLVER_ENTRYPOINT` | 空 | 内置 MCP 的单一 Secret Resolver allowlist；不是在线功能开关 |
| `OPENTRACE_RELEASE_REVISION` | `unknown` | 构建期注入且只读投影的源码修订；用于发布证据绑定，不是运行时能力开关 |

这些数值控制不是能力开关。表目录 API 固定采用有界分页响应，不能通过提高同步预算改回一次性
返回完整 Schema；生产调整预算前必须先验证 API 内存、目标数据库元数据查询和 PostgreSQL
`DataSourceSchema` 体积。
