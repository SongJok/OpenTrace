# OpenTrace Helm Chart

Chart 只部署无状态 API、Worker 和迁移 Job；生产 PostgreSQL、Redis、对象存储、KMS/Vault 与
OTel Collector 应使用托管或独立高可用服务。敏感配置必须来自 `secret.existingSecret`，不得写入
values 文件。升级顺序为：备份 → pre-upgrade migration Job → API/Worker 滚动更新 → SLO 验证。
