# 企业身份目录与运营控制面

## 目标

OpenTrace 的企业权限不能长期依赖管理员手工填写不可解释的主体 ID。第二阶段引入持久化企业目录，使部门、用户组和岗位成为可审计、可同步、可失效的企业事实，并自动复用到知识空间 ACL。

企业运营中心则把 Responses、ModelCall、Goal、数据源、知识、预警和目录状态聚合为租户工作区级运营视图。它是 PostgreSQL 事实状态的只读投影，不是第二套运行时或计费账本。

## 企业目录模型

```text
EnterpriseDirectoryPrincipal
  ├─ department
  ├─ group
  └─ role

EnterpriseDirectoryMembership
  └─ User → Principal

EnterpriseDirectorySyncRun
  └─ provider / cursor / authoritative / stats / audit

KnowledgePrincipalMembership
  └─ 目录成员关系的知识 ACL 投影
```

目录主体使用 `(tenant_id, workspace_id, principal_type, external_id)` 作为稳定唯一键；成员关系使用 `(tenant_id, workspace_id, user_id, principal_id)` 作为唯一键。

## 同步语义

`POST /api/v1/admin/enterprise/directory/sync` 支持：

- `manual`：管理员或内部系统增量维护。
- `scim`：标准身份目录同步。
- `hr`：企业 HR 主数据同步。
- 增量模式：只更新请求中出现的主体和成员。
- 权威模式：同一 provider 中未再次出现的主体和成员自动失效。
- 未注册、未激活员工不会被隐式创建或授权，而是计入 `unresolved_users`。
- 同一租户、工作区和 provider 使用 PostgreSQL advisory lock 串行同步。
- 同步记录、处理统计和知识 ACL 投影在同一数据库事务内完成。

目录凭据和 SCIM Token 不进入同步请求或目录表。生产适配器应只传递已经过网关认证和解密后的标准化快照。

## 运营中心

`GET /api/v1/admin/enterprise/operations/overview` 聚合：

- 30 天活跃员工、Goal、定时任务和主动预警采用情况。
- 24 小时 Response 成功率、失败、待操作和模型调用。
- ModelCall Token、平均延迟和 P95 延迟。
- 企业数据源、知识空间、发布知识、到期复审、反馈积压。
- 企业目录主体、成员数量和最近一次同步结果。
- 待审批、关键预警、失败执行和知识治理风险。

所有指标强制限定当前经过签名验证的 `tenant_id` 与 `workspace_id`。前端 `/enterprise-admin` 只向管理员展示，但后端管理员依赖仍是最终权限边界。

## 后续扩展

1. 标准 SCIM 2.0 `/Users`、`/Groups` 协议适配器与增量游标。
2. HR 主数据字段映射、离职即时失权和组织树变更审批。
3. 目录同步凭据接入 KMS/Vault，并建立轮换和失败通知。
4. 运营指标时序化、部门采用漏斗、成本预算与 SLA 告警。
5. 企业级职责分离：身份管理员、知识管理员、安全审计员和平台运营员。
