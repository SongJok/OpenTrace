# OpenTrace

OpenTrace 是一个以 **Cognitive Kernel** 为核心的智能体系统，支持：

- 对话问答（同步 / 流式）
- 工具调用（Web / 时间 / 天气 / 代码等）
- 推理链与执行图可视化
- V4 架构：**Plan + Dispatcher + Agent Cluster + Fusion + Critic**（稳定默认版本）

---

## 快速开始（Docker 统一口径）

```bash
cd /path/to/opentrace
bash start.sh
```

服务地址：

- Frontend: http://localhost:14108
- API: http://localhost:14101
- Swagger: http://localhost:14101/docs

停止 / 重启：

```bash
bash stop.sh
bash restart.sh
```

---

## V4 推荐配置（稳定默认）

在 `.env` 中保持默认或显式设置：

```env
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_ENABLED=true
KERNEL_AGENT_DATA_ENABLED=true
KERNEL_AGENT_TOOL_ENABLED=true
KERNEL_AGENT_WEB_ENABLED=true
KERNEL_AGENT_RAG_ENABLED=true
KERNEL_AGENT_TIMEOUT_SEC=30
KERNEL_AGENT_MAX_PARALLEL=5
```

重启生效：

```bash
bash restart.sh
```

---

## 关键能力

- **自动联网检索**（支持 web search）
- **Sources 引用展示**（前端答案区）
- **检索过程可视化**（Searching / Reading / Ranking / Synthesizing）
- **时间 / 天气工具自动路由**（支持中英文城市别名）
- **Agent Cluster 并行执行**（Data / Web / Tool / RAG）

---

## 项目结构（简版）

```text
opentrace/
├── gateway/                 # FastAPI 接口层
├── kernel/                  # 核心编排（v1/v2/v3）
│   ├── orchestrator.py
│   ├── orchestrator_v2.py
│   ├── orchestrator_v3.py
│   ├── fusion_engine/
│   └── critic_engine/
├── tools/                   # 工具注册与内置工具
├── plugins/                 # web/doc/memory 等插件
├── frontend/                # React 前端
├── infra/                   # 配置/存储/观测/安全
├── tests/                   # 合约与回归测试
└── scripts/                 # 启停与验证脚本
```

---

## 测试与验证

本地快速验证：

```bash
bash scripts/verify_all.sh
```

Docker 内一致性验证：

```bash
bash scripts/verify_all_docker.sh
```

关键新增测试：

- `tests/test_orchestrator_v3_contract.py`
- `tests/test_fusion_critic_flags_contract.py`
- `tests/test_weather_city_routing_contract.py`
- `tests/test_time_weather_tools_behavior.py`

---

## 文档索引

- `SERVICE.md`：全量主文档（SSOT，推荐先读）
- `RUNBOOK.md`：运维与故障处理
- `scripts/work_script.md`：脚本使用说明

---

## 默认账号（本地开发）

- `songts@tuwan.com` / `123456`
