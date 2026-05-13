# OpenTrace

OpenTrace 是一个以 **Cognitive Kernel** 为核心的智能体系统，支持：

- 对话问答（同步 / 流式 SSE）
- 工具调用（Web / 时间 / 天气 / 代码 / 计算器等）
- 推理链与执行图可视化
- 多轮对话状态追踪与上下文压缩
- V4 架构：**Plan + Dispatcher + Agent Cluster + Fusion + Critic**（稳定默认版本）

---

## 🚀 快速开始（Docker 统一口径）

### 前置依赖

| 组件 | 版本 | 说明 |
|------|------|------|
| Docker | ≥ 24.0 | 容器运行时 |
| Docker Compose | ≥ 2.20 | 编排工具 |
| PostgreSQL | 15+ | 持久化存储（docker-compose 自动拉起） |
| Redis | 7+ | 缓存/会话存储（docker-compose 自动拉起） |

### 启动服务

```bash
cd /path/to/opentrace

# 1. 复制环境变量模板并配置 LLM API Key
cp .env.example .env
# 编辑 .env，填写 DEFAULT_LLM_QUERY_API_KEY 等必要字段

# 2. 启动所有服务
bash start.sh

# 3. 验证服务状态
curl http://localhost:14101/health
```

### 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| Frontend | http://localhost:14108 | React 管理界面 |
| API Gateway | http://localhost:14101 | FastAPI 后端 |
| Swagger Docs | http://localhost:14101/docs | API 文档 |
| PostgreSQL | localhost:5432 | 数据库（默认账号：postgres/PASSWORD） |
| Redis | localhost:6379 | 缓存服务 |

### 停止 / 重启

```bash
bash stop.sh      # 优雅停止所有容器
bash restart.sh   # 重启服务（保留数据卷）
```

---

## ⚙️ 配置说明

### 核心环境变量（.env）

```env
# ── 数据库 ─────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@postgres:5432/opentrace_v2
TOKEN_DB_URL=postgresql+asyncpg://postgres:PASSWORD@postgres:5432/opentrace_v2

# ── LLM 配置（DashScope 示例）────────────────────────
DEFAULT_LLM_QUERY_PROVIDER=阿里巴巴 Qwen(DashScope)
DEFAULT_LLM_QUERY_MODEL=qwen3.6-plus
DEFAULT_LLM_QUERY_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEFAULT_LLM_QUERY_API_KEY=sk-xxxxxxxxxxxxxxxx

# ── Redis ──────────────────────────────────────────
REDIS_URL=redis://redis:6379/10

# ── 功能开关 ────────────────────────────────────────
KERNEL_ORCHESTRATOR_VERSION=v4
RAG_RERANK_ENABLED=true
ATTACHMENT_UPLOAD_ENABLED=true
```

> 💡 **提示**：修改 `.env` 后需执行 `bash restart.sh` 使配置生效。

### V4 推荐配置（稳定默认）

```env
KERNEL_AGENT_ENABLED=true
KERNEL_AGENT_DATA_ENABLED=true
KERNEL_AGENT_TOOL_ENABLED=true
KERNEL_AGENT_WEB_ENABLED=true
KERNEL_AGENT_RAG_ENABLED=true
KERNEL_AGENT_TIMEOUT_SEC=30
KERNEL_AGENT_MAX_PARALLEL=5
```

---

## 🔧 开发环境（非 Docker）

### 本地依赖安装

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库（开发环境）
python -c "from infra.storage.database import init_db; import asyncio; asyncio.run(init_db())"

# 4. 启动服务
python -m gateway.main
```

### 数据库迁移

> ⚠️ 生产环境请使用 Alembic，开发环境可使用自动建表：

```bash
# 自动创建/更新表结构（开发专用）
python -c "from infra.storage.database import ensure_runtime_schema; import asyncio; asyncio.run(ensure_runtime_schema())"
```

---

## 🧪 测试与验证

### 本地快速验证

```bash
bash scripts/verify_all.sh
```

### Docker 内一致性验证

```bash
bash scripts/verify_all_docker.sh
```

### 关键测试用例

- `tests/test_orchestrator_v3_contract.py` — 编排器接口契约
- `tests/test_fusion_critic_flags_contract.py` — Fusion/Critic 标志位
- `tests/test_weather_city_routing_contract.py` — 城市别名路由
- `tests/test_time_weather_tools_behavior.py` — 工具行为回归

---

## ⚠️ 常见问题排查

### 1. 数据库事务错误：`InFailedSQLTransactionError`

**现象**：问答时返回 `{"decision_type": "setup_error", "content": "服务暂时不可用"}`

**原因**：PostgreSQL 事务因前置查询失败进入 `aborted` 状态，后续查询被拒绝。

**排查步骤**：

```bash
# ① 检查数据库连接
pg_isready -h localhost -p 5432

# ② 验证表结构是否匹配代码模型
psql -h localhost -U postgres -d opentrace_v2 -c "\d+ chat_sessions"
psql -h localhost -U postgres -d opentrace_v2 -c "\d+ conversation_states"

# ③ 查看 pending 事务/锁
psql -h localhost -U postgres -d opentrace_v2 -c "SELECT * FROM pg_locks WHERE NOT granted;"

# ④ 临时恢复：重启数据库清理事务状态
docker restart opentrace-postgres-1  # 或 systemctl restart postgresql
```

**预防**：确保 `.env` 中 `DATABASE_URL` 配置正确，且首次启动时执行过数据库初始化。

### 2. LLM 调用失败 / 超时

- 检查 `.env` 中 `DEFAULT_LLM_QUERY_API_KEY` 是否已填写
- 确认网络可访问 `dashscope.aliyuncs.com`（或对应 provider）
- 查看日志：`docker logs opentrace-api-1 | grep -i "llm\|error"`

### 3. 前端无法连接 API

- 确认 `VITE_API_URL` 与实际 API 地址一致
- 检查浏览器控制台 CORS 错误
- 验证网关端口 `14101` 是否监听：`lsof -i :14101`

### 4. 附件上传失败

- 确认 `ATTACHMENT_STORAGE_PATH` 目录存在且可写
- 检查文件大小是否超过 `ATTACHMENT_MAX_SIZE_MB`（默认 20MB）

---

## 🏗️ 项目结构（简版）

```text
opentrace/
├── gateway/                 # FastAPI 接口层
│   ├── api_gateway/
│   │   ├── routers/         # chat.py, auth.py 等路由
│   │   └── middleware/      # 认证/限流/观测中间件
│   └── main.py              # 应用入口
├── kernel/                  # 核心编排引擎（v4 默认）
│   ├── orchestrator_v4.py   # 主编排器：Plan→Dispatch→Fusion→Critic
│   ├── fusion_engine/       # 多源结果融合
│   ├── critic_engine/       # 输出校验与修正
│   ├── conversation_state.py# 多轮对话状态管理
│   └── adaptive_profiles/   # 动态响应策略（speed/quality）
├── agents/                  # 可插拔 Agent 实现
│   ├── base.py, registry.py
│   ├── data_agent.py, rag_agent.py, web_agent.py, tool_agent.py
│   └── vision_agent.py, skills_agent.py
├── tools/                   # 工具注册与内置工具
│   ├── registry.py
│   └── builtin/             # weather, datetime, calculator, web_search
├── plugins/                 # 扩展插件（web/doc/memory）
├── frontend/                # React + Vite 管理界面
├── infra/                   # 基础设施层
│   ├── config/              # pydantic-settings 配置管理
│   ├── storage/             # SQLAlchemy models + asyncpg engine
│   ├── cache/               # Redis 客户端
│   ├── observability/       # OpenTelemetry + 日志
│   └── security/            # JWT + Zero Trust 校验
├── memory/                  # 记忆系统（短期/长期/演化）
├── execution/               # 执行层（tool router, data query）
├── tests/                   # 合约测试与回归用例
├── scripts/                 # 启停/验证/运维脚本
├── docker-compose.yml       # 服务编排定义
├── .env.example             # 环境变量模板
└── README.md                # 本文档
```

---

## 📚 文档索引

| 文档 | 说明 | 优先级 |
|------|------|--------|
| `SERVICE.md` | 全量主文档（SSOT），含架构/流程/配置详解 | ⭐⭐⭐ |
| `RUNBOOK.md` | 运维手册：监控/告警/故障处理 | ⭐⭐ |
| `scripts/work_script.md` | 脚本使用说明与开发工作流 | ⭐⭐ |
| `kernel/README.md` | Kernel 引擎设计文档（进阶） | ⭐ |

---

## 🤝 贡献指南

1. 创建分支：`git checkout -b codex/feature-name`
2. 遵循代码规范：`black . && ruff check .`
3. 添加测试：新功能需配套单元测试
4. 提交前验证：`bash scripts/verify_all.sh`
5. 提交 PR 并关联相关 Issue

---

## 📄 许可证

MIT License — 详见 `LICENSE` 文件
