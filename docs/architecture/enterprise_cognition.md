# 企业认知底座

## 定位

OpenTrace 的产品愿景是：**成为最懂公司的企业提问系统**。

“懂公司”不是把员工聊天内容直接当作企业事实，也不是把所有企业文档永久塞进模型提示词。它表示平台能够在严格的租户、工作区、组织、部门、岗位和 Project 边界内，使用经过审核、版本化、可追溯的企业认知理解问题，并在需要事实依据时检索有权限的企业知识或业务数据。

## 认知分层

```text
公司/部门认知实体
  ├─ 稳定身份：entity_type + entity_key
  ├─ 组织绑定：Department → EnterpriseDirectoryPrincipal
  ├─ 知识绑定：Company/Department → KnowledgeSpace
  └─ 生命周期：active / archived

企业认知版本
  ├─ draft → published → archived
  ├─ 简介、使命、愿景、价值观
  ├─ 职责、产品与服务、经营原则
  ├─ 企业术语与关键联系人
  ├─ 来源引用、密级、生效期、失效期、复审日期
  └─ 发布人、发布时间和审计日志

详细企业事实
  └─ KnowledgeSpace → Source → Version → Page / Claim / Relation → Citation

实时业务事实
  └─ 授权 DataSource / Tool → durable execution ledger
```

认知实体只保存稳定、精简、适合上下文装配的企业骨架。制度全文、SOP、产品文档和决策记录继续由企业知识库管理，实时指标继续由 DataAgent 和授权数据源提供，不能把认知版本变成第二套知识或数据事实源。

## 公司与部门语义

- 公司实体在 `tenant_id + workspace_id + org_id` 范围内唯一。
- 部门实体必须绑定当前租户工作区内有效的 `EnterpriseDirectoryPrincipal(department)`。
- 部门可以绑定 `space_type=department` 的知识空间，公司只能绑定 `space_type=company` 的知识空间。
- 员工只能获得其有效部门成员关系及最多八级上级部门的已发布认知。
- 公司认知对当前组织内员工可见，但仍受版本密级与员工 clearance 限制。
- 目录关系回答“员工属于哪里”，认知实体回答“组织是谁、负责什么”，知识空间回答“依据和细节是什么”。三者不能互相替代。

## Responses 主链路

企业认知只进入当前 `/api/v2/responses` Worker 主链路：

```text
平台规则与租户策略
  → 已发布公司/部门认知
  → Project 指令与数据绑定
  → Assistant Profile / 用户指令
  → 会话与回合指令
  → 用户当前输入
```

每轮只装配当前员工有权访问、处于有效期内且密级允许的最新 published 版本。通用问题只注入简介、使命和愿景；涉及公司、部门、制度、流程、职责、口径、战略等问题时补充职责、产品、原则和术语，并确定性启用 RAG。详细结论必须来自绑定知识空间的授权检索并保留引用。

`tool_choice=none` 或 Assistant Profile 禁用 RAG 时不绕过调用方和治理策略。企业认知用于语义理解，不能替代工具授权、写操作审批、数据源 ACL 或持久化幂等账本。

上下文 manifest 保存实体、版本、密级和知识空间 ID，便于审计某次 Response 使用了哪一版企业认知。

## 治理流程

1. 管理员在企业目录中同步部门和员工成员关系。
2. 在企业知识库创建公司或部门知识空间，配置 ACL、密级和发布审核。
3. 在企业运营中心创建认知实体并绑定目录部门与知识空间。
4. 编辑认知草稿；草稿不会进入任何员工问答。
5. 草稿至少包含简介或使命，并且必须绑定知识空间或提供来源引用。
6. 管理员发布后，旧 published 版本在同一事务内归档，新版本进入 Responses 上下文。
7. 到达复审日期、组织职责变化或来源撤回时创建新草稿，不原地篡改历史发布版本。

所有创建、草稿保存和发布动作写入 `AuditLog`。正式结构由 Alembic 管理；staging/production 启动时会校验认知表是否已经迁移。

## API 与产品面

管理员控制面：

- `GET /api/v1/admin/enterprise/cognition/entities`
- `POST /api/v1/admin/enterprise/cognition/entities`
- `PUT /api/v1/admin/enterprise/cognition/entities/{entity_id}/draft`
- `GET /api/v1/admin/enterprise/cognition/entities/{entity_id}/versions`
- `POST /api/v1/admin/enterprise/cognition/entities/{entity_id}/publish`
- `POST /api/v1/admin/enterprise/cognition/entities/{entity_id}/archive`

员工透明投影：

- `GET /api/v2/enterprise-context/current`

管理员在企业大脑页维护公司与部门认知。员工透明 API 只返回当前员工实际可见的认知实体，可
用于解释“AI 当前了解哪些公司与部门信息”，不能用于枚举其他部门的受限信息。

## 典型场景

- 新员工询问公司业务、部门职责、企业术语和协作边界。
- 员工起草方案时自动遵循公司使命、产品定位和经营原则。
- 跨部门问题先确定职责归属，再从对应部门知识空间检索流程依据。
- 问数时以企业术语和指标口径理解问题，以 DataAgent 结果作为实时事实。
- 工具调用时理解员工所属组织和业务语境，但仍执行 ACL、审批和审计。

## 质量指标

“最懂公司”必须通过可观测指标持续验证：

- 公司和部门认知覆盖率、已发布率、到期复审率；
- 企业问题的知识检索触发率、引用覆盖率和有效证据命中率；
- 术语理解正确率、部门职责路由正确率；
- 过期事实率、越权召回率和跨租户泄漏率；
- 任务完成时长、人工澄清次数和人工接管率。

最重要的安全指标是越权召回率必须为零。认知覆盖不足时应显式暴露建设缺口，不能通过扩大检索范围或使用未发布内容伪造“更懂公司”。
