# 版本与发布流程

1. 从 `main` 创建候选 Tag `vX.Y.Z-rc.N`，执行完整 CI、Golden Dataset、真实 PostgreSQL 迁移、
   Helm lint、[端到端容量门禁](runbooks/responses_capacity.md)、故障注入、备份恢复和安全扫描。
   Golden Results 与 72 小时内的容量报告必须绑定同一个干净候选提交；HTTP 2xx 入队结果不
   得作为完成率或端到端性能证据。
2. 由非作者 CODEOWNER 复核安全、迁移与回滚证据；GitHub branch protection 必须要求两人批准。
3. 生产变更先 canary 5%，观察一个完整 SLO 窗口，再扩至 25%/50%/100%。
4. 正式 Tag `vX.Y.Z` 触发镜像、OCI SBOM、BuildKit provenance、GitHub/Sigstore attestation
   和 Cosign keyless digest 签名；工作流会立即验证签名，并将不可变 `image@sha256` 引用附加到
   Release。Release Notes 包含 migration、flag、已知风险。
5. 回滚只回滚应用镜像；不可逆数据迁移必须使用 expand/contract，禁止直接 downgrade 破坏生产数据。
