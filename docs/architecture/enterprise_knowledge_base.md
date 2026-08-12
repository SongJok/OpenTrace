# OpenTrace 企业知识库架构

> 状态：受控企业 Beta。知识编排是内部控制面，企业知识库是员工产品面；两者共享 PostgreSQL 事实源，不维护第二套知识事实。

## 目标主链

```text
我的资料投稿
  → Document + KnowledgeSource / SourceVersion
  → durable compile job
  → Page / Claim / Relation
  → Lint / ACL / 有效期 / 密级 / 版本差异
  → Review Task
  → Active Published Version
  → 企业知识搜索 / RAG / 工作区 / Agent
  → 反馈、复审、撤回和重新投稿
```

## 产品与控制面分工

| 产品面 | 用户 | 职责 |
|---|---|---|
| 我的资料 `/documents` | 全体员工 | 原始文件、个人检索资料，以及向知识空间投稿的唯一上传入口 |
| 企业知识库 `/knowledge-base` | 管理员 | 搜索、浏览空间、查看已发布资产和来源状态、发起知识投稿 |
| 知识库质量中心 `/knowledge` | 管理员 | 编排策略、关系图、任务、审核、质量和空间授权 |
| Responses/RAG | Agent | 在统一权限范围内检索 Page、Claim、Relation 和原文证据 |

产品层必须保持以下边界：

- `Document` 是原始内容事实，不等于已发布企业知识；
- `KnowledgeSource` 是稳定治理身份，更新文件应生成新 Source Version；
- `KnowledgePage/Claim/Relation` 是派生资产，不能脱离 Source Version 成为第二套事实；
- 员工端不直接操作编译 Job、Review 决策或空间 ACL；
- 企业知识版本只能通过 Review Task 决策发布，兼容 Page Publish API 仅用于非空间个人知识；
- 已进入企业知识生命周期的 Document 不能物理删除，必须先撤回 Source 并保留审计链。

## 治理边界

`KnowledgeSpace` 独立于临时会话。公司、部门、岗位、工作区和个人空间长期存在；员工查询在工作区与空间授权范围内使用对应知识，短期会话结束不会删除企业知识。

公司和部门知识空间可以绑定到[企业认知实体](enterprise_cognition.md)。认知实体只保存适合每轮装配的稳定骨架，知识空间继续保存有来源、版本、ACL 和 citation 的详细事实；二者不能复制维护同一份全文内容。

空间角色依次为 `viewer → contributor → reviewer → publisher → admin`。授权主体支持用户、部门、用户组和岗位；`KnowledgePrincipalMembership` 可由 SCIM/HR 同步。来源系统 ACL 写入 `KnowledgeSourcePermission`，查询权限是空间访问权与来源 ACL 的交集。

密级为 `public → internal → confidential → restricted`。查询在召回前过滤密级、租户、工作区、空间、来源 ACL、有效期和撤回状态；Session 热证据也必须重新授权。

## 来源与编排

企业知识的唯一交互式摄入入口是“我的资料”。用户选择目标知识空间投稿后，系统保留原始
`Document`，创建稳定的 `KnowledgeSource` 和新的 Source Version，再由持久化编译任务生成
Page、Claim 与 Relation。API 请求内不执行分块、Embedding 或编译；后台 Worker 负责领取任务，
失败任务可回收并保留可追溯状态。

修改资料会生成新 Source Version，撤回则归档活动版本和派生资产，不能让旧索引继续可见。
质量中心只提供编排策略、审核、质量检查、复审、合并和空间授权，不再提供外部连接器或同步运行面板。

## 发布与复审

企业空间默认 `review`：编译完成后生成 `KnowledgeReviewTask`，publisher 才能发布。发布会归档旧 Active Version，统一切换 Page/Claim/Relation 状态并设置下一复审日期。个人空间可配置 `auto`。

来源撤回后设置 `deleted_at` 和 `sync_status=deleted`，归档活动版本和派生资产。有效期到期、密级不足、ACL 不匹配或已撤回的来源不能进入查询候选。

## 兼容策略

历史个人文档可以保持 `space_id=NULL`，继续按 `owner_id` 访问。新企业知识应进入 Knowledge Space；迁移过程不修改已冻结历史迁移。
