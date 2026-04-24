# OpenTrace Docker 脚本执行流程说明

本文档说明：在 **Docker 模式** 下，项目启动、验证、清理、停止的标准流程与注意事项。

---

## 一、脚本总览（统一 Docker 模式）

- `bash start.sh`  
  统一启动入口（内部调用 `scripts/docker_up.sh`）

- `bash stop.sh`  
  统一停止入口（内部调用 `scripts/docker_down.sh`）

- `bash restart.sh`  
  统一重启入口（先 stop 再 start）

- `bash scripts/docker_up.sh [--with-observability]`  
  直接 Docker 启动，支持可选观测组件

- `bash scripts/docker_down.sh [--volumes]`  
  停止 Docker 容器，可选删除卷

- `bash scripts/docker_logs.sh [service]`  
  查看日志（可指定服务：`api/postgres/redis`）

- `bash scripts/verify_e2e.sh`  
  E2E 验收（含 ui-settings round-trip）

- `bash scripts/verify_docker.sh`  
  Docker 环境专项验证（daemon/compose/health/verify_all）

- `bash scripts/verify_all.sh`  
  全量验证（本机模式：error envelope + e2e + kernel + unittest）

- `bash scripts/verify_all_docker.sh`  
  全量验证（纯 Docker 模式：unittest 在 api 容器内执行）

- `bash scripts/preflight_release.sh`  
  发布前预检查

- `bash scripts/clean_session.sh [--with-users]`  
  清理会话和记忆相关数据，恢复初始状态

---

## 二、推荐执行顺序（Docker）

### 1. 启动

```bash
bash start.sh
```

可选带观测组件：

```bash
bash start.sh --with-observability
```

### 2. 查看服务状态与日志

```bash
docker compose ps
bash scripts/docker_logs.sh api
```

### 3. 执行验证

最小验证：

```bash
bash scripts/verify_e2e.sh
```

全量验证（推荐：纯 Docker 模式）：

```bash
bash scripts/verify_all_docker.sh
```

全量验证（本机模式）：

```bash
bash scripts/verify_all.sh
```

Docker专项验证：

```bash
bash scripts/verify_docker.sh
```

### 4. 清理会话/记忆（如需回归初始态）

```bash
bash scripts/clean_session.sh
```

> 如需连用户一起清理：

```bash
bash scripts/clean_session.sh --with-users
```

### 5. 停止

```bash
bash stop.sh
```

需要同时删卷（彻底清空数据库卷）时：

```bash
bash stop.sh --volumes
```

---

## 三、注意事项

1. **必须先确保 Docker Desktop 正常运行**
   - `docker info` 能正常返回

2. **镜像拉取超时**
   - 脚本已内置重试；若仍失败，检查网络或配置镜像加速

3. **端口冲突**
   - PostgreSQL/Redis 端口可通过环境变量覆盖：
     - `POSTGRES_PORT`
     - `REDIS_PORT`

4. **新增表结构后**
   - 请执行数据库迁移后再验证：
     - `alembic upgrade head`

5. **clean_session.sh 默认不删除用户**
   - 仅清理会话、记忆、任务、审计、文档等业务数据
   - 使用 `--with-users` 才会删除用户

6. **验证建议**
   - 开发阶段：`verify_e2e.sh`
   - 提交/发布前：`verify_all.sh` + `preflight_release.sh`

---

## 四、故障快速处理

- 服务未就绪：

```bash
bash scripts/docker_logs.sh api
```

- 需要完整重置：

```bash
bash stop.sh --volumes
bash start.sh
```

- 清理业务数据回到初始业务态：

```bash
bash scripts/clean_session.sh
```
