# Production Intelligence 威胁模型

## 边界与保护目标

本模型覆盖 `/api/v2/responses`、Responses Worker、Manager Agent Loop、四类受治理能力、
Connector Gateway、Production Asset Graph、Evidence Ledger、审批和管理控制台。核心目标是：

- 任何外部数据不能改变平台身份、策略或工具目录。
- 任何资源不能跨 user、tenant、workspace、environment 或 classification 边界读写。
- 任何生产副作用不能绕过持久化审批、幂等账本、执行后验证和审计。
- 凭据和原始敏感数据不得进入模型提示、日志、证据摘要或 API 响应。
- 可恢复执行不得因断线、重投、Worker 接管或 Redis 丢失而重复副作用。

## 主要威胁与控制

| 威胁 | 典型路径 | 强制控制 | 剩余风险/运维要求 |
| --- | --- | --- | --- |
| Prompt/Tool Injection | 文档、日志或 MCP 结果要求调用未授权工具 | 可调用能力来自 Manifest 和本地操作白名单；结果只作证据 | 依然需维护高风险提示注入评测集 |
| 跨租户越权 | 猜测 asset/connector/response ID | 服务查询同时绑定 tenant + workspace，Response 再校验 user 与资源范围 | 生产启用 RLS 并由受信代理注入租户上下文 |
| SSRF/DNS Rebinding | 恶意 MCP endpoint 访问 metadata 或内网 | HTTPS、host allowlist、DNS/IP 私网拒绝、禁止重定向；Helm 默认拒绝未声明 egress | 生产使用 egress gateway/FQDN Policy 将应用 allowlist 与网络准入对齐 |
| 凭据泄露 | config 存 token，或 source_ref 带 secret | 只持久化 Secret 引用；敏感 key 拒绝；输出和审计二次脱敏 | Secret Resolver 应使用短时凭据和轮换策略 |
| 操作目录扩权 | MCP 远端新增一个删除工具 | 远端发现不生效；本地 operation spec + allowed_operations 取交集 | 连接器变更需代码评审或管理员复核 |
| 参数注入 | 模型传入未知字段、SQL、URL 或 Shell | 封闭 JSON Schema、服务端可信参数绑定、DataAgent 静态校验 | 适配器仍应调用下游参数化 API |
| 副作用重放 | SSE 断线、Worker 崩溃后重执行回滚 | ResponseApproval + Tool Ledger + 稳定 action ref；终态副作用不重试 | 未知结果必须进 reconciliation，不依靠模型推测 |
| 审批混淆 | 用户批准 A，模型实际执行 B | action ref 来自同一 Response 的 Production Agent 目录；审批后从原始输入重绑参数；破坏性操作持久记录并校验两个不同账号 | 部署方仍需用独立 SRE/Admin 轮值落实职责分离并定期复核审批事实 |
| 伪造证据 | Connector 返回虚假 source_ref/资产 | 证据类型声明、资产范围校验、内容哈希、authority 和时效 | 信任的 Connector 仍是供应链边界，需签名、版本锁定与审计 |
| 敏感数据外泄 | 客服查到完整用户记录 | Capability Policy 按角色输出 masked/summary/aggregate，字段与文本脱敏 | 每个业务 Connector 还需声明资源级 ACL |
| DoS/成本攻击 | 超大输出、慢工具、无限 Agent 循环 | 参数边界、超时、最大输出、最小能力集、步数限制、计量与熔断 | 依据 SLO 调整租户配额与下游限流 |
| 审计篡改 | 修改 Redis 消息或删除客户端事件 | PostgreSQL 是 Response/Event/Approval/Ledger 事实源；Redis 只投递 | 需数据库不可变备份、最小 DBA 权限和保留策略 |
| 扩展供应链 | 恶意 Python 包注册 Native Adapter | 仅启动期加载已安装包中显式 allowlist 的 entry point；冲突/缺失失败关闭 | 固定版本、签名、SBOM、漏洞扫描与镜像准入 |

## 信任边界

```text
用户终端
  → 受信身份代理 / API Gateway
  → PostgreSQL 持久化命令
  → Responses Worker / Model Gateway
  → Governed Connector Gateway
  → egress proxy / 外部 MCP、SDK、REST、RPC
```

外部连接器返回值、RAG 文档、数据库文本和模型输出均是不可信数据。它们可以成为
Evidence，但不能成为身份、策略、审批或工具目录的事实源。

## 发布前安全证据

1. 租户/工作区越权、资产跨范围连边、Response 范围不匹配的反向测试。
2. MCP SSRF、私网 IP、DNS 解析、重定向、超时、过大输出和敏感引用测试。
3. 写操作未审批、非法 action ref、断线恢复、重复投递和缺验证证据测试。
4. 真实主链 Golden Dataset 的安全拒绝率和错误归因率报告。
5. 生产 egress、Vault/KMS、RLS、备份恢复、审计保留和应急操作演练记录。
