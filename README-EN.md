# OpenTrace

[英文版](README.md) | **简体中文**

[![CI](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml)
[![vNext contracts](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11–3.12](https://img.shields.io/badge/Python-3.11--3.12-3776AB.svg)](https://www.python.org/)

OpenTrace 是一个可自托管的企业 AgentOS。它以 OpenAI 风格的 Responses API、可恢复
Agent Loop 和 PostgreSQL 持久化事件为核心，让用户专注于一个提问页面，并提供三类能力：
RAG 检索、受治理的企业大脑上下文，以及只读 DataAgent。

> **项目状态：受控企业 Beta。** 支持范围内的产品主路径可进入受治理租户试点，但尚未达到
> GA；真实放量仍需通过主链评测，并完成密钥托管、网络隔离、备份恢复、容量评估和组织级安全审查。

## 为什么是 OpenTrace

- **企业数据与知识联合推理**：在受治理的工作区内接入 MySQL、Doris、ClickHouse 或
  PostgreSQL，并结合已发布知识生成带证据的回答。
- **持久化而非请求内执行**：API 只提交命令；Worker 通过 Outbox、Redis Streams 和数据库
  租约执行，浏览器断线不会取消任务，SSE 可以按序号恢复。
- **治理默认开启**：租户、工作区、用户和数据源边界在 API、Agent 与后台任务中
  重复校验；写入和破坏性工具进入持久化审批节点。
- **聚焦提问工作流**：所有问题都经过同一条持久化 Responses 主链；RAG 提供引用，企业大脑
  提供授权的公司上下文，DataAgent 提供经过校验的只读数据答案。
- **可观测、可测试、可替换**：模型调用统一经过 Model Gateway；架构边界、Responses、
  RAG、DataAgent、审批和调度行为均有合约测试。

## 产品主线

```text
提问页
  └─ IntentPlan → ContextAssembler → Manager loop
       ├─ 企业大脑：授权的公司上下文
       ├─ RAG：审核发布的知识与引用
       └─ DataAgent：授权数据库 → 校验后的只读 SQL → 证据
```

典型使用方式：

1. 管理员配置企业知识、企业大脑画像、权限和可查询的数据库。
2. 用户进入 `/chat`，在授权工作区范围内提出问题。
3. Manager loop 只选择 RAG 或 DataAgent；企业大脑由 ContextAssembler 注入，
   不作为用户可直接调用的工具暴露。

## 核心架构

```text
POST /api/v2/responses
  → 校验身份、租户、工作区、数据源和幂等键
  → PostgreSQL Response / Item / Event / Outbox（同一事务）
  → Worker 投递 Redis Streams，并通过数据库租约领取 Response
  → IntentPlan → ContextAssembler → Manager model/tool loop
  → RAG / 企业大脑上下文 / DataAgent (DataAgent)
  → PostgreSQL 持久化结果、事件、模型调用与工具账本
  → SSE 按 sequence_number 断点续传
  → 摘要与记忆学习
```

PostgreSQL 是在线事实来源，Redis 仅承担投递、唤醒和可选镜像。旧
`/api/v1/chat` 与 `/api/v1/tasks` 已退役并返回 `410 Gone`。

## 功能概览

| 领域 | 当前能力 |
| --- | --- |
| Responses | 持久化响应、流式事件、重试、取消、审批、断线恢复、会话分支 |
| Agent Loop | IntentPlan、最小能力选择、工具循环、专家 Agent、证据合成、步骤上限保护 |
| 企业数据库 | MySQL、Doris、ClickHouse、PostgreSQL；连接测试、Schema、语义映射、只读 SQL |
| DataAgent | DataAgent、指标/实体/时间/Join 推理、校验、反思、结果解释和可视化配置 |
| 企业知识库 | 公司/部门/岗位/工作区/个人空间、来源 ACL 同步、审核发布、有效期、密级、治理检索、关系图和引用 |
| 治理 | 多租户/工作区边界、资源权限、持久化审批、配额与策略接口 |
| 用户支持 | 我的资料、数据库、个人记忆、任务、Skills 与设置 |
| 记忆 | 会话摘要、用户/会话记忆、记忆治理与反馈学习 |
| Skills/Tools | typed tools、SkillHub、本地 Skill 管理；动态执行默认关闭 |
| 可观测性 | 结构化日志、OpenTelemetry、Prometheus、Jaeger、运行时健康接口 |
| 前端 | 以提问页为主的 React、TypeScript、Vite 界面；用户页与管理员治理页按权限展示 |

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
- Python 3.11 或 3.12（仅本地开发和测试需要）

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
| MySQL | `aiomysql` | `3306` | 支持只读会话设置、Schema 与 DataAgent |
| Doris | MySQL protocol / `aiomysql` | `9030` | 使用 Doris 方言与兼容的只读执行策略 |
| ClickHouse | `clickhouse-sqlalchemy` + `asynch` | `9000` | 使用 ClickHouse 系统表同步 Schema |
| PostgreSQL | `asyncpg` | `5432` | 支持 PostgreSQL 方言与只读事务 |

生产环境建议为每个数据源创建最小权限的只读账号。OpenTrace 同时使用 SQL AST 白名单、
结果行数限制、执行超时和工作区/ACL 校验，但这些应用层控制不能替代数据库权限。

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
- Conversations、Assistant Profiles、Goals
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
bash scripts/bootstrap_dev.sh
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
bash scripts/run_product_beta_gate.sh --contract

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
governance/       宪法、审批与治理策略
frontend/         React + TypeScript 用户界面
alembic/          PostgreSQL 迁移
docs/             架构、catalog、配置与 runbook
scripts/          开发、测试、迁移、发布和运维脚本
tests/            单元、集成与架构合约测试
```

## 文档

- [受控企业 Beta 就绪说明](docs/BETA_READINESS.md)
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

## 许可证

OpenTrace 使用 [MIT License](LICENSE)。
