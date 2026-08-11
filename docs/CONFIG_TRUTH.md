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

## 数据库 Schema 元数据

| 变量 | 默认值 | 说明 |
|------|-------:|------|
| `DATABASE_SCHEMA_SYNC_PAGE_SIZE` | `2000` | Schema 同步访问目标数据库时的每批行数 |
| `DATABASE_SCHEMA_SYNC_MAX_TABLES` | `100000` | 单次同步表安全预算，达到后返回 `tables_truncated=true` |
| `DATABASE_SCHEMA_SYNC_MAX_COLUMNS` | `1000000` | 单次同步列安全预算，达到后返回 `columns_truncated=true` |
| `SCHEMA_ANNOTATION_AUTO_SUGGEST_MAX_ITEMS` | `20000` | 单次 Schema 同步最多生成的表/字段业务标注建议数 |

Schema 同步不得复用 `DATA_AGENT_MAX_RESULT_ROWS=500`：后者只保护业务查询结果。同步端按批次读取
元数据，目录 API 默认每页返回 100 张表、最多 200 张，并支持 `search`、`database`、`offset`
和 `limit`；前端通过“继续加载”渐进展示。达到同步安全预算时统计是下限，API 和页面必须保留
明确告警。

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

## Skills

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

`staging` 与 `production` 会强制关闭动态 Skill 安装、创建、进程内执行和子进程执行。Knowledge Worker 启动时会检测公共 Skill 本地镜像，仅在没有可用 Skill 时立即补齐一次，并按 `SKILLHUB_SYNC_TIMEZONE` 每天 06:30 下载更新到共享本地镜像；API 和 Skills 页面只读取该镜像，不在用户请求中访问 GitHub 或 SkillHub。Docker Compose 会先修复共享卷权限，再启动 API 与 Worker；页面会在首次同步期间自动刷新。公司 Skill 由管理员蒸馏时写入同一共享卷下的租户/工作区隔离目录。生产部署应为 `skills/catalog_mirror` 配置 API/Worker 共享持久卷。

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
| `RESPONSES_DATA_KNOWLEDGE_CONTEXT_MAX_CHARS` | `12000` | DataAgent 草案中 Schema 标注、指标、关系与 SQL 资产知识的总字符预算 |
| `DATA_AGENT_GENERATION_MAX_TOKENS` | `1600` | SQL 候选最大输出 token；用于避免复杂 SQL 被截断 |
| `DATA_AGENT_SCHEMA_HINT_MAX_CHARS` | `16000` | QueryPlan 命中表优先排序后的 Schema 提示预算 |
| `DATA_AGENT_PROFILE_SAMPLE_ROWS` | `1000` | 每张表用于语义和质量提示的有界样本行数，不代表全表分布 |
| `DATA_AGENT_PROFILE_MAX_TABLES` | `50` | 单次画像刷新的表数上限 |
| `DATA_AGENT_PROFILE_MAX_COLUMNS_PER_TABLE` | `100` | 单表画像字段数上限 |
| `DATA_AGENT_PROFILE_TTL_HOURS` | `24` | 画像有效期；过期画像不进入在线证据包 |
| `DATA_AGENT_PREFLIGHT_REQUIRED` | `true` | 数据库 EXPLAIN 失败时是否阻止执行 |
| `DATA_AGENT_PREFLIGHT_TIMEOUT_MS` | `15000` | EXPLAIN 超时预算 |
| `DATA_AGENT_PREFLIGHT_MAX_ESTIMATED_ROWS` | `10000000` | 预计扫描行数门禁 |
| `DATA_AGENT_PREFLIGHT_MAX_ESTIMATED_BYTES` | `1073741824` | 预计扫描字节门禁 |
| `DATA_AGENT_SOURCE_RESOLUTION_ENABLED` | `true` | 多数据源时允许依据认证指标、语义、血缘和 trusted 经验自动选择 |
| `DATA_AGENT_SOURCE_MIN_SCORE` | `0.25` | 自动选源的最低企业证据评分 |
| `DATA_AGENT_SOURCE_AMBIGUITY_DELTA` | `0.08` | 前两名评分接近时进入澄清的差值阈值 |
| `DATA_AGENT_LEARNING_ENABLED` | `true` | 保存受完整 Scope 和版本约束的执行经验；不修改治理资产 |
| `DATA_AGENT_LEARNING_TRUST_MIN_SUCCESS` | `2` | observed 晋升 trusted 所需成功次数 |
| `DATA_AGENT_LEARNING_MIN_CONFIDENCE` | `0.85` | 经验记录和晋升所需最低逻辑计划置信度 |
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

镜像构建基础镜像由 `PYTHON_BASE_IMAGE`、`FRONTEND_NODE_BASE_IMAGE` 和
`FRONTEND_NGINX_BASE_IMAGE` 控制，默认使用国内 Docker 镜像代理；依赖源由
`PYTHON_DEPENDENCY_INDEX_URL`、`PYTHON_DEPENDENCY_FALLBACK_INDEX_URL` 和 `NPM_REGISTRY` 控制。
Python 依赖使用固定版本 `uv`
安装，BuildKit 会复用 `/root/.cache/uv`。两个 Python 镜像源按顺序独立尝试，不再把官方 PyPI
作为并列 extra index，避免国内服务器反复等待 `files.pythonhosted.org`。主源和备用源的整次
安装时限分别由 `PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS` 和
`PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS` 控制；`UV_CONCURRENT_*` 默认限制小规格服务器上的
下载、安装和构建并发。uv 引导层独立缓存，主源会在
`UV_BOOTSTRAP_PRIMARY_MAX_SECONDS` 后快速切换国内备用源。旧的 `PIP_INDEX_URL` 和
`PIP_EXTRA_INDEX_URL`、`UV_HTTP_TIMEOUT` 和 `UV_HTTP_RETRIES` 不再参与应用镜像构建，已有
`.env` 无需手工删除这些字段。备用源整层默认重试两次，并复用 BuildKit 的 uv 缓存，单个
CDN 文件偶发超时时不会直接导致整个镜像构建失败。
前端镜像会跨构建复用 npm 下载缓存，并对瞬时网络中断自动重试；受限网络可通过
`.env` 覆盖 `NPM_REGISTRY`，不要修改依赖锁文件中的完整性校验。

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

Helm Secret 使用三条独立连接：`API_DATABASE_URL`、`WORKER_DATABASE_URL`、
`MIGRATION_DATABASE_URL`。API/Worker 角色不得是表 owner 或 superuser；角色初始化见
`deploy/postgres_roles.sql`。
