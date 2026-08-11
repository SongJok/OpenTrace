# DataAgent 企业问数平台

DataAgent 是 OpenTrace 唯一的企业问数产品与领域概念。SQL 生成只是其中一个编译阶段，
不再单独暴露 Text2SQL、NL2SQL、V1 或 V2 产品入口。

## 目标

平台优先保证口径、粒度、时间、权限和结果完整性正确，允许单次请求更慢。每次查询必须：

1. 在授权的租户、工作区、Project 和数据源范围内研究证据；
2. 明确业务场景、指标定义、统计粒度、时间字段、时间区间、维度和固有过滤；
3. 证据不足、版本冲突或 JOIN 未验证时先澄清，不猜测执行；
4. 生成可审计的逻辑计划和候选 SQL；
5. 通过静态校验、Schema 重检、数据库 EXPLAIN 和只读执行门禁；
6. 校验空结果、截断、异常值、数据质量和历史基线后再生成答案。

## 统一在线链路

```text
/api/v2/responses 或数据库 Query 页面
  -> services.sql_assets.generate_sql_query_draft
  -> DataAgentRun 持久化事实源
  -> ResearchPlanner 选择证据
  -> OpenTraceEvidenceProvider 收集当前 Scope 内的证据
  -> LogicalPlanner 解析场景、指标、实体、粒度、时间和关系
  -> DeterministicSQLCompiler 优先编译可完全证明的常见指标查询
  -> OpenTraceSQLGenerator 为复杂查询生成受证据约束的候选
  -> SQLGuard 校验 AST、表列范围、指标覆盖、时间边界和 JOIN
  -> SQLQueryDraft 投影为现有前端确认执行界面
  -> 用户显式确认
  -> Schema 与语义版本重检
  -> 数据库 EXPLAIN 成本预检
  -> 只读执行
  -> ResultValidator 校验完整性、质量和历史基线
  -> 答案、证据、预检、结果校验和事件轨迹持久化
```

`agents/data_agent.py` 只进入上述治理草案链路。`agents/data_agent_v2/` 和
`DataAgentV1` 只保留为离线兼容及架构合约组件，不属于在线产品能力。

## 数据来源与权威顺序

### 已接入的核心来源

| 来源 | 用途 | 使用约束 |
| --- | --- | --- |
| 实时数据库 Schema | 证明表、字段和方言真实存在 | 当前数据源事实，执行前重新采集 |
| 有界真实数据画像 | 推断时间、枚举、维度、数值分布和空值情况 | 仅作语义与质量提示，不代表全表精确分布 |
| 已发布指标 | 公式、底层字段、时间字段、粒度、固有过滤、版本和 Owner | 优先确定性编译；按查询时间选择有效版本 |
| 已验证表关系 | JOIN 键、方向、基数和放大风险 | 多表查询缺少完整验证路径时先澄清 |
| 已发布历史 SQL 资产 | 需求、指标、结构模式和已验证过滤参考 | 不复制固定日期、ID 或已过期物理结构 |
| 业务规则、政策、流程、报表和血缘资产 | 解释业务场景、排除条件、可信表和口径变化 | 必须带版本、有效期、Owner 和引用 |
| 企业知识 Claims 与分析 Skills | 业务实现逻辑和分析方法 | 只能补充计划，不能绕过 SQLGuard |
| 同 Scope 历史执行记忆 | 结果基线、计划和失败经验 | 只用于异常提示，不直接复用旧 SQL 执行 |

### 建议继续引入的数据来源

以下来源会显著提高大型企业中的准确率，建议按优先级接入：

1. **dbt/DataWorks/Airflow/ETL 血缘**：补齐事实表、汇总表、字段转换和刷新周期。
2. **BI 报表与看板元数据**：引入已被业务长期使用的指标、过滤器、维度和报表 Owner。
3. **数据库约束、索引和查询统计**：利用 PK/FK、唯一约束、索引、行数和慢查询估计 JOIN 基数与成本。
4. **主数据和码表**：统一组织、渠道、区域、商品、客户、状态码及历史拉链版本。
5. **数据质量与可观测性平台**：接入新鲜度、完整性、唯一性、分布漂移和事故窗口。
6. **需求单、报表说明和验收记录**：将历史 SQL 与原始需求、指标名称、统计周期和验收结论绑定。
7. **权限与数据分类分级目录**：提供字段级脱敏、用途限制、导出限制和审批策略。
8. **Golden Case 冻结快照**：保存问题、计划、SQL、结果和 Schema 指纹，作为发布门禁。

历史 SQL 没有需求说明、执行成功证据或验收结论时，只能进入 `quarantine` 或
`evaluation` 语料，不能自动晋升为治理口径。

## 缺少 Schema 注释时的处理

真实数据库经常只有物理字段名。平台采用分层补全，不让模型直接把猜测当事实：

1. 同步物理 Schema、数据库 COMMENT、PK/FK 和类型；
2. 对有界真实样本生成脱敏画像，识别时间、枚举、标识符、金额、维度和指标候选；
3. 从历史 SQL 提取表使用、JOIN、过滤、聚合和需求标签；
4. 从 Skills、知识文档、报表和血缘中生成字段与表的业务标注建议；
5. 由 Owner 审核后发布 `SchemaMetadata`、`SchemaTableMetadata`、指标和关系；
6. 未审核建议保持 inferred/suggested，不能获得 governed 权威级别。

敏感字段画像不保存样例值和 Top Values。画像使用有界顺序样本，页面和 API 必须明确其
抽样偏差。

## 指标与业务规则

一个可执行的企业指标至少包含：

- 唯一名称与别名；
- 业务定义、Owner、业务域和单位；
- SQL 公式与聚合类型；
- 底层字段；
- 唯一统计时间字段；
- 默认粒度；
- 固有过滤和排除条件；
- 版本、有效起止时间和发布状态。

同一统计周期存在重叠且内容冲突的已治理指标或规则时，逻辑计划进入
`needs_clarification`。历史查询按绝对时间选择当时有效的版本，而不是总取最新版本。

## SQL 生成与校验

常见聚合、趋势和排名优先由确定性语义编译器生成。同比、环比、漏斗、留存、复杂窗口和
多阶段分析可由模型生成候选，但必须受同一逻辑计划和证据包约束。

所有候选统一执行以下检查：

- 单条只读 `SELECT/WITH`，拒绝 DDL、DML、锁和多语句；
- 表、字段和数据源 Scope 真实存在；
- 指标底层字段、聚合、`COUNT DISTINCT` 和固有过滤完整；
- 时间字段和绝对起止边界完整；
- 维度聚合包含 `GROUP BY`；
- JOIN 使用已验证关系，未验证关系不能自动执行；
- 敏感字段仅在 SQL 实际引用时触发高风险门禁；
- 自动添加或收紧 `LIMIT`，并保留截断语义。

## 执行与结果可靠性

执行前重新采集 Schema 和治理证据。Schema 指纹变化时旧候选作废。数据库原生
`EXPLAIN` 失败或预计扫描行数、字节数超过预算时阻止执行。

执行器使用只读事务、超时、返回行数上限和数据源级权限。执行后验证：

- 执行器行数与实际行数一致；
- 是否达到返回上限；
- 空结果是否可能由时间、过滤或新鲜度造成；
- 治理字段空值率是否超限；
- 正数指标是否出现异常负值；
- 当前单值结果是否与同 Scope 历史基线显著偏离。

阻断级结果校验失败时不生成业务答案，避免把已知不可靠结果包装成确定事实。

## 持久化事实源

| 模型 | 作用 |
| --- | --- |
| `data_agent_runs` | 请求、证据、计划、候选、策略、预检、结果、校验和答案 |
| `data_agent_run_events` | 顺序化阶段事件和审计轨迹 |
| `data_agent_semantic_assets` | 业务过程、规则、政策、报表、血缘、质量和来源策略 |
| `data_agent_profiles` | 表级与字段级有界数据画像 |
| `data_agent_evaluation_cases` | Golden Case 和冻结结果 |
| `data_agent_feedback` | 用户纠错，不自动晋升治理知识 |
| `sql_query_drafts` | 现有 UI 的确认执行投影，通过 `data_agent_run_id` 关联事实源 |

PostgreSQL 是事实来源。草案状态不能代替 DataAgentRun 的证据、预检和结果校验记录。

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/v1/data-agent/queries` | 创建治理运行并生成候选 |
| GET | `/api/v1/data-agent/queries/{run_id}` | 读取完整 Scope 内的运行记录 |
| POST | `/api/v1/data-agent/queries/{run_id}/execute` | 显式确认后执行 |
| POST/GET | `/api/v1/data-agent/semantic-assets` | 创建或查询治理资产 |
| POST | `/api/v1/data-agent/semantic-assets/{id}/publish` | 管理员发布治理资产 |
| POST/GET | `/api/v1/data-agent/profiles/refresh` / `profiles` | 刷新或读取数据画像 |
| POST | `/api/v1/data-agent/evaluation-cases` | 创建 Golden Case |
| POST | `/api/v1/data-agent/evaluation-cases/{id}/evaluate` | 运行 SQL/结果回归 |
| POST | `/api/v1/data-agent/queries/{run_id}/feedback` | 保存结构化反馈 |

`/api/v2/responses`、`/api/v1/data/query` 和数据库 Query 页面都通过
`services.sql_assets.generate_sql_query_draft()` 进入同一治理运行。

## 配置

公开配置统一使用 `DATA_AGENT_*`：

- `DATA_AGENT_ENABLED`
- `DATA_AGENT_MAX_RESULT_ROWS`
- `DATA_AGENT_STATEMENT_TIMEOUT_MS`
- `DATA_AGENT_GENERATION_MAX_TOKENS`
- `DATA_AGENT_SCHEMA_HINT_MAX_CHARS`
- `DATA_AGENT_PROFILE_*`
- `DATA_AGENT_PREFLIGHT_*`

旧 `TEXT2SQL_*` 仅作为环境变量兼容别名，不属于新部署推荐配置面。旧
`DATA_AGENT_V2_*` 只服务离线兼容组件，不控制在线 DataAgent。

## 评测与发布门禁

至少按业务域维护以下集合：

- 单表查询、多表指标、复杂时间、同比环比、排名、漏斗、留存；
- 指标版本切换、规则版本切换、Schema 漂移和数据延迟；
- 错误 JOIN、缺少固有过滤、错误时间字段、敏感字段和越权 Scope；
- 空结果、截断、异常值、EXPLAIN 超预算和执行失败恢复。

发布指标应同时观察：逻辑计划正确率、可执行 SQL 正确率、结果一致率、澄清命中率、
越权率、敏感字段误放行率、Schema 漂移阻断率和 P95 延迟。准确率未达标的业务域应保持
SQL-only 或必须确认模式，不能通过降低校验阈值换取表面成功率。

## 实施顺序

1. 先完成数据源授权、Schema 同步、画像和敏感字段治理；
2. 导入历史 SQL，并补齐需求、指标、Owner、业务域和验收状态；
3. 发布高频核心指标、时间字段和固有过滤；
4. 验证高频 JOIN 与基数，接入血缘、BI 报表和质量平台；
5. 为每个业务域建立 Golden Case 和回放数据；
6. 先 SQL-only，再确认执行，最后只对高置信、低风险场景开放自动回答。

速度优化只能发生在证据可复现之后，例如缓存 Schema、语义版本和 EXPLAIN 结果；任何缓存
命中都必须绑定完整 Scope、Schema 指纹和语义版本。
