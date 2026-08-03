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
| `SKILLS_GIT_INSTALL_ENABLED` | `false` | 兼容字段；外部 Git 即时安装入口已停用，第三方 Skill 统一由后台镜像同步 |
| `SKILLHUB_SYNC_ENABLED` | `true` | 是否启用公共 Skill 本地镜像同步 |
| `SKILLHUB_SYNC_HOUR` / `SKILLHUB_SYNC_MINUTE` | `6` / `30` | 每日本地镜像同步时间 |
| `SKILLHUB_SYNC_TIMEZONE` | `Asia/Shanghai` | 每日同步计划使用的时区 |
| `SKILLHUB_SYNC_RETRY_SECONDS` | `60` | 同步失败后的重试间隔 |
| `SKILLHUB_SYNC_DOWNLOAD_CONCURRENCY` | `8` | 后台下载 Skill 文件的最大并发 |
| `SKILLHUB_LOCAL_MIRROR_DIR` | `skills/catalog_mirror` | API 与 Worker 共享的本地 Skill 镜像目录 |
| `SKILLHUB_CATALOG_URL` | `https://skills.palebluedot.live` | 兼容 `/api/skills` 的目录来源，可替换为其他 SkillHub |
| `SKILLHUB_GITHUB_TOKEN` | 空 | 仅后台同步读取 GitHub 时使用，不进入用户安装请求链路 |
| `SKILLS_LOCAL_CREATE_ENABLED` | `false` | 是否允许管理员在平台创建动态 Skill |
| `SKILLS_SUBPROCESS_EXECUTION_ENABLED` | `false` | 是否允许受限子进程执行 Python Skill |
| `SKILLS_EXECUTION_TIMEOUT_SECONDS` | `10` | 单次动态 Skill 执行超时（最大 60 秒） |
| `ALERT_SCHEDULER_POLL_SECONDS` | `10` | Worker 扫描到期预警规则的周期 |
| `ALERT_SCHEDULER_RETRY_SECONDS` | `60` | 主动预警查询失败后的恢复重试间隔 |

`staging` 与 `production` 会强制关闭动态 Skill 安装、创建、进程内执行和子进程执行。公共 Skill 由 Knowledge Worker 启动时补齐，并按 `SKILLHUB_SYNC_TIMEZONE` 每天 06:30 下载到共享本地镜像；Skills 页面和安装接口只读取该镜像，不在用户请求中访问 GitHub 或 SkillHub。公司 Skill 由管理员蒸馏时写入同一共享卷下的租户/工作区隔离目录。生产部署应为 `skills/catalog_mirror` 配置 API/Worker 共享持久卷。

## LLM 配置组命名与用户模型选择

规划模型环境变量前缀为 `DEFAULT_LLM_PLANING_*`（项目内固定拼写 `PLANING`，非 PLANNING）。

设置页只展示一个系统内置的通用免费模型源，以及当前用户自己添加的模型。选择与自定义模型按 `user_id + tenant_id + workspace_id` 隔离；自定义 API Key 使用 `DATA_SECRET_KEY` 派生密钥加密落库，不通过 API 回显。未做选择时默认使用 `FREE_LLM_MODEL1`。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FREE_LLM_MINSHORT_PROVIDER` | `通用免费模型` | 设置页中的内置模型源名称 |
| `FREE_LLM_MINSHORT_BASE_URL` | `https://coding-api-3671.underpinetree.com` | 通用免费模型的 OpenAI-compatible Base URL |
| `FREE_LLM_MINSHORT_API_KEY` | 空 | 服务端共享密钥，不下发到浏览器 |
| `FREE_LLM_MINSHORT_API_MODE` | `chat_completions` | `auto`、`responses` 或 `chat_completions` |
| `FREE_LLM_MODEL1` | `glm-5.2-free` | 默认免费模型 |
| `FREE_LLM_MODEL2` | `deepseek-v4-pro-free` | 第二个可选免费模型 |
| `DYNAMIC_LLM_ALLOW_PRIVATE_BASE_URLS` | `false` | 是否允许动态 Base URL 指向 localhost、私网或保留 IP；生产环境不建议开启 |

选中的免费或自定义模型接管规划、路由、压缩、知识问答和主回答等文本角色；Vision/Omni 仍使用专用环境配置，避免将多模态请求误发到普通文本端点。未包含路径的 OpenAI-compatible Base URL 会自动补全 `/v1`。运行中的 Response 固定使用领取时解析出的配置，新建或重试的 Response 才读取最新设置。`DEFAULT_LLM_*` 与 `OTHER_LLM_*` 仅保留为内部角色和旧部署兼容配置，不再作为用户可选模型展示。

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

## 企业运行时与数据面

| 变量 | 生产要求 | 说明 |
|---|---|---|
| `OBJECT_STORAGE_BACKEND` | `local` 或 `s3`，禁止 `database` | 图片/音视频原始字节不再写 PostgreSQL |
| `IDENTITY_OIDC_ENABLED` | 按企业 IdP 开启 | 开启时 issuer/audience/JWKS 必填；SAML 经企业 OIDC bridge 接入 |
| `ENTERPRISE_TOKEN_REVOCATION_ENABLED` | `true` | JWT `jti` 撤销；改密递增 token version |
| `WORKER_ROLE` | 独立部署四类池 | `responses` / `agents` / `knowledge` / `scheduler` |
| `RESPONSE_WORKER_CONCURRENCY` | 容量测试后设定 | 单 Worker 全局并发 |
| `RESPONSE_WORKER_TENANT_CONCURRENCY` | 按租户公平性设定 | 单租户并发上限 |
| `RESPONSE_WORKER_MAX_QUEUE_DEPTH` | 与 SLO 告警一致 | 达阈值停止 Outbox 扩散，由 DB claim 排空 |
| `MCP_SERVER_ENABLED` / `A2A_PROTOCOL_ENABLED` | 默认关闭、灰度开启 | 调用必须转换为 durable Response，不得旁路审批和账本 |

### 钉钉企业数据接入

| 变量 | 权威值 / 默认 | 说明 |
|---|---|---|
| `DINGTALK_DWS_BINARY` | 空（禁用） | 运行时挂载的 `dws` Linux 可执行文件绝对路径；API 仅以参数数组执行只读命令，不经过 shell |
| `DINGTALK_DWS_PROFILE` | 空 | 运维预配置的只读企业 Profile / corpId；生产禁止挂载个人高权限 Profile |
| `DINGTALK_DWS_TIMEOUT_SECONDS` | `30` | 单条读取命令超时，运行时限制在 5–120 秒 |
| `DWS_CONFIG_DIR` | Compose: `/var/lib/opentrace/dws` | OAuth 加密凭据与恢复事件的持久化目录 |
| `DWS_CLIENT_ID` / `DWS_CLIENT_SECRET` | 空 | Headless 环境的钉钉 AppKey/AppSecret；使用 Secret 注入，不写入镜像 |

钉钉文档和群聊先进入持久化知识同步队列，再由 Worker 编译；部门和成员关系进入企业目录并投影到知识 ACL。群聊默认按 `confidential` 处理并保留群主体 ACL。生产应把版本固定的 DWS Linux 二进制以只读文件挂载，把 Profile 作为 Secret/持久卷挂载；不要让核心应用镜像构建依赖外部 CLI 下载服务。

Helm Secret 使用三条独立连接：`API_DATABASE_URL`、`WORKER_DATABASE_URL`、
`MIGRATION_DATABASE_URL`。API/Worker 角色不得是表 owner 或 superuser；角色初始化见
`deploy/postgres_roles.sql`。
