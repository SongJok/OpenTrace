# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目与当前主路径

OpenTrace 是一个以 Responses API 和可恢复 Agent Loop 为核心的 AgentOS 全栈项目，覆盖对话、RAG、工具与专家 Agent、DataAgent/Text2SQL、记忆、Goal、定时任务、审批、审计和运行时观测。后端使用 Python 3.11、FastAPI、PostgreSQL/pgvector、Redis；前端使用 React、TypeScript 和 Vite。默认部署方式是 Docker Compose。

当前在线对话主路径不是旧的 `CognitiveKernel → CognitiveSupervisor → RuntimeGateway`，而是：

```text
POST /api/v2/responses
  → API 校验租户、资源范围和幂等键
  → PostgreSQL Response / Item / Event / Outbox（同一事务提交）
  → Agent Worker 将 Outbox 投递到 Redis Streams，并以数据库租约领取 Response
  → AgentLoop：IntentPlan → ContextAssembler → Manager model/tool loop
  → typed tools / expert agents（写操作进入持久化审批暂停点）
  → PostgreSQL 持久化输出、事件与工具账本
  → SSE 从持久化事件投影，可按 sequence_number 断点续传
  → 会话摘要与记忆学习
```

`/api/v1/chat` 和 `/api/v1/tasks` 已退役并返回 `410 Gone`。`kernel/cognitive_supervisor/`、`kernel/runtime_gateway.py` 等旧认知运行时代码仍有架构合约覆盖，但不应被当作当前 Responses 请求入口；只有任务明确涉及该兼容子系统时才修改。

## 常用命令

### 安装与运行

```bash
# 后端开发环境
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

# 首次准备配置
cp .env.example .env

# Docker 后端栈：API、Agent Worker、PostgreSQL、Redis
bash start.sh                    # 启动后会执行 alembic upgrade head
bash start.sh --build            # 强制执行缓存增量构建并启动
bash start.sh --rebuild          # 仅排查缓存问题时完全重建
bash start.sh --pull             # 主动更新基础或远程镜像
bash start.sh --verify           # 启动并做 Docker 快速验收
bash start.sh --with-observability
bash stop.sh
bash restart.sh

# 日志
bash scripts/docker_logs.sh api
bash scripts/docker_logs.sh agent-worker
```

Prometheus 和 Jaeger 仅在 `--with-observability` 下启动。Compose 不包含前端。

Docker 镜像通过 `COPY . .` 打包源码，并通过镜像 label 保存源码指纹。普通启动会在
指纹变化时自动增量构建；也可以显式强制构建：

```bash
bash restart.sh --build
```

日常 `start.sh` / `restart.sh` 会复用已有统一应用镜像，不再默认构建或拉取。
只有缓存异常时才使用 `bash restart.sh --rebuild`。

宿主机运行 API、Docker 只承载 PostgreSQL/Redis 时，要覆盖容器网络主机名：

```bash
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

### 测试与静态检查

```bash
# 全部后端测试
python -m pytest -q

# 单个文件 / 单个测试
python -m pytest -q tests/test_responses_contract.py
python -m pytest -q tests/test_responses_contract.py::test_stream_disconnect_does_not_cancel_durable_response

# 格式、lint、类型检查
black --check .
black .
ruff check .
mypy .

# 架构边界与主要合约
bash scripts/check_import_boundaries.sh
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/check_gateway_silent_failures.sh
bash scripts/check_kernel_silent_failures.sh

# 运行中的服务栈验收
bash scripts/verify_all.sh
bash scripts/verify_all_docker.sh
bash scripts/verify_agent_bus_e2e.sh
bash scripts/verify_e2e.sh

# 发布前；默认 --full，也可用 --quick
bash scripts/preflight_release.sh --full
```

`verify_all.sh` 中包含 HTTP/Redis 等端到端检查，通常需要已启动的依赖；纯合约回归优先直接运行相关 pytest 或 `run_vnext_final_tests.sh`。

### 前端

```bash
cd frontend
npm ci
npm run dev                         # http://localhost:14108
npm run build                       # tsc -b && vite build
npm test                            # vitest run
npm test -- src/utils/__tests__/responsesStream.contract.test.ts
```

CI 使用 Node.js 20；不要只运行 Vite build 而跳过 TypeScript 构建。

### 数据库迁移

```bash
bash scripts/migrate.sh

docker compose exec -T api alembic history --verbose
docker compose exec -T api alembic revision --autogenerate -m "description"
bash scripts/verify_migration_idempotent.sh
```

开发环境允许 `ensure_runtime_schema()` 做兼容性 DDL；staging/production 只做 schema readiness 校验，正式结构变更必须通过 Alembic。

## 架构边界

### API 与持久化执行面

- `gateway/api_gateway/main.py` 创建 FastAPI 应用、注册中间件和路由；主对话入口是 `gateway/api_gateway/routers/responses.py`。
- Responses API 只验证命令并提交持久状态。模型和工具执行只能发生在 Worker，不能在 API 请求进程中通过 background task 偷跑。
- `ResponseRecord`、`ResponseItem`、`ResponseEvent` 和相关审批/工具账本是在线会话事实来源。旧 Message/TraceLog 只能作为迁移输入，不能重新引入在线读取。
- PostgreSQL 是事实来源，Redis Streams 只是投递与唤醒层。Redis 丢消息或不可用时，Worker 通过数据库 claim 恢复；流式客户端断开不会取消 Response。
- `infra/responses/repository.py` 管理事件、Outbox、租约和重试；`infra/responses/worker.py` 负责 Outbox 投递、Response 执行、恢复与最终持久化。`infra/response_worker.py` 只是兼容导入。

### Manager Agent Loop

- `kernel/agent_loop/runner.py` 是当前 Manager loop：先用严格工具调用生成 `IntentPlan`，再选择最小能力集合，调用统一 Model Gateway，并循环执行工具/专家 Agent。
- `kernel/agent_loop/context.py` 只沿当前 Response 父链组装上下文。优先级依次为平台/租户、Project、Assistant Profile/用户指令、会话/回合指令、当前输入；记忆按 user/project/conversation scope 隔离。
- 只读工具可自动执行；write/destructive 工具必须写入 `ResponseApproval` 并返回 `requires_action`。副作用工具不自动重试，未知结果进入 reconciliation 状态；不要绕过持久化幂等账本。
- `model/model_gateway/gateway.py` 是模型调用统一入口，按 `LLMRole` 管理 adapter、fallback、重试、熔断和调用计量。不要在业务模块直接实例化 provider client。

### Capability、Agent 与后台 Worker

- `kernel/runtime/capability.py` 的 registry 同时暴露 typed tools 与专家 Agent。内置 Agent 由 `agents/bootstrap.py` 按 `kernel/agent_runtime/agent_topology_manifest.yaml` 注册。
- Tier-1 内置能力包括 data、rag、web_intelligence、tool、vision、skills、rules。拓扑 manifest 是 bootstrap/worker/bus eligibility 的单一真相；变更时同步其版本和 Agent Runtime 合约测试。
- `agents/worker.py` 同时运行 Responses worker、scheduler、knowledge jobs、memory subscriber 和 Agent Bus consumers。Responses Stream 与通用 `AgentMessageBus` 是不同通道，不要混用其可靠性语义。
- Agent 不得反向导入 Gateway 或 Cognitive Kernel；`scripts/check_import_boundaries.sh` 和 import-linter 维护这些边界。

### 专项能力

- RAG 主实现位于 `agents/rag_agent.py`、`knowledge/`、`plugins/document_retrieval.py` 和 `services/rag_query_planning.py`。RagAgent 负责返回证据与 citation，不负责生成最终答案；最终回答由 Manager loop 合成。
- DataAgent 入口是 `agents/data_agent.py`，V2 由 `agents/data_agent_v2/supervisor.py` 及其 DAG 子代理执行。SQL 必须绑定授权的 `data_source_id`，只读并经过方言归一化、校验、执行后检查；V1 fallback 只能由配置显式开启。
- `memory/` 和 Responses 侧的 `MemoryLearner` 分工不同：前者提供记忆基础设施，后者在 Response 完成后提取候选并写入当前租户/工作区范围。
- `frontend/src/api/client.ts` 实现 `/api/v2/responses` 请求、SSE 事件解析、续传、审批和 retry；修改事件协议时同时更新前端 contract tests。

## 修改时必须保持的约束

- 创建父 `ResponseRecord` 后，在写入带纯外键的 Item/Event/Outbox 前显式 `flush()`；这些 ORM 模型没有 relationship 可帮助 SQLAlchemy 推断插入顺序。
- 所有资源查询同时保持 user、tenant、workspace 边界；不能只凭对象 ID 查询后返回。
- 新增配置或 feature flag 时同步 `infra/config/settings.py`、`.env.example`、`docs/FEATURE_FLAG_REGISTRY.md`，必要时更新 `docs/ENV_PROFILES.md` 和 `docs/CONFIG_TRUTH.md`。
- 配置优先级是环境变量 > `.env` > `infra/config/settings.py` 默认值；修改 `.env` 后重启进程或容器。
- 端口真相：API `14100`、前端 `14108`、PostgreSQL `5432`、Redis 宿主机 `6380`、Prometheus `14190`、Jaeger `14186`。`GATEWAY_PORT=14101` 是废弃残留。
- Python 遵循 `pyproject.toml`：Black/Ruff line length 100，Ruff `E/F/I/N/UP`（忽略 `E501`），pytest 默认 `tests/` 且仓库根目录在 `pythonpath`。
- 所有对话、解释和建议使用简体中文；新增代码注释使用中文，并匹配周边注释密度。

## 排障入口与权威资料

- Responses 创建/SSE/重试：`gateway/api_gateway/routers/responses.py`、`infra/responses/`、`tests/test_responses_contract.py`
- Agent Loop/上下文/审批：`kernel/agent_loop/`、`tests/test_kernel_agent_loop.py`、`tests/test_responses_contract.py`
- Worker/定时任务：`agents/worker.py`、`infra/responses/worker.py`、`infra/responses/scheduler.py`、`tests/test_scheduler_v2.py`
- RAG：`agents/rag_agent.py`、`docs/catalog/rag_retrieval.md`、`tests/test_rag_agent_contract.py`
- DataAgent：`agents/data_agent.py`、`agents/data_agent_v2/`、`docs/catalog/data_agent.md`
- 配置与部署：`infra/config/settings.py`、`docs/CONFIG_TRUTH.md`、`docs/ENV_PROFILES.md`、`README.md`
- Responses 切换/回滚：`docs/runbooks/chatgpt_cutover.md`

README 或 catalog 与在线代码冲突时，以路由、Worker、模型定义、迁移和合约测试为准。
