# Tenant RLS — Staging 上线检查清单

## 前置

1. **单 head**：`python -m alembic heads` 应只输出一个 revision（`20260611_billing_invoice` 或后续）。
2. 若出现多 head，先执行仓库内 merge revision（`20260610_merge_heads`），再 `alembic upgrade head`。

## Staging（真实 Postgres）

```bash
export DATABASE_URL=postgresql://...   # staging 实例，勿用生产
export APP_ENV=staging
export APP_SECRET_KEY=...
export JWT_SECRET=...
export DATA_SECRET_KEY=...
export ENTERPRISE_TENANT_RLS_ENABLED=true

python -m alembic upgrade head
```

应用启动时只做只读 schema readiness 校验；如果 `tenants`、`tenant_workspaces`、`compliance_audit_events` 或关键租户列缺失，API 应启动失败而不是自动修表。

验证：

```sql
SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'tenants';
SELECT policyname FROM pg_policies WHERE tablename = 'tenants';
```

应用侧写入租户前需 `set_config('app.tenant_id', ...)`（见 `tenant/tenant_rls.set_session_tenant`）。

## 生产

- 仅在 staging 全量契约 + 手工隔离测试通过后开启 `ENTERPRISE_TENANT_RLS_ENABLED`。
- 禁止依赖 `TenantManager` 内存 fallback 作为唯一租户源（`require_tenant_persist` 在 production 为 true 时应有 DB 行）。

## Billing 表

`20260611_billing_invoice` 创建 `billing_ledger` / `billing_invoices`。  
回合收尾经 `finalize_turn` → `record_turn_billing` → 可选 `persist_ledger_entry`。  
对账：`BillingManager.persist_snapshot_as_invoice(tenant_id)`。

## 生产角色分离

生产禁止 API/Worker 使用表 owner 或 superuser。使用 `deploy/postgres_roles.sql` 创建独立
`opentrace_api`、`opentrace_worker` 与 `opentrace_migration`，Helm Secret 分别提供
`API_DATABASE_URL`、`WORKER_DATABASE_URL`、`MIGRATION_DATABASE_URL`。发布门禁执行
`scripts/verify_tenant_rls_postgres.py`，必须证明 tenant-a 无法读取 tenant-b。
