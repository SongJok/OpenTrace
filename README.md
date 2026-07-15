# OpenTrace

OpenTrace 是一个以 Responses API 和可恢复 Agent Loop 为核心的智能工作平台，把对话、RAG、工具调用、数据分析、记忆、Goal、定时任务、审批和运行时观测组织成统一产品。

本 README 依据当前仓库代码、`docker-compose.yml`、启动脚本和 `.env` 重新整理。`.env` 中包含真实密钥、数据库密码、SMTP 授权码和第三方 API Key，本文档只记录配置项与脱敏示例，不写入真实敏感值。

## 当前能力

- FastAPI API Gateway；聊天统一使用 `/api/v2/responses`，旧 `/api/v1/chat` 返回 `410 Gone`。
- **统一主路径**：PostgreSQL Response/Items/Events → Outbox → Redis Streams → 无状态 Worker → Context Assembler → Manager Agent Loop。
- GPT-5.6 优先的模型路由、严格类型化工具、专家 Agent 内部编排、写操作审批和断线续传。
- Redis Agent Bus，当前 `.env` 启用 `KERNEL_AGENT_BUS_ENABLED=true`，模式为 `stream`。
- 多模型 LLM 路由，OpenAI GPT-5.6 优先，Qwen 作为配置化兼容与降级模型。
- RAG 增强链路，包含 Query Rewrite、HyDE、混合检索、Rerank、证据质量门禁和 Web fallback。
- DataAgent V2，用于 Text2SQL、指标语义、表关系、分析技能、结果解释和高级分析。
- 多轮分支会话、Projects、Assistant Profiles、自动记忆、Goal、Scheduled Tasks、审计、技能、连接器和文档 API。
- OpenTelemetry、Prometheus、Jaeger 可选观测栈。
- React + Vite 前端，默认独立运行在 `14108`。

### Responses Agent Loop 架构

切换、回填与回滚流程见 `docs/runbooks/chatgpt_cutover.md`。

```text
Responses API → PostgreSQL + Outbox → Redis Streams → Agent Worker
  → ContextAssembler → IntentPlan → Manager Agent Loop
  → typed tools / expert agents → durable events → resumable SSE
  → run_outcomes (Artifact, GoalEvidenceBinding, semantic_alerts)
```

```bash
bash scripts/run_vnext_final_tests.sh
```

## 快速启动

### 前置依赖

| 组件 | 建议版本 | 说明 |
| --- | --- | --- |
| Docker | 24+ | 默认运行方式 |
| Docker Compose | 2.20+ | 服务编排 |
| Python | 3.11+ | 本地开发或容器镜像 |
| Node.js | 18+ | 前端开发 |
| npm | 9+ | 前端依赖管理 |

### 1. 准备环境变量

首次启动时复制模板并填写真实值：

```bash
cp .env.example .env
```

当前 `.env` 是运行时配置源。至少需要确认这些配置存在：

```env
POSTGRES_PASSWORD=<your-postgres-password>
DATABASE_URL=postgresql://postgres:<your-postgres-password>@postgres:5432/opentrace_v2
TOKEN_DB_URL=postgresql://postgres:<your-postgres-password>@postgres:5432/opentrace_v2
REDIS_URL=redis://redis:6379/10

APP_PORT=14100
VITE_API_URL=http://localhost:14100
FRONTEND_PORT=14108
APP_SECRET_KEY=<your-app-secret>
JWT_SECRET=<your-jwt-secret>
DATA_SECRET_KEY=<your-data-secret>

DASHSCOPE_API_KEY=<your-dashscope-key>
DEFAULT_LLM_QUERY_API_KEY=<your-dashscope-key>
EMBEDDING_API_KEY=<your-dashscope-key>
RERANK_API_KEY=<your-dashscope-key>

SERPER_API_KEY=<optional-web-search-key>
WEATHER_API_KEY=<optional-weather-key>
WEATHER_STACK_API_KEY=<optional-weatherstack-key>
```

不要提交 `.env`。如果 `.env` 曾经被分享或进入日志，请轮换其中的数据库密码、SMTP 授权码和第三方 API Key。

### 2. 启动后端栈

```bash
bash start.sh
```

启动脚本会检查 Docker、Compose、`.env`、端口 `14100`，然后构建并启动：

- `opentrace_api`
- `opentrace_agent_worker`
- `opentrace_postgres`
- `opentrace_redis`

验证：

```bash
curl http://127.0.0.1:14100/api/v1/health
curl http://127.0.0.1:14100/api/v1/health/deps
```

带观测组件启动：

```bash
bash start.sh --with-observability
```

启动后额外可用：

- Prometheus: `http://localhost:14190`
- Jaeger: `http://localhost:14186`

启动并执行 Docker 快速验收：

```bash
bash start.sh --verify
```

### 3. 启动前端

`docker-compose.yml` 当前不包含前端服务。前端使用 Vite 本地启动：

```bash
cd frontend
npm install
npm run dev
```

访问：

- 前端: `http://localhost:14108`
- API: `http://localhost:14100`
- Swagger: `http://localhost:14100/docs`

## 服务端口

| 服务 | 宿主机地址 | 容器/内部地址 | 说明 |
| --- | --- | --- | --- |
| API Gateway | `http://localhost:14100` | `api:14100` | FastAPI 主入口 |
| Swagger Docs | `http://localhost:14100/docs` | - | OpenAPI 文档 |
| Frontend | `http://localhost:14108` | - | Vite dev server |
| PostgreSQL | `localhost:5432` | `postgres:5432` | 默认数据库 `opentrace_v2` |
| Redis | `localhost:6380` | `redis:6379` | Compose 默认映射 `${REDIS_PORT:-6380}:6379` |
| Prometheus | `http://localhost:14190` | `prometheus:9090` | `--with-observability` 启用 |
| Jaeger | `http://localhost:14186` | `jaeger:16686` | `--with-observability` 启用 |

**端口真相**：API 以 **`APP_PORT=14100`** 为准（Compose、`start.sh`、健康检查、`VITE_API_URL`）。若 `.env` 中 `GATEWAY_PORT` 与 `APP_PORT` 不一致，开发环境启动时会收到警告；详见 `docs/CONFIG_TRUTH.md`。

**改代码后容器行为未变**：镜像 `COPY` 打入代码，需强制重建：

```bash
docker compose build --no-cache api agent-worker && bash restart.sh
```

## 常用命令

```bash
# 启动
bash start.sh

# 启动后端 + Prometheus + Jaeger
bash start.sh --with-observability

# 停止容器，保留数据卷
bash stop.sh

# 停止容器并删除数据卷
bash stop.sh --volumes

# 重启
bash restart.sh

# 查看日志
bash scripts/docker_logs.sh api
bash scripts/docker_logs.sh agent-worker

# Docker 快速验收
bash scripts/verify_docker.sh

# Docker 完整验证
bash scripts/verify_all_docker.sh
```

## 配置说明

OpenTrace 通过 `infra/config/settings.py` 使用 `pydantic-settings` 读取 `.env`，大小写不敏感，额外字段会被忽略。数据库 DSN 如果写成 `postgresql://`，配置层会自动转换为 asyncpg 使用的 `postgresql+asyncpg://`。

### 当前 `.env` 摘要

| 类别 | 当前配置含义 |
| --- | --- |
| App | `APP_NAME=opentrace`，`APP_ENV=development`，`APP_PORT=14100`，`DEBUG=true` |
| Database | PostgreSQL，数据库名 `opentrace_v2`，容器内主机名 `postgres` |
| Redis | 容器内 `redis:6379/10`，DB `10-15` 分别用于 session/cache/memory/queue/rate-limit/pubsub |
| LLM | OpenAI GPT-5.6 为 auto/deep/fast 首选；Qwen 为配置化降级 |
| Short Models | SeniorShort `qwen3-14b`，MiddleShort/JuniorShort/MinShort 当前配置为 `qwen3-8b` |
| Embedding | DashScope `qwen3-vl-embedding`，维度 `1024` |
| Rerank | DashScope `qwen3-vl-rerank` |
| Search/Weather | Serper、OpenWeatherMap、Weatherstack 通过对应 API Key 启用 |
| Auth | JWT `HS256`，默认过期 `10080` 分钟 |
| Registration | 注册开启，允许邮箱域名和管理员邮箱由 `.env` 控制 |
| SMTP | 使用 `.env` 中的 SMTP 服务发送邮件 |
| Trace | `TRACE_ENABLED=true`，OTLP 默认指向 `http://localhost:4317` |
| Runtime | Responses Agent Loop；PostgreSQL 为事实来源，Redis Streams 仅投递 |
| Agent Bus | 启用 Redis Agent Bus，当前模式为 `stream` |
| RAG | Query Rewrite、HyDE、Hybrid Search、Rerank、Fallback to Web 均开启 |
| Text2SQL | Join inference、结果解释和最多 2 次重试开启 |
| DataAgent V2 | 当前启用，高级分析模式为 `auto` |

### LLM 配置组

项目把模型按用途拆成多组，便于按成本和延迟路由：

| 配置前缀 | 用途 |
| --- | --- |
| `DEFAULT_LLM_STRONGEST_*` | 最强模型，复杂推理或高质量任务 |
| `DEFAULT_LLM_QUERY_*` | 主问答模型 |
| `DEFAULT_LLM_COMPRESS_*` | 上下文压缩 |
| `DEFAULT_LLM_PLANING_*` | 计划生成，变量名沿用项目内 `PLANING` 拼写 |
| `DEFAULT_LLM_SENIORSHORT_*` | 知识问答、轻量 critique |
| `DEFAULT_LLM_MIDDLESHORT_*` | 简单问答、FAQ、快速回答 |
| `DEFAULT_LLM_JUNIORSHORT_*` | L1 路由、轻量分类 |
| `DEFAULT_LLM_MINSHORT_*` | 预留轻量模型 |
| `DEFAULT_LLM_VISION_*` | 视觉理解，代码中有默认值，当前 `.env` 未显式配置 |

所有 `*_API_KEY` 请只写在 `.env` 或安全的密钥管理系统里。

### RAG 与检索

当前 `.env` 开启：

```env
RAG_QUERY_REWRITE_ENABLED=true
RAG_HYDE_ENABLED=true
RAG_HYBRID_SEARCH_ENABLED=true
RAG_VECTOR_WEIGHT=0.7
RAG_BM25_WEIGHT=0.3
RAG_RERANK_ENABLED=true
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=100
RAG_SEMANTIC_CHUNKING_ENABLED=true
RAG_MIN_EVIDENCE_SCORE=0.6
RAG_MIN_EVIDENCE_COUNT=2
RAG_FALLBACK_TO_WEB=true
```

Embedding 与 Rerank 当前均使用 DashScope。若要降级成本或离线运行，可以参考 `.env.example` 中的 `hash` / `heuristic` 配置思路。

### DataAgent V2 与 Text2SQL

DataAgent V2 当前作为数据认知核心开启，覆盖：

- 数据库连接管理与 schema 同步。
- 指标定义、语义层、表关系、分析技能。
- Intent、Entity、Metric、Time、Join、Semantic、Planner、SQL Compiler、Verifier、Reflection、Critic 子代理。
- DAG 并行、Supervisor 重试和高级分析。

关键开关：

```env
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_ADVANCED_ANALYTICS_MODE=auto
TEXT2SQL_JOIN_INFERENCE_ENABLED=true
TEXT2SQL_RESULT_INTERPRET_ENABLED=true
TEXT2SQL_MAX_RETRY=2
```

## API 概览

所有业务接口默认带 `/api/v1` 前缀。

| 模块 | 主要接口 |
| --- | --- |
| Health | `GET /health`，`GET /health/deps`，`GET /health/runtime`，`GET /ping` |
| Auth | `POST /auth/register`，`POST /auth/login`，`GET /auth/me` |
| Chat | `POST /chat`，`POST /chat/stop`，`POST /chat/regenerate`，附件上传与消息版本 |
| Conversations | 会话列表、创建、归档、删除、分支和消息读取 |
| Documents | 文档上传、搜索、详情、更新和删除 |
| Memories | 记忆列表、创建、更新、删除和设置 |
| Tasks | 任务创建、暂停、恢复、取消、通知 |
| Data | `POST /data/query`，schema 同步和读取 |
| Databases | 数据库连接、连通性测试、schema 同步、SQL 查询、语义层 |
| Metrics | 指标定义、发布、废弃和 lineage |
| Table Relationships | 表关系维护、验证和图谱 |
| Analytical Skills | 分析技能维护、激活、废弃和 seed |
| Skills | 技能列表、安装、创建、测试、会话绑定 |
| Connectors | 连接器授权、回调、资源和同步 |
| Rules | 规则文件读取、生成、更新和删除 |
| Audit | 审计日志查询和导出 |
| Admin | 用户审批、工具、策略、bandit、meta cycle、自博弈 |
| Sandbox | 沙箱文件下载 |
| Cognitive | 认知事件 replay |

完整接口以 `http://localhost:14100/docs` 为准。

## 本地开发

推荐仍使用 Docker 跑 PostgreSQL/Redis，然后在宿主机运行 API 或前端。由于当前 `.env` 的 `DATABASE_URL` 和 `REDIS_URL` 使用容器内主机名 `postgres` / `redis`，宿主机直接运行后端时需要临时覆盖为宿主机地址。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

DATABASE_URL=postgresql://postgres:<your-postgres-password>@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:<your-postgres-password>@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

前端开发：

```bash
cd frontend
npm install
npm run dev
```

构建前端：

```bash
cd frontend
npm run build
```

## 数据库与迁移

API 启动时会执行 `ensure_runtime_schema()`，用于保证运行期核心表结构存在。迁移系统使用 Alembic，配置入口为 `alembic.ini` 和 `alembic/env.py`。

Docker 环境执行迁移（推荐；宿主机 `.env` 的 `postgres` 主机名仅容器内可解析）：

```bash
bash scripts/migrate.sh
```

验证迁移幂等：

```bash
bash scripts/verify_migration_idempotent.sh
```

查看核心表：

```bash
docker compose exec -T postgres psql -U postgres -d opentrace_v2 -c "\dt"
```

## 测试与验收

Docker 快速验收：

```bash
bash scripts/verify_docker.sh
```

Docker 完整验证：

```bash
bash scripts/verify_all_docker.sh
```

本地完整验证：

```bash
bash scripts/verify_all.sh
```

单测示例：

```bash
python -m pytest -q
python -m pytest -q tests/test_responses_contract.py tests/test_scheduler_v2.py
```

发布前检查：

```bash
bash scripts/preflight_release.sh
```

## 项目结构

```text
opentrace/
├── gateway/                 # FastAPI API Gateway
│   └── api_gateway/
│       ├── main.py          # FastAPI app、middleware、router 注册
│       └── routers/         # auth/chat/data/databases/documents 等 API
├── kernel/                  # 统一 Agent Loop、上下文、工具与专业能力
│   ├── agent_loop/
│   ├── runtime/
│   ├── data_cognition/
│   └── capability_intelligence/
├── agents/                  # Agent Cluster 与 DataAgent V2 子代理
│   ├── worker.py
│   └── data_agent_v2/
├── infra/                   # 配置、存储、Redis、消息总线、观测、安全、错误模型
│   ├── config/settings.py
│   ├── storage/
│   ├── message_bus/
│   └── observability/
├── memory/                  # working/episodic/semantic/procedural/temporal memory
├── model/                   # LLM adapter、embedding、reranker、model gateway
├── tools/                   # 工具注册与内置工具
├── plugins/                 # web/document/knowledge/memory/tool/code/chart/data 插件
├── execution/               # DAG、tool router、workflow、sandbox、SQL executor
├── skills/                  # skill runtime 与 marketplace/store
├── connectors/              # connector registry、SDK、内置 GitHub connector
├── safety/                  # guardrails、policy、masking、audit、XAI
├── sandbox_runtime/         # 本地 AST、gVisor、Firecracker provider
├── frontend/                # React + Vite + Tailwind 管理界面
├── docs/                    # 模块 catalog 与 service 文档
├── scripts/                 # 启停、验证、迁移、运维脚本
├── deploy/                  # Docker、K8s、Helm 部署配置
├── alembic/                 # 数据库迁移
├── tests/                   # 合约测试与回归测试
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── start.sh
├── stop.sh
└── restart.sh
```

## 常见问题

### 端口 14100 被占用

`start.sh` 会在启动前检查 `14100`。如果失败，先定位占用进程：

```bash
lsof -iTCP:14100 -sTCP:LISTEN
```

释放端口后重新执行：

```bash
bash start.sh
```

### API 健康检查失败

先看容器状态和日志：

```bash
docker compose ps
bash scripts/docker_logs.sh api
bash scripts/docker_logs.sh agent-worker
```

再检查依赖：

```bash
curl http://127.0.0.1:14100/api/v1/health/deps
```

如果 database 或 redis 异常，确认 `.env` 中容器内地址仍为：

```env
DATABASE_URL=postgresql://postgres:<password>@postgres:5432/opentrace_v2
REDIS_URL=redis://redis:6379/10
```

### 宿主机本地运行后端无法连接数据库

这是因为 `.env` 默认适配 Docker 网络。宿主机进程无法解析 `postgres` / `redis`，需要临时覆盖为 `127.0.0.1`，Redis 宿主机端口默认是 `6380`。

### 前端请求错端口

前端读取 `frontend/.env*` 或根 `.env` 中的 `VITE_API_URL`。当前后端实际地址是：

```env
VITE_API_URL=http://localhost:14100
```

浏览器控制台出现网络错误时，优先确认该值和 API 健康检查地址一致。

### LLM、Embedding 或 Rerank 调用失败

检查对应 API Key 和 Base URL：

```env
DEFAULT_LLM_QUERY_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RERANK_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

容器内可通过日志确认具体错误：

```bash
bash scripts/docker_logs.sh api
```

### 注册或邮件发送失败

当前注册由 `.env` 中的这些变量控制：

```env
REGISTRATION_ENABLED=true
REGISTRATION_ALLOWED_EMAIL_DOMAIN=<allowed-domain>
ADMIN_EMAIL=<admin-email>
SMTP_HOST=<smtp-host>
SMTP_PORT=465
SMTP_USER=<smtp-user>
SMTP_PASS=<smtp-password-or-app-token>
SMTP_FROM=<sender>
```

确认 SMTP 授权码有效，且邮箱服务允许应用专用密码或 SMTP 登录。

## 相关文档

| 文档 | 内容 |
| --- | --- |
| `docs/runbooks/chatgpt_cutover.md` | Responses Agent Loop 的迁移、灰度与回滚手册 |
| `docs/CONFIG_TRUTH.md` | 端口、URL、RAG 阈值配置真相表 |
| `docs/ENV_PROFILES.md` | dev / staging / production 推荐开关 |
| `docs/FEATURE_FLAG_REGISTRY.md` | 内核 Feature Flag 注册表 |
| `docs/CAPABILITY_MATURITY.md` | 模块成熟度（生产 vs stub） |
| `docs/OBSERVABILITY_COGNITIVE_HEALTH.md` | 认知健康指标与观测 |
| `docs/adr/` | 架构决策记录（vNext / Governance / Memory） |
| `docs/runbooks/` | 排障与发布 runbook |
| `docs/catalog/agent_runtime.md` | Agent Runtime 说明 |
| `docs/catalog/data_agent.md` | DataAgent 说明 |
| `docs/catalog/data_cognition.md` | Data Cognition / Text2SQL 说明 |
| `docs/catalog/rag_retrieval.md` | RAG 与检索说明 |
| `docs/catalog/memory_system.md` | Memory System 说明 |
| `scripts/work/README.md` | 启停与开发工作流脚本 |

## 贡献约定

1. 新功能优先补充或更新合约测试。
2. 合并前运行 `pytest -q`、前端 build/test 与 `bash scripts/check_import_boundaries.sh`。
3. 提交前至少运行与改动范围匹配的验证脚本。
4. 配置新增项需要同步更新 `.env.example`、`docs/FEATURE_FLAG_REGISTRY.md` 和本 README。
5. 不提交 `.env`、日志、数据库 dump、密钥或本地缓存。
6. 保持 API 错误响应符合统一 error envelope。

## License

MIT
