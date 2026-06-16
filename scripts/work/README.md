# OpenTrace 本地开发启停

## 推荐：一条命令启动全栈

```bash
bash start-dev.sh
# 或
bash scripts/work/dev-boot-all-in-one.sh
```

将自动完成：

1. 若无 `.env`，从 `.env.example` 生成并写入本地 Docker 常用连接串  
2. 启动 **postgres + redis + api + agent-worker**（Docker）  
3. 若缺少表结构，在 API 容器内执行 **`alembic upgrade head`**  
4. 启动 **Vite 前端**（默认 `http://127.0.0.1:14108`）  

关闭全栈：

```bash
bash scripts/work/dev-stop-all.sh
```

## 脚本一览

| 脚本 | 说明 |
|------|------|
| **`dev-boot-all-in-one.sh`** | 全栈一键启动（后端 + 前端） |
| **`dev-stop-all.sh`** | 全栈关闭 |
| `backend-boot-all-in-one.sh` | 仅后端 Docker + 迁移 |
| `backend-start.sh` / `backend-stop.sh` / `backend-restart.sh` | 后端分步 |
| `frontend-boot-all-in-one.sh` | 仅前端 |
| `frontend-start.sh` / `frontend-stop.sh` | 前端分步 |
| `lib.sh` | 公共函数（`.env`、迁移、健康检查） |

根目录 **`start-dev.sh`** 为全栈入口；**`start.sh` / `stop.sh` / `restart.sh`** 仍为 Docker 后端快捷方式（与 `backend-*` 类似，但不自动拉起前端、不自动迁移）。

## 前置条件

- **Docker Desktop**（或 docker + compose）已运行  
- **Node.js 18+**、**npm**（仅前端）  
- 首次使用建议配置 `.env` 中至少一个 LLM 的 `DEFAULT_LLM_*_API_KEY`（否则复杂对话可能离线降级；L0 问候/帮助仍可用）

## 默认端口

| 服务 | 端口 |
|------|------|
| API | 14100 |
| 前端 | 14108 |
| PostgreSQL（宿主机） | 5432 |
| Redis（宿主机） | 6380 |

## 常用变体

```bash
# 仅后端（适合只调 API）
bash scripts/work/dev-boot-all-in-one.sh --backend-only

# 仅前端（需后端已起）
bash scripts/work/dev-boot-all-in-one.sh --frontend-only

# 可观测性（Prometheus + Jaeger）
bash start-dev.sh --with-observability

# 清空 Docker 数据卷后停止
bash scripts/work/dev-stop-all.sh --volumes
```

## 排障

```bash
docker compose ps
bash scripts/docker_logs.sh api
bash scripts/docker_logs.sh agent-worker
curl -s http://127.0.0.1:14100/api/v1/health/deps | python3 -m json.tool
```

手动迁移：`docker compose exec -T api alembic upgrade head`