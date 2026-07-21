# OpenTrace

[![CI](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml)
[![vNext contracts](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)

OpenTrace 是一个可自托管的企业 AgentOS。它以 OpenAI 风格的 Responses API、可恢复
Agent Loop 和 PostgreSQL 持久化事件为核心，把企业数据库、知识库、审批治理、主动预警、
对话、记忆、Goal 与定时任务组织到同一条产品主链中。

> **项目状态：Alpha。** 核心链路和合约测试已经建立，但在生产部署前仍应完成密钥托管、
> 网络隔离、备份恢复、容量评估和组织级安全审查。

## 为什么是 OpenTrace

- **企业数据与知识联合推理**：在同一个 Project 中绑定 MySQL、Doris、ClickHouse 或
  PostgreSQL，并结合已发布知识生成带证据的回答。
- **持久化而非请求内执行**：API 只提交命令；Worker 通过 Outbox、Redis Streams 和数据库
  租约执行，浏览器断线不会取消任务，SSE 可以按序号恢复。
- **治理默认开启**：租户、工作区、用户和 Project 数据源边界在 API、Agent 与后台任务中
  重复校验；写入和破坏性工具进入持久化审批节点。
- **从问数到主动预警**：DataAgent/Text2SQL 生成只读 SQL，主动预警复用相同权限范围，
  保存阈值、SQL、结果预览和置信度等治理证据。
- **可观测、可测试、可替换**：模型调用统一经过 Model Gateway；架构边界、Responses、
  RAG、DataAgent、审批和调度行为均有合约测试。

## 产品主线

```text
Project
  ├─ 企业数据库：MySQL / Doris / ClickHouse / PostgreSQL
  │    └─ 连接测试 → Schema 同步 → 语义层 → DataAgent / Text2SQL
  ├─ 企业知识库：文档 → 编译 → 审核/发布 → RAG 引用
  ├─ 审批治理：租户/工作区/Project ACL → 写操作审批 → 审计事件
  └─ 主动预警：定时问数 → 确定性阈值 → 触发/恢复 → 通知与证据
```

典型使用方式：

1. 在“数据库”页面连接并验证企业数据源，系统自动同步 Schema。
2. 创建 Project，绑定允许查询的数据源，并上传制度、指标口径或业务文档。
3. 在聊天页选择 Project 和数据源，提出“结合经营数据与制度知识分析风险”等问题。
4. 让 Agent 创建预警规则；该写操作先进入审批，通过后由 Worker 持续运行。

## 核心架构

```text
POST /api/v2/responses
  → 校验身份、租户、Project、数据源和幂等键
  → PostgreSQL Response / Item / Event / Outbox（同一事务）
  → Worker 投递 Redis Streams，并通过数据库租约领取 Response
  → IntentPlan → ContextAssembler → Manager model/tool loop
  → typed tools / expert agents / RAG / DataAgent
  → write/destructive tool → durable approval pause point
  → PostgreSQL 持久化结果、事件、模型调用与工具账本
  → SSE 按 sequence_number 断点续传
  → 摘要、记忆学习、Goal/Task/Alert 后续执行
```

PostgreSQL 是在线事实来源，Redis 仅承担投递、唤醒和可选镜像。旧
`/api/v1/chat` 与 `/api/v1/tasks` 已退役并返回 `410 Gone`。

## 功能概览

| 领域 | 当前能力 |
| --- | --- |
| Responses | 持久化响应、流式事件、重试、取消、审批、断线恢复、会话分支 |
| Agent Loop | IntentPlan、最小能力选择、工具循环、专家 Agent、证据合成、步骤上限保护 |
| 企业数据库 | MySQL、Doris、ClickHouse、PostgreSQL；连接测试、Schema、语义映射、只读 SQL |
| DataAgent | Text2SQL、指标/实体/时间/Join 推理、校验、反思、结果解释和可视化配置 |
| 知识库 | 文档处理、Project 范围、知识编译、发布、检索、关系图和引用 |
| 治理 | 多租户/工作区边界、资源权限、持久化审批、审计、配额与策略接口 |
| 自动化 | Goal、Scheduled Task、主动数据预警、通知、失败重试与恢复事件 |
| 记忆 | 会话摘要、用户/Project 记忆、记忆治理与反馈学习 |
| Skills/Tools | typed tools、SkillHub、本地 Skill 管理；动态执行默认关闭 |
| 可观测性 | 结构化日志、OpenTelemetry、Prometheus、Jaeger、运行时健康接口 |
| 前端 | React、TypeScript、Vite；聊天、数据源、知识、审批、任务和预警界面 |

## 技术栈

- Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic
- PostgreSQL 16 + pgvector、Redis 7
- OpenAI-compatible Responses/model adapters，默认示例使用 Qwen/DashScope
- React 18、TypeScript、Vite、Zustand、Tailwind CSS
- Docker Compose；Prometheus 和 Jaeger 为可选 profile

## 快速开始

### 前置条件

- Docker 24+
- Docker Compose 2.20+
- Node.js 20.19+ 与 npm 10+（前端）
- Python 3.11+（仅本地开发和测试需要）

### 1. 准备配置

```bash
git clone https://github.com/SongJok/OpenTrace.git
cd OpenTrace
cp .env.example .env
```

`.env.example` 不包含真实密钥。至少需要为主模型填写对应角色的 API Key，例如：

```env
DEFAULT_LLM_QUERY_API_KEY=your-provider-key
DEFAULT_LLM_COMPRESS_API_KEY=your-provider-key
DEFAULT_LLM_PLANING_API_KEY=your-provider-key
DEFAULT_LLM_SENIORSHORT_API_KEY=your-provider-key
DEFAULT_LLM_MIDDLESHORT_API_KEY=your-provider-key
DEFAULT_LLM_JUNIORSHORT_API_KEY=your-provider-key
DEFAULT_LLM_MINSHORT_API_KEY=your-provider-key
DEFAULT_LLM_VISION_API_KEY=your-provider-key
```

Embedding/Rerank 可使用 `DASHSCOPE_API_KEY`，也可分别配置。生产或 staging 环境必须设置
独立的 `APP_SECRET_KEY`、`JWT_SECRET`、`DATA_SECRET_KEY`，并更换模板中的开发数据库和种子
用户密码。

### 2. 启动后端

```bash
bash start.sh
```

首次运行会构建统一的 API/Worker 镜像，启动 PostgreSQL、Redis、API 和 Agent Worker，执行
Alembic 迁移并创建开发种子账号。后续启动会通过源码指纹复用镜像。

常用选项：

```bash
bash start.sh --build               # 强制缓存增量构建
bash start.sh --rebuild             # 仅排查缓存污染时无缓存重建
bash start.sh --with-observability  # 启用 Prometheus 与 Jaeger
bash start.sh --verify              # 启动后执行 Docker 快速验收
```

验证服务：

```bash
curl http://127.0.0.1:14100/api/v1/health
curl http://127.0.0.1:14100/api/v1/health/deps
```

### 3. 启动前端

Docker Compose 默认不包含前端：

```bash
cd frontend
npm ci
npm run dev
```

打开 <http://localhost:14108>。Swagger 位于 <http://localhost:14100/docs>。

## 服务端口

| 服务 | 宿主机端口 | 容器端口 |
| --- | ---: | ---: |
| API / Swagger | `14100` | `14100` |
| Vite 前端 | `14108` | - |
| PostgreSQL | `5432` | `5432` |
| Redis | `6380` | `6379` |
| Prometheus（可选） | `14190` | `9090` |
| Jaeger UI（可选） | `14186` | `16686` |
| OTLP gRPC（可选） | `4317` | `4317` |

API 端口以 `APP_PORT=14100` 为准。`GATEWAY_PORT` 必须保持一致；staging/production 配置不一致
会直接拒绝启动。

## 数据库接入

| 类型 | 驱动/协议 | 默认端口 | 说明 |
| --- | --- | ---: | --- |
| MySQL | `asyncmy` | `3306` | 支持只读会话设置、Schema 与 Text2SQL |
| Doris | MySQL protocol / `asyncmy` | `9030` | 使用 Doris 方言与兼容的只读执行策略 |
| ClickHouse | `clickhouse-sqlalchemy` + `asynch` | `9000` | 使用 ClickHouse 系统表同步 Schema |
| PostgreSQL | `asyncpg` | `5432` | 支持 PostgreSQL 方言与只读事务 |

生产环境建议为每个数据源创建最小权限的只读账号。OpenTrace 同时使用 SQL AST 白名单、
结果行数限制、执行超时和 Project/ACL 校验，但这些应用层控制不能替代数据库权限。

## 配置与安全

配置优先级为：环境变量 → `.env` → `infra/config/settings.py` 默认值。

- `.env.example`：可提交的脱敏模板。
- `docs/ENV_PROFILES.md`：development/staging/production 推荐组合。
- `docs/CONFIG_TRUTH.md`：端口、URL 和配置真相。
- `docs/FEATURE_FLAG_REGISTRY.md`：受治理的内核开关。
- `SECURITY.md`：漏洞报告与部署安全要求。

提交前运行公开发布检查：

```bash
python scripts/check_public_release.py
```

该检查会拒绝跟踪 `.env`、私钥、本地运行产物、重复配置项或带值的敏感模板变量。

## API 概览

### `/api/v2`：当前 Agent 产品主路径

- `POST /api/v2/responses`
- Response 查询、事件流、重试、取消和审批
- Conversations、Projects、Assistant Profiles、Goals
- Scheduled Tasks、Active Alerts、Notifications
- Resource Permissions、Memories 与 Personalization

### `/api/v1`：业务资源与兼容接口

- Auth、Health、Documents、Knowledge、Databases、Data Query
- Metrics、Table Relationships、Analytical Skills
- Connectors、Skills、Audit、Rules、Admin、Sandbox

完整、实时的接口定义以 Swagger 为准。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

如果 PostgreSQL/Redis 在 Docker 中，而 API 在宿主机运行，需要覆盖容器网络主机名：

```bash
DATABASE_URL=postgresql://postgres:opentrace-dev@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:opentrace-dev@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

数据库迁移：

```bash
bash scripts/migrate.sh
bash scripts/verify_migration_idempotent.sh
```

## 测试

```bash
# 后端
python -m pytest -q
bash scripts/check_import_boundaries.sh
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh

# 对本次修改的 Python 文件做静态检查（替换为实际文件路径）
ruff check path/to/changed.py
black --check path/to/changed.py

# 前端
cd frontend
npm test
npm run build
```

运行中的 Docker 栈还可以执行：

```bash
bash scripts/verify_docker.sh
bash scripts/verify_all_docker.sh
bash scripts/preflight_release.sh --full
```

## 项目结构

```text
gateway/          FastAPI 应用与 API routers
infra/            配置、数据库、Responses、消息总线、安全与观测
kernel/           当前 Manager Agent Loop、上下文、运行时与数据认知
agents/           专家 Agent、DataAgent V2、RAG Agent 与 Worker
knowledge/        企业知识编排与检索
memory/           记忆基础设施与治理
model/            Model Gateway、provider adapters、embedding、reranker
execution/        SQL、DAG、workflow 与 sandbox 执行层
tools/            typed tool registry 与内置工具
skills/           Skill runtime、catalog 与安装策略
connectors/       connector registry、SDK 与内置连接器
governance/       宪法、审批与治理策略
frontend/         React + TypeScript 用户界面
alembic/          PostgreSQL 迁移
docs/             架构、catalog、配置与 runbook
scripts/          开发、测试、迁移、发布和运维脚本
tests/            单元、集成与架构合约测试
```

## 文档

- [架构概览](docs/architecture_overview.md)
- [Responses 切换与回滚](docs/runbooks/chatgpt_cutover.md)
- [DataAgent](docs/catalog/data_agent.md)
- [RAG 检索](docs/catalog/rag_retrieval.md)
- [Agent Runtime](docs/catalog/agent_runtime.md)
- [配置真相](docs/CONFIG_TRUTH.md)
- [环境配置档位](docs/ENV_PROFILES.md)
- [能力成熟度](docs/CAPABILITY_MATURITY.md)

## 参与贡献

请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要提交公开 issue。

## License

OpenTrace 使用 [MIT License](LICENSE)。
