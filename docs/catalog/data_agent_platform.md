# DataAgent 企业数据问答与 SQL 编译平台

OpenTrace 的 DataAgent 主路径现在由独立的 `data_agent/` 领域包提供。OpenTrace Gateway 仅负责身份、租户范围、数据源授权和适配器注入。

## 主流程

```text
问题 + DataScope
  -> ResearchPlanner 选择证据类型
  -> EvidenceProvider 读取 Schema、数据源策略、指标、关系、SQL 资产、流程、知识、技能和数据质量
  -> LogicalPlanner 生成 LogicalQueryPlan
  -> SQLGenerator 生成 1-N 个候选
  -> SQLGuard AST / 表列范围 / 指标覆盖 / JOIN / 敏感字段校验
  -> ExecutionPolicy 决定 SQL-only、澄清、确认或阻止
  -> 重新校验 Schema、执行数据库 EXPLAIN 后只读执行
  -> 返回 SQL、结果、截断状态、答案、证据和完整轨迹
```

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/v1/data-agent/queries` | 研究、规划、生成 SQL；`mode=execute_and_answer` 仍需 `confirmed=true`，可通过 `Idempotency-Key` 安全重试 |
| GET | `/api/v1/data-agent/queries/{run_id}?data_source_id=...&project_id=...` | 读取带完整 Scope 的查询运行记录 |
| POST | `/api/v1/data-agent/queries/{run_id}/execute?data_source_id=...&project_id=...` | 重新校验 Schema 后执行选定候选 |
| POST/GET | `/api/v1/data-agent/semantic-assets` | 创建或查询业务规则、政策、报表、血缘、质量和实体草案 |
| POST | `/api/v1/data-agent/semantic-assets/{id}/publish` | 管理员发布治理资产 |
| POST/GET | `/api/v1/data-agent/profiles/refresh` / `profiles` | 刷新或读取有界真实数据画像 |
| POST | `/api/v1/data-agent/evaluation-cases` | 保存冻结数据快照上的 Golden Case |
| POST | `/api/v1/data-agent/evaluation-cases/{id}/evaluate` | 运行 SQL 与结果回归 |
| POST | `/api/v1/data-agent/queries/{run_id}/feedback?data_source_id=...&project_id=...` | 保存用户反馈，不自动晋升知识 |

## 证据和权威级别

执行前必须保留 `source_id`、`authority`、`version`、`scope` 和 `citation`。权威顺序为：

1. 实时 Schema、权限和数据质量；
2. 已发布指标、字段语义和已验证关系；
3. 已验证 SQL 资产和 Golden Case；
4. 企业流程和知识库；
5. 未验证历史 SQL 或模型推断。

历史 SQL 只作为参考，具体日期、ID 和普通过滤值不得直接复用。`SQLAsset` 只以同一租户、工作区、数据源和当前 Schema 可证明合法的已发布查询进入检索。

## 执行安全

- 只允许单条 `SELECT/WITH`，拒绝写操作、DDL、多语句、注释和越权表。
- 所有候选在执行前强制经过 AST、表列范围、指标契约和 JOIN 校验。
- `source_policy` 治理资产可禁止 SQL 生成、禁止执行或要求额外审批。
- 执行接口必须显式确认；敏感字段、未验证关系或阻断型数据质量问题不能自动执行。
- 执行前重新收集证据；Schema 指纹变化时阻止旧候选执行。
- 查询创建支持 `Idempotency-Key`；同一完整 Scope 和 key 返回同一运行记录，复用到不同问题会返回冲突。
- 结果报告 `returned_rows`、`total_rows`、`truncated` 和 `snapshot_id`，截断结果不能被描述为完整结果。

## 数据治理资产

平台复用已有的 `MetricDefinition`、`SchemaMetadata`、`SchemaTableMetadata`、`TableRelationship`、`SQLAsset` 和 `AnalyticalSkill`，并新增：

- `data_agent_semantic_assets`：业务过程、数据质量、实体、维度和来源策略；
- `data_agent_evaluation_cases`：问题、逻辑计划、期望 SQL、期望结果和 Schema 指纹；
- `data_agent_runs`：问题、证据、计划、候选、策略、EXPLAIN 预检、结果校验和答案；
- `data_agent_run_events`：阶段化审计事件；
- `data_agent_feedback`：用户纠错和结果反馈；
- `data_agent_profiles`：有界真实样本生成的表级和字段级画像。

历史 `r0020`、`r0021` 保持冻结；`r0022_unify_data_agent_platform` 将持久化表统一迁移到
`data_agent_*` 命名并补充画像、预检、结果验证和草案关联字段。

完整数据来源、可靠性标准和实施顺序见 [DataAgent 企业问数平台](data_agent.md)。
