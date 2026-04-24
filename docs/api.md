## 8. API 接口文档

完整 Swagger UI: http://localhost:14101/docs

基础 URL: `http://localhost:14101/api/v1`

所有需要认证的接口需在请求头携带:
```
Authorization: Bearer <token>
```

---

### 认证接口 `/auth`

#### POST /auth/login — JSON 登录
```json
// 请求
{ "email": "songts@tuwan.com", "password": "123456" }

// 响应 200
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user_id": "10d9b603-0555-4200-9b2e-2abd79708d73",
  "email": "songts@tuwan.com",
  "display_name": "Song TS"
}
```

#### POST /auth/register — 注册
```json
// 请求
{ "email": "new@example.com", "password": "pass123", "display_name": "姓名" }
// 响应: 同 login
```

#### POST /auth/token — OAuth2 表单登录 (Swagger 用)
```
Content-Type: application/x-www-form-urlencoded
username=songts@tuwan.com&password=123456
```

#### GET /auth/me — 当前用户信息
```json
// 响应 200
{
  "user_id": "10d9b603...",
  "email": "songts@tuwan.com",
  "display_name": "Song TS",
  "is_superuser": true,
  "created_at": "2026-03-30T14:52:49.658000+00:00"
}
```

---

### 对话接口 `/chat`

#### POST /chat — AI 对话
```json
// 请求
{
  "query": "你好，介绍一下自己",
  "session_id": "可选-UUID",
  "stream": true
}

// 响应 (stream=false) 200
{
  "session_id": "uuid",
  "content": "我是 OpenTrace AI 助手...",
  "decision_type": "direct",
  "validation_score": 1.0,
  "passed_validation": true
}

// 响应 (stream=true) Content-Type: text/event-stream
data: {"session_id": "uuid", "delta": "我是", "done": false}
data: {"session_id": "uuid", "delta": " OpenTrace", "done": false}
...
data: {"session_id": "uuid", "delta": "", "done": true}

// 错误响应 503
{"detail": "LLM service unavailable: Connection error."}
```

---

### 会话接口 `/conversations`

#### GET /conversations — 会话列表
```json
// 响应 200
[
  {
    "id": "uuid",
    "title": "你好，介绍一下",
    "turn_count": 3,
    "created_at": "2026-03-30T14:00:00Z",
    "last_active": "2026-03-30T15:30:00Z"
  }
]
```

#### POST /conversations — 创建会话
```json
// 响应 200
{
  "id": "new-uuid",
  "title": "New conversation",
  "turn_count": 0,
  "created_at": "...",
  "last_active": "..."
}
```

#### DELETE /conversations/{id} — 删除会话
```json
// 响应 200
{ "deleted": true }
```

#### GET /conversations/{id}/messages — 消息历史
```json
// 响应 200
[
  { "id": "xxx_q", "role": "user",      "content": "你好", "created_at": "..." },
  { "id": "xxx_a", "role": "assistant", "content": "你好！我是...", "created_at": "..." }
]
```

---

### 其他接口

#### GET /health — 健康检查
```json
{
  "status": "ok",
  "service": "opentrace",
  "version": "0.1.0",
  "uptime_seconds": 3600.5,
  "environment": "development"
}
```

#### GET /metrics — Prometheus 指标
```
Content-Type: text/plain
opentrace_http_requests_total{method="POST",endpoint="/api/v1/chat",status="200"} 42
...
```
