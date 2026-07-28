# 版本与发布流程

1. 从 `main` 创建候选 Tag `vX.Y.Z-rc.N`，执行完整 CI、Golden Dataset、真实 PostgreSQL 迁移、
   Helm lint、容量、故障注入、备份恢复和安全扫描。
2. 由非作者 CODEOWNER 复核安全、迁移与回滚证据；GitHub branch protection 必须要求两人批准。
3. 生产变更先 canary 5%，观察一个完整 SLO 窗口，再扩至 25%/50%/100%。
4. 正式 Tag `vX.Y.Z` 触发镜像、SBOM 与 provenance；Release Notes 包含 migration、flag、已知风险。
5. 回滚只回滚应用镜像；不可逆数据迁移必须使用 expand/contract，禁止直接 downgrade 破坏生产数据。
