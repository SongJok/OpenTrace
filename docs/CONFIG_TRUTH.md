# OpenTrace — 配置真相表

避免 `.env`、Compose、前端与脚本之间的端口/主机不一致。

## API 与前端

| 项 | 权威值 | 说明 |
|----|--------|------|
| API 监听端口 | **14100** | `APP_PORT`、`docker-compose` api 映射、`start.sh` 健康检查 |
| Swagger | `http://localhost:14100/docs` | |
| 前端 dev | **14108** | `FRONTEND_PORT` / Vite |
| `VITE_API_URL` | `http://localhost:14100` | 浏览器访问宿主机 API |

**已废弃/易混淆**：`.env` 中的 `GATEWAY_PORT=14101` 若存在，**不参与**当前 Dockerfile/Compose/健康检查；请勿将 `preflight` 或前端指向 14101，除非全栈已同步改端口。`development` 会给出 warning；`staging` / `production` 中 `GATEWAY_PORT != APP_PORT` 会启动失败。

## 数据与缓存（Docker 网络 vs 宿主机）

| 场景 | `DATABASE_URL` / `TOKEN_DB_URL` | `REDIS_URL` |
|------|-------------------------------|-------------|
| 容器内 api/worker | `postgresql://...@postgres:5432/opentrace_v2` | `redis://redis:6379/10` |
| 宿主机 `uvicorn` | `...@127.0.0.1:5432/...` | `redis://127.0.0.1:6380/10`（Compose 默认 `6380:6379`） |

## RAG 阈值

| 变量 | 定义位置 | 说明 |
|------|----------|------|
| `RAG_MIN_EVIDENCE_SCORE` | `settings.rag_min_evidence_score` | 证据门禁（默认 0.65） |
| `RAG_MIN_SCORE` | 仅部分遗留代码 | **未**在 `settings.py` 定义；新配置请用 `RAG_MIN_EVIDENCE_SCORE` |

## 知识编排

| 变量 | 定义位置 | 说明 |
|------|----------|------|
| `KNOWLEDGE_ORCHESTRATION_ENABLED` | `settings.knowledge_orchestration_enabled` | 是否启用受治理知识主链 |
| `KNOWLEDGE_QUERY_ENABLED` | `settings.knowledge_query_enabled` | 是否启用 Knowledge Query lane |
| `KNOWLEDGE_AUTO_COMPILE_ENABLED` | `settings.knowledge_auto_compile_enabled` | 文档就绪后是否提交编译任务 |
| `KNOWLEDGE_AUTO_PUBLISH` | `settings.knowledge_auto_publish` | 确定性编译结果是否自动发布 |
| `KNOWLEDGE_MAX_RELATION_HOPS` | `settings.knowledge_max_relation_hops` | 关系查询最大跳数 |
| `KNOWLEDGE_QUERY_CANDIDATE_BUDGET` | `settings.knowledge_query_candidate_budget` | 单次知识查询候选上限 |
| `KNOWLEDGE_STALE_AFTER_DAYS` | `settings.knowledge_stale_after_days` | 默认 stale 判定周期 |
| `KNOWLEDGE_JOB_POLL_SECONDS` | `agents.worker` 环境变量 | 持久化编译队列轮询间隔 |
| `KNOWLEDGE_JOB_RECLAIM_MINUTES` | `agents.worker` 环境变量 | 崩溃 worker 任务回收阈值 |

## LLM 配置组命名

规划模型环境变量前缀为 `DEFAULT_LLM_PLANING_*`（项目内固定拼写 `PLANING`，非 PLANNING）。

## 密钥

- 所有 `*_API_KEY`、`SMTP_PASS`、`APP_SECRET_KEY` 仅放在 `.env` 或密钥管理系统。
- `staging` / `production` 必须显式配置非占位的 `APP_SECRET_KEY`、`JWT_SECRET`、`DATA_SECRET_KEY`；启用 `ENTERPRISE_TENANT_RLS_ENABLED` 时还必须配置 `TRUSTED_TENANT_HEADER_SECRET`，缺失会在配置加载时失败。
- 文档与 README 只使用占位符 `<your-*>`。

## Schema 与迁移

- `development` 启动时允许 `ensure_runtime_schema()` 做本地兼容性 DDL 修复。
- `staging` / `production` 启动时只做只读 schema readiness 校验；缺少 Alembic 迁移会启动失败，请先执行 `alembic upgrade head`。

## 健康检查 `orchestrator` 字段

`/health/deps` 与 `/health/runtime` 固定报告 `responses-agent-loop`。V4 开关与回退实现已删除。

## Docker 代码生效

镜像通过 `COPY . .` 打入代码；若改 Python 后容器行为未变：

```bash
bash restart.sh --build
```
