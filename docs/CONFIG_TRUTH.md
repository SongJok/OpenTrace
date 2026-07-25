# OpenTrace — 配置真相表

避免 `.env`、Compose、前端与脚本之间的端口/主机不一致。

## API 与前端

| 项 | 权威值 | 说明 |
|----|--------|------|
| API 监听端口 | **14100** | `APP_PORT`、`docker-compose` api 映射、`start.sh` 健康检查 |
| Swagger | `http://localhost:14100/docs` | |
| 生产前端 | **14108** | `FRONTEND_PORT` / Compose `frontend`（Nginx） |
| 前端 dev | **14108** | 仅本地 HMR；需先停止 Compose `frontend`，由 Vite 占用端口 |
| `VITE_API_URL` | `http://localhost:14100` | 仅本地 Vite 开发模式的直连回退；生产环境优先同源 `/api` Nginx 反代 |

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
| `KNOWLEDGE_SYNC_BATCH_SIZE` | `settings.knowledge_sync_batch_size` | 单轮连接器 Snapshot 领取上限 |
| `KNOWLEDGE_SYNC_RECLAIM_MINUTES` | `settings.knowledge_sync_reclaim_minutes` | 同步 Worker 崩溃后的运行项回收阈值 |
| `KNOWLEDGE_SYNC_MAX_ATTEMPTS` | `settings.knowledge_sync_max_attempts` | 单个 Snapshot 显式重试前的最大尝试次数 |

## Skills 与主动预警

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SKILLS_GIT_INSTALL_ENABLED` | `false` | 是否允许管理员从 Git 安装动态 Skill |
| `SKILLS_LOCAL_CREATE_ENABLED` | `false` | 是否允许管理员在平台创建动态 Skill |
| `SKILLS_SUBPROCESS_EXECUTION_ENABLED` | `false` | 是否允许受限子进程执行 Python Skill |
| `SKILLS_EXECUTION_TIMEOUT_SECONDS` | `10` | 单次动态 Skill 执行超时（最大 60 秒） |
| `ALERT_SCHEDULER_POLL_SECONDS` | `10` | Worker 扫描到期预警规则的周期 |
| `ALERT_SCHEDULER_RETRY_SECONDS` | `60` | 主动预警查询失败后的恢复重试间隔 |

`staging` 与 `production` 会强制关闭动态 Skill 安装、创建、进程内执行和子进程执行。生产部署应把第三方 Skill 放入独立容器/微虚机，并增加网络出口、密钥和文件系统策略；仓库内子进程运行器只用于显式开启的开发环境。

## LLM 配置组命名

规划模型环境变量前缀为 `DEFAULT_LLM_PLANING_*`（项目内固定拼写 `PLANING`，非 PLANNING）。

## Responses Agent Loop 预算

以下配置只作用于当前在线 `/api/v2/responses → Worker → AgentLoop` 主链；旧内核的
`CONTEXT_WINDOW_MAX_TOKENS` 不控制在线对话。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEFAULT_LLM_OMNI_MODEL` | `qwen3.5-omni-flash` | 音频/视频原生理解模型；复用 Query role 的 Provider 凭据 |
| `RESPONSES_CONTEXT_WINDOW_TOKENS` | `131072` | 文本、媒体估算、工具 schema 共用的输入窗口 |
| `RESPONSES_CONTEXT_OUTPUT_RESERVE_TOKENS` | `8192` | 为模型输出预留的 token |
| `RESPONSES_SUMMARY_TRIGGER_TOKENS` | `48000` | 持久会话摘要的 token 触发阈值 |
| `RESPONSES_CAPABILITY_CATALOG_LIMIT` | `48` | 大型工具生态中交给规划器的相关能力上限；调用方显式工具始终保留 |
| `RESPONSES_AGENT_DEEP_MAX_ROUNDS` | `16` | deep/complex 任务单个 Response 的最大工具轮次 |
| `RESPONSES_AGENT_REPLAN_LIMIT` | `3` | 只读工具失败后的最大重规划次数 |
| `MULTIMODAL_INLINE_MAX_MB` | `7` | Base64 音视频上传上限，编码后保持在 Provider 10MB 限制内 |

每轮实际上下文用量、裁剪数、摘要命中、媒体数量和工具 schema 估算会写入
`opentrace.context.ready.manifest` 及最终 Response metadata。

Agent Loop 会把重复工具参数、重复有效结果、连续失败和无结果识别为“无进展”。连续两轮
无进展时写入 `opentrace.loop.no_progress`，停止继续调用工具，并执行一次禁用工具的最终
合成；终止原因和成功/失败工具计数写入 `loop_termination`。只有持续产生新结果仍未完成的
请求才会触发 `max_tool_rounds`。两轮熔断值是防止成本失控和错误自激的运行时安全约束，
不通过环境变量放宽。

## 密钥

- 所有 `*_API_KEY`、`SMTP_PASS`、`APP_SECRET_KEY` 仅放在 `.env` 或密钥管理系统。
- `staging` / `production` 必须显式配置非占位的 `APP_SECRET_KEY`、`JWT_SECRET`、`DATA_SECRET_KEY`；启用 `ENTERPRISE_TENANT_RLS_ENABLED` 时还必须配置 `TRUSTED_TENANT_HEADER_SECRET`，缺失会在配置加载时失败。
- 文档与 README 只使用占位符 `<your-*>`。

## Schema 与迁移

- `development` 启动时允许 `ensure_runtime_schema()` 做本地兼容性 DDL 修复。
- `staging` / `production` 启动时只做只读 schema readiness 校验；缺少 Alembic 迁移会启动失败，请先执行 `alembic upgrade head`。
- `user_memory_relations` 是记忆关系图事实来源；Redis Memory Fabric 只能作为加速投影，不能替代该表。

## 健康检查 `orchestrator` 字段

`/health/deps` 与 `/health/runtime` 固定报告 `responses-agent-loop`。V4 开关与回退实现已删除。

## Docker 代码生效

镜像通过 `COPY . .` 打入代码；若改 Python 后容器行为未变：

```bash
bash restart.sh --build
```

## P0 配置收敛

- 产品只支持 `development`、`staging`、`production` 三种环境 Profile。
- 内置 Agent 只支持 `core`、`data`、`knowledge`、`data_knowledge` 四种 `CAPABILITY_PROFILE`。
- 公开高影响布尔开关以 `infra/config/flag_registry.py` 为准；实验开关缺 owner、引入版本、退出条件或最晚删除版本时 CI 失败。
- 旧 Cognitive Runtime 细粒度字段继续兼容读取，但不进入 `.env.example` 的推荐配置面。

## P0 迁移创建流程

```bash
python scripts/create_migration.py add_response_trace_id --release unreleased
# 完成 upgrade/downgrade 内容后冻结校验和
python scripts/freeze_migration.py r0001_add_response_trace_id
python scripts/check_migration_policy.py
```

已提交迁移（包括文件名为 2026-07-25 至 2026-08-03 的历史文件）不重命名、不改写。新 revision 使用 `rNNNN_slug`，发布信息单独记录在 `alembic/revision_releases.json`。
