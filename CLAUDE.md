# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

OpenTrace 是以 Cognitive Kernel 为核心的 AgentOS 后端 + 前端项目，覆盖对话 QA、RAG、工具调用、DataAgent/Text2SQL、记忆、审计、任务与运行时观测。主要技术栈：Python 3.11+、FastAPI、PostgreSQL/pgvector、Redis、React/Vite。统一部署优先使用 Docker Compose。

默认执行路径是 **vNext / Cognitive Runtime V2**，V4 只作为 legacy fallback 保留：

```text
Gateway chat API
  → CognitiveKernel.process / stream
  → CognitiveSupervisor.prepare_run
  → RuntimeGateway.run / stream
  → kernel.runtime.registry.dispatch_runtime
       ├─ cognitive_executive
       ├─ data_intelligence
       └─ multi_goal
  → CognitiveSupervisor.run_outcomes
```

关键边界：

- `RuntimeGateway` 只做 runtime lookup + dispatch，不在其中调用 `evaluate_turn` 或构建最终 artifact。
- goal planning、多问题路由、governance 预检属于 `kernel/cognitive_supervisor/`。
- V4 默认关闭（`kernel_orchestrator_v4_enabled=False`），只通过 `legacy/v4/` 兼容入口使用。
- 配置优先级：环境变量 > `.env` > `infra/config/settings.py` 默认值；修改 `.env` 后重启服务。

## 常用命令

### 环境与运行

```bash
# 安装后端开发依赖
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 首次准备配置
cp .env.example .env

# 启动 / 停止 / 重启 Docker 后端栈
bash start.sh
bash stop.sh
bash restart.sh

# 启动后端 + Prometheus + Jaeger
bash start.sh --with-observability

# 启动后同时做快速验收
bash start.sh --verify

# 查看容器日志
bash scripts/docker_logs.sh api
bash scripts/docker_logs.sh agent-worker

# 完整清空数据卷后重启
bash stop.sh --volumes && bash start.sh
```

Docker 镜像通过 `COPY . .` 打包源码，容器内代码未更新时强制重建：

```bash
docker compose build --no-cache api agent-worker && bash restart.sh
```

宿主机本地跑 API、Docker 只跑 PostgreSQL/Redis 时，需要覆盖容器内主机名：

```bash
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev      # http://localhost:14108
npm run build
npm run test
```

### 测试、检查与验收

```bash
# 后端单测 / 合约测试
pytest
pytest tests/path/to/test.py::test_function

# 代码格式与静态检查
black .
ruff check .
mypy .

# 项目级验证
bash scripts/verify_all.sh
bash scripts/verify_all_docker.sh
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/check_import_boundaries.sh
bash scripts/check_kernel_silent_failures.sh
bash scripts/check_gateway_silent_failures.sh
bash scripts/verify_kernel_loop.sh

# 关键专项验收
bash scripts/verify_agent_bus_e2e.sh
bash scripts/verify_error_envelope.sh
bash scripts/verify_e2e.sh
bash scripts/verify_migration_idempotent.sh
```

### 数据库迁移与维护

```bash
# Docker 环境执行迁移
docker compose exec -T api alembic upgrade head

docker compose exec -T api alembic history --verbose
docker compose exec -T api alembic revision --autogenerate -m "description"
bash scripts/verify_migration_idempotent.sh

# 常用维护脚本
bash scripts/apply_provided_schema_to_docker.sh
bash scripts/clean_session.sh
python scripts/seed_user.py
python scripts/memory_evolve.py
python scripts/cleanup_retention.py
python scripts/opentrace_replay.py <trace_id>
bash scripts/preflight_release.sh
```

## 代码架构导览

- `gateway/`：FastAPI 入口。`gateway/api_gateway/main.py` 注册应用、中间件与路由；主聊天入口在 `gateway/api_gateway/routers/chat.py`，负责同步/流式对话、权限、附件与数据源上下文。
- `kernel/`：核心认知编排层。
  - `cognitive_kernel.py` 是统一 run/stream 入口。
  - `cognitive_supervisor/` 位于 Kernel 与 RuntimeGateway 之间，负责 GoalGraph、IntentLock、governance 预检、route hint 与 runtime task 构造。
  - `runtime/` 是 vNext 执行管线，覆盖 rewrite、understanding、planning、capability graph、DAG execution、Evidence Bus、Fusion/Critic、ArtifactComposer、Workspace、Replay。
  - `protocol/` 定义跨域稳定契约；`goal/` 管理一等目标生命周期；`governance/` 是 vNext 内嵌治理编排；顶层 `governance/` 提供可复用 governor 实现。
  - V5 routing 相关文件包括 `query_router_v2.py`、`complexity_engine.py`、`tiny_router.py`、`semantic_cache.py`、`context_assembler.py`。
  - `cognition/`、`cognitive_controls.py`、`clarification_gate.py`、`conversation_state.py` 处理意图、实体、预算、澄清、多轮状态和多问题分解。
- `agents/`：Agent Cluster。`worker.py` 消费 Redis Agent Bus；`registry.py` 管理 agent 注册；`rag_agent.py`、`web_agent.py`、`tool_agent.py`、`vision_agent.py` 等执行具体能力；`data_agent_v2/` 是 DataAgent V2 的知识层、推理子代理、DAG supervisor 与修复流程。
- `services/`：仓库内 service runtime。`services/data_intelligence_runtime/` 将 DataAgent V1/V2 接入 RuntimeGateway，返回与 CognitiveExecutive 兼容的结果。
- `model/`：模型网关与 provider adapter。按 `LLMRole` 路由 Query、Planning、Compress、Router、Fast、Critic、Knowledge、Identity、Vision 等模型。
- `memory/`：工作记忆、情景记忆、语义记忆、程序记忆、时间衰减、memory router 与 memory fabric。
- `infra/`：配置、数据库/Redis、消息总线、观测、错误模型与运行时 guard。新增配置从 `infra/config/settings.py` 开始，并同步 `.env.example` 与相关文档。
- `execution/`、`plugins/`、`tools/`、`skills/`、`connectors/`、`safety/`、`sandbox_runtime/`：分别承载 DAG/tool/workflow 执行面、插件系统、工具注册、技能、外部连接器、安全与沙箱运行时。
- `frontend/`：React + Vite 前端，默认端口 14108，API 指向 `http://localhost:14100`。
- `alembic/`：数据库迁移；`tests/`：单元、合约与回归测试；`docs/`：架构、配置、发布门禁和模块 catalog；`scripts/`：启停、验证、迁移、运维脚本。

## 开发时优先查看的位置

- 对话链路问题：`gateway/api_gateway/routers/chat.py` → `kernel/cognitive_kernel.py` → `kernel/cognitive_supervisor/` → `kernel/runtime/`。
- vNext 架构契约：`tests/test_vnext_architecture_contract.py`、`tests/test_cognitive_supervisor_contract.py`、`tests/test_cognitive_runtime_contract.py`、`scripts/run_vnext_final_tests.sh`。
- 路由与意图：`kernel/query_router_v2.py`、`kernel/complexity_engine.py`、`kernel/cognitive_controls.py`、`tests/test_v5_routing_contract.py`。
- RAG：`agents/rag_agent.py`、`docs/catalog/rag_retrieval.md`、`tests/test_rag_agent_contract.py`。
- DataAgent/Text2SQL：`agents/data_agent_v2/`、`services/data_intelligence_runtime/`、`docs/catalog/data_agent.md`、`docs/catalog/data_cognition.md`。
- 配置真相：`infra/config/settings.py`、`.env.example`、`docs/CONFIG_TRUTH.md`、`docs/FEATURE_FLAG_REGISTRY.md`、`docs/ENV_PROFILES.md`。
- 发布/合并门禁：`docs/RELEASE_GATE.md`、`bash scripts/preflight_release.sh`。

## 配置与运行约定

- 端口真相：API `14100`，前端 `14108`，Redis 宿主机端口 `6380`，PostgreSQL `5432`，Prometheus `14190`，Jaeger `14186`。
- Agent Bus 支持 `pubsub` 与 `stream`，当前主路径依赖 Redis。
- SQL 查询必须只读，并绑定 `data_source_id`；Text2SQL 结果需经过校验与后处理。
- RAG 证据门槛以 `RAG_MIN_EVIDENCE_SCORE` 为主；配置说明见 `docs/CONFIG_TRUTH.md`。
- 新增 feature flag 时，同步 `infra/config/settings.py`、`.env.example`、`docs/FEATURE_FLAG_REGISTRY.md`，必要时更新 `docs/ENV_PROFILES.md`。
- 前端 API 地址通过 `VITE_API_URL` / `VITE_WS_URL` 配置，默认指向 `http://localhost:14100`。

## 代码风格与语言规范

- Python 代码遵循 `pyproject.toml`：Black line-length 100；Ruff 规则 `E/F/I/N/UP` 且忽略 `E501`；mypy 非 strict、忽略缺失导入；pytest 默认 `tests/` 且 `pythonpath=["."]`。
- 写代码时匹配周边命名、抽象层级和注释密度；不要绕过 vNext 的 supervisor/runtime/governance 边界。
- 所有对话、解释、建议必须使用**简体中文**。
- 代码注释必须使用中文。

## 参考文档

- `README.md`：快速启动、端口、配置、API 与项目结构。
- `docs/CONFIG_TRUTH.md`：端口、URL、RAG 阈值配置真相表。
- `docs/FEATURE_FLAG_REGISTRY.md`：Feature Flag 注册表。
- `docs/RELEASE_GATE.md`：PR/发布合并门禁。
- `docs/ENV_PROFILES.md`：dev/staging/prod 推荐配置。
- `docs/adr/`：架构决策记录。
- `docs/runbooks/`：运行排障手册。
- `docs/catalog/`：cognitive kernel、agent runtime、data agent、RAG、memory 等模块说明。
