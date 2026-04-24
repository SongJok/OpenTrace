## 10. 环境配置说明

配置文件: `.env`（从 `.env.example` 复制）

### 必填配置

```env
# 数据库 (PostgreSQL)
DATABASE_URL=postgresql://postgres:password@localhost:5432/opentrace_v2

# Redis
REDIS_URL=redis://localhost:6379/20

# LLM - 查询模型
DEFAULT_LLM_QUERY_MODEL=qwen3-32b
DEFAULT_LLM_QUERY_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEFAULT_LLM_QUERY_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# JWT 密钥
JWT_SECRET=your-secret-key-at-least-32-chars
```

### 可选配置

```env
# LLM - 压缩模型（摘要/压缩）
DEFAULT_LLM_COMPRESS_MODEL=qwen3-14b
DEFAULT_LLM_COMPRESS_API_KEY=sk-xxx

# LLM - 规划模型
DEFAULT_LLM_PLANING_MODEL=qwen3-8b
DEFAULT_LLM_PLANING_API_KEY=sk-xxx

# 网络搜索（内置工具 web_search 需要）
SERPER_API_KEY=your-serper-key

# OpenTelemetry（可选）
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
TRACE_ENABLED=true

# SMTP 邮件
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USER=your@163.com
SMTP_PASS=your-auth-code
```

### Redis DB 分区说明

| DB | 用途 | 配置键 |
|----|------|--------|
| 20 | 会话 Session | REDIS_SESSION_DB |
| 21 | 缓存 Cache | REDIS_CACHE_DB |
| 22 | 记忆 Memory | REDIS_MEMORY_DB |
| 23 | 队列 Queue | REDIS_QUEUE_DB |
| 24 | 速率限制 | REDIS_RATE_LIMIT_DB |
| 25 | 发布订阅 | REDIS_PUBSUB_DB |

### 端口说明

| 服务 | 默认端口 | 配置键 |
|------|----------|--------|
| 后端 API | 14101 | GATEWAY_PORT |
| 前端 | 14108 | FRONTEND_PORT |
| PostgreSQL | 5432 | DATABASE_URL |
| Redis | 6379 | REDIS_URL |

## 11. 数据库模型

### users 表
```sql
CREATE TABLE users (
  id            VARCHAR(36) PRIMARY KEY,
  email         VARCHAR(255) NOT NULL UNIQUE,
  hashed_password VARCHAR(255) NOT NULL,
  display_name  VARCHAR(100),
  is_active     BOOLEAN NOT NULL DEFAULT true,
  is_superuser  BOOLEAN NOT NULL DEFAULT false,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### chat_sessions 表
```sql
CREATE TABLE chat_sessions (
  id                VARCHAR(36) PRIMARY KEY,
  user_id           VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
  title             VARCHAR(255),
  turn_count        INTEGER NOT NULL DEFAULT 0,
  last_decision_type VARCHAR(50),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_active       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### trace_logs 表
```sql
CREATE TABLE trace_logs (
  id               VARCHAR(36) PRIMARY KEY,
  session_id       VARCHAR(36) REFERENCES chat_sessions(id) ON DELETE CASCADE,
  trace_id         VARCHAR(64),
  span_id          VARCHAR(32),
  query            TEXT NOT NULL,
  response         TEXT,
  decision_type    VARCHAR(50),
  validation_score FLOAT,
  latency_ms       INTEGER,
  model            VARCHAR(100),
  prompt_tokens    INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 12. 运维脚本

所有脚本位于 `scripts/` 目录：

| 脚本 | 用法 | 说明 |
|------|------|------|
| `start.sh` | `bash scripts/start.sh` | 一键启动后端+前端 |
| `stop.sh` | `bash scripts/stop.sh` | 一键停止所有服务 |
| `restart.sh` | `bash scripts/restart.sh` | 一键重启所有服务 |
| `seed_user.py` | `python scripts/seed_user.py` | 初始化数据库和默认用户 |
| `test_llm.py` | `python scripts/test_llm.py` | 测试 DashScope API 连通性 |

### 查看服务日志
```bash
tail -f /tmp/opentrace-backend.log   # 后端日志
tail -f /tmp/opentrace-frontend.log  # 前端日志
```

### Docker 部署
```bash
docker-compose up -d
```

### 数据库迁移
```bash
alembic revision --autogenerate -m "描述"
alembic upgrade head
```
