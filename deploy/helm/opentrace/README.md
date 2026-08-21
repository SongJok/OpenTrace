# OpenTrace Helm Chart

Chart 只部署无状态 API、Worker 和迁移 Job；生产 PostgreSQL、Redis、对象存储、KMS/Vault 与
OTel Collector 应使用托管或独立高可用服务。敏感配置必须来自 `secret.existingSecret`，不得写入
values 文件。升级顺序为：备份 → pre-upgrade migration Job → API/Worker 滚动更新 → SLO 验证。

生产部署必须设置 `image.digest=sha256:...`；Chart 拒绝 `production` 环境仅使用 tag，也在所有
环境拒绝 `latest`。Ingress
启用时必须配置 TLS。NetworkPolicy 默认拒绝未声明流量，并分别限制运行时与迁移 Job：集群内
DNS、PostgreSQL、Redis 和 OTel 通过非空 namespace/pod selector 准入，托管服务通过专用 CIDR
列表准入。模型、对象存储与 Connector 的 HTTPS 出站必须写入 `externalHttpsRanges`，例如：

```yaml
networkPolicy:
  externalHttpsRanges:
    - cidr: 0.0.0.0/0
      except:
        - 10.0.0.0/8
        - 100.64.0.0/10
        - 127.0.0.0/8
        - 169.254.0.0/16
        - 172.16.0.0/12
        - 192.168.0.0/16
```

更严格的生产集群应通过 egress gateway 或支持 FQDN Policy 的 CNI 只放行已准入域名；应用层
Connector host allowlist、DNS/IP 校验与禁止重定向仍必须同时启用，NetworkPolicy 不能替代它们。
