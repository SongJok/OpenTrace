# MCP、A2A 与企业连接器

- MCP Client 默认要求 HTTPS、租户工具 allowlist、写/破坏操作审批回调和持久化幂等账本。
- MCP Server 与 A2A 开关默认关闭；暴露能力时不得直接调用 provider 或绕过 Responses Worker。
- A2A 信封绑定 tenant/workspace、sender/recipient/task，并使用服务身份密钥签名。
- GitHub、Slack、Confluence 连接器统一返回游标、ACL、版本、删除列表和 checkpoint；同步任务必须
  持久化游标、对账 observed/deleted 数量，并将 ACL 投影到知识库资源权限。
- 连接器 OAuth 密钥通过 Vault/KMS 注入环境变量，不写入数据库或镜像；数据库只保存加密后的用户凭据。
