# OpenTrace 企业知识库架构

> 状态：Alpha。知识编排是内部控制面，企业知识库是员工产品面；两者共享 PostgreSQL 事实源，不维护第二套知识事实。

## 目标主链

```text
企业文档/知识系统/代码仓库/业务系统
  → KnowledgeConnector（游标、凭据引用、同步状态）
  → KnowledgeSyncRun + KnowledgeSyncItem（API 仅持久化，HTTP 202）
  → Sync Worker 行锁领取、文档摄入、Source/ACL 落库
  → durable compile job
  → Page / Claim / Relation
  → Lint / ACL / 有效期 / 密级 / 版本差异
  → Review Task
  → Active Published Version
  → 企业知识搜索 / RAG / Project / Agent
  → 反馈、复审、撤回和再次同步
```

## 产品与控制面分工

| 产品面 | 用户 | 职责 |
|---|---|---|
| 我的资料 `/documents` | 全体员工 | 原始文件、个人/Project 检索资料，以及向知识空间投稿的唯一上传入口 |
| 企业知识库 `/knowledge-base` | 全体员工 | 搜索、浏览空间、查看已发布资产和来源状态、发起知识投稿 |
| 知识治理中心 `/knowledge` | Owner/Steward/Reviewer | 编排规则、关系图、任务、审核、连接器、同步、质量和空间授权 |
| Responses/RAG | Agent | 在统一权限范围内检索 Page、Claim、Relation 和原文证据 |

产品层必须保持以下边界：

- `Document` 是原始内容事实，不等于已发布企业知识；
- `KnowledgeSource` 是稳定治理身份，更新文件应生成新 Source Version；
- `KnowledgePage/Claim/Relation` 是派生资产，不能脱离 Source Version 成为第二套事实；
- 员工端不直接操作编译 Job、Connector Cursor、Review 决策或空间 ACL；
- 企业知识版本只能通过 Review Task 决策发布，兼容 Page Publish API 仅用于非空间个人知识；
- 已进入企业知识生命周期的 Document 不能物理删除，必须先撤回 Source 并保留审计链。

## 治理边界

`KnowledgeSpace` 独立于 Project。公司、部门、岗位、个人空间长期存在；Project 通过 `KnowledgeSpaceProject` 挂载空间。员工查询可以使用公司/部门/岗位空间以及当前 Project 挂载空间，Project 结束不会删除企业知识。

空间角色依次为 `viewer → contributor → reviewer → publisher → admin`。授权主体支持用户、部门、用户组、岗位和 Project；`KnowledgePrincipalMembership` 可由 SCIM/HR 同步。来源系统 ACL 写入 `KnowledgeSourcePermission`，查询权限是空间访问权与来源 ACL 的交集。

密级为 `public → internal → confidential → restricted`。查询在召回前过滤密级、租户、工作区、空间、来源 ACL、有效期和撤回状态；Session 热证据也必须重新授权。

## 来源与同步

连接器只保存 `credential_ref`，不把密钥写入知识表。同步协议支持：

- 增量 cursor；
- 内容哈希去重；
- 来源 ACL 快照；
- 修改生成新 Document/Source Version；
- 删除转为 withdraw/tombstone，不直接让旧索引继续可见；
- 同步 Run 记录 queued/running/succeeded/failed 和 created/updated/unchanged/deleted；
- API 请求内不执行分块、Embedding 或编译，只返回 `202 Accepted`；
- Worker 使用 `FOR UPDATE SKIP LOCKED` 领取同步项，失联项可回收，耗尽尝试次数后终止为 failed；
- 同一连接器按 Run 顺序推进，前置失败批次会阻塞后续批次，避免 cursor 回退或跨增量漏数；
- 只有整批 Snapshot 成功才推进 cursor，失败项可在治理端查看错误并显式重试；
- `batch_hash` 在状态聚合时保留，用于 pending/running/succeeded 批次幂等去重。

当前提供通用 Push 接口作为 SharePoint、Confluence、钉钉、Git 等连接器的稳定落点。具体连接器只负责把外部增量事件规范化为 Snapshot，不得直接写 KnowledgePage。治理端可查看 Run 与 Item 状态、展开错误明细，并对失败项重新入队。

## 发布与复审

企业空间默认 `review`：编译完成后生成 `KnowledgeReviewTask`，publisher 才能发布。发布会归档旧 Active Version，统一切换 Page/Claim/Relation 状态并设置下一复审日期。个人空间可配置 `auto`。

来源撤回后设置 `deleted_at` 和 `sync_status=deleted`，归档活动版本和派生资产。有效期到期、密级不足、ACL 不匹配或已撤回的来源不能进入查询候选。

## 兼容策略

历史个人文档与 Project 知识可以保持 `space_id=NULL`，继续按 `owner_id + project_id` 访问。新企业知识应进入 Knowledge Space；迁移过程不修改已冻结历史迁移。
