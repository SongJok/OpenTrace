# OpenTrace Runbook

> 当前统一口径（2026-04-12）：
> - 后端 API：`http://localhost:14100`
> - 前端 Dev：`http://localhost:14108`
> - Swagger：`http://localhost:14100/docs`

## 1) 标准启动 / 停止 / 重启

启动：

```bash
bash start.sh
```

停止：

```bash
bash stop.sh
```

重启：

```bash
bash restart.sh
```

健康检查：

```bash
curl -s http://127.0.0.1:14100/api/v1/health
curl -s http://127.0.0.1:14100/api/v1/health/deps
```

---

## 2) Docker 启动

```bash
bash scripts/docker_up.sh
```

查看日志：

```bash
bash scripts/docker_logs.sh
# 或指定服务
bash scripts/docker_logs.sh api
```

停止并清理：

```bash
bash scripts/docker_down.sh
```

> 若端口冲突，可通过环境变量覆盖：
>
> - `POSTGRES_PORT`（默认 5432）
> - `REDIS_PORT`（默认 6380）
> - `PYTHON_BASE_IMAGE`（默认 `python:3.11-slim`）

---

## 3) 全量验证

本地/当前环境验证：

```bash
bash scripts/verify_all.sh
```

Docker 环境专项验证：

```bash
bash scripts/verify_docker.sh
```

---

## 4) 常见故障排查

### A. Docker daemon 无法连接
报错示例：`permission denied ... docker.sock`

处理：
1. 确认 Docker Desktop 已启动并完成初始化
2. 在本机终端执行 `docker info`
3. 若仍失败，重启 Docker Desktop

### B. 镜像拉取超时
报错示例：`context deadline exceeded` / `i/o timeout`

处理：
1. 重试 `bash scripts/docker_up.sh`（脚本已内置重试）
2. 配置镜像加速
3. 使用可访问的 `PYTHON_BASE_IMAGE`

### C. 端口冲突
报错示例：`bind: address already in use`

处理：
1. 修改端口环境变量后重启：

```bash
REDIS_PORT=6381 POSTGRES_PORT=5433 bash scripts/docker_up.sh
```

2. 或停止占用端口的本地服务

---

## 5) 发布前检查（V3 上线清单）

### 5.1 配置确认

确保 `.env` 已设置并生效：

```env
KERNEL_ORCHESTRATOR_VERSION=v3
KERNEL_FUSION_ENABLED=true
KERNEL_CRITIC_ENABLED=true
KERNEL_CRITIC_MAX_RETRY=2
```

### 5.2 外部 Key 校验

- `SERPER_API_KEY`（联网检索）
- `WEATHER_API_KEY`（天气工具）
- LLM 相关 API Key（QUERY/PLANNING/COMPRESS）

### 5.3 服务健康

```bash
bash restart.sh
```

检查：
- 前端：`http://localhost:14108`
- 后端：`http://localhost:14101`
- Swagger：`http://localhost:14101/docs`

### 5.4 核心链路冒烟

至少验证 4 条：
1. 普通问答可返回
2. 实时问题触发联网检索
3. 时间问题触发 `get_current_time`
4. 天气问题触发 `get_weather`

### 5.5 可观测项确认

- 推理链可显示执行过程
- DAG 可展开查看节点
- 有联网结果时，回答下方有 `Sources`

### 5.6 V3 元数据确认

在响应 metadata 中确认存在：
- `orchestrator_version = v3`
- `fusion`
- `critic`

### 5.7 冲突/低置信度行为验证

- 冲突场景下能看到 `fusion.conflicts`
- 低置信度时出现不确定性提示（若 critic 生效）

### 5.8 全量验证

当前环境验证：

```bash
bash scripts/verify_all.sh
```

Docker 专项验证：

```bash
bash scripts/verify_all_docker.sh
```

### 5.9 回滚预案验证

若需回滚，设置：

```env
KERNEL_ORCHESTRATOR_VERSION=v2
KERNEL_FUSION_ENABLED=false
KERNEL_CRITIC_ENABLED=false
```

然后：

```bash
bash restart.sh
```

### 5.10 发布记录

发布单至少记录：
- 变更摘要
- 风险点
- 回滚命令
- 负责人
- 时间窗口

---

## 6) 自动化发布前检查脚本（建议）

```bash
bash scripts/preflight_release.sh
```

该脚本会检查：
- 关键端口占用
- Python 环境
- `.env` 存在性
- 全量验证脚本
- API 健康检查
