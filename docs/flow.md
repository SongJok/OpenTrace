## 6. 请求流水图

### 6.1 登录流程

```
用户      前端(14108)    后端(14101)    PostgreSQL
 │             │              │               │
 │─输入邮密────▶│              │               │
 │             │─POST /login──▶│               │
 │             │              │─SELECT users──▶│
 │             │              │◀──User record──│
 │             │              │ bcrypt.verify  │
 │             │              │ jwt.encode     │
 │             │◀─200 {token}─│               │
 │             │ Zustand持久化 │               │
 │◀─跳转 /─────│              │               │
```

### 6.2 SSE 流式对话

```
用户  前端(14108)  后端(14101)   Safety  ModelGateway  DashScope
 │        │            │            │           │           │
 │─发消息──▶│            │            │           │           │
 │        │─POST /chat──▶│            │           │           │
 │        │  stream=true │            │           │           │
 │        │            │─check_input─▶│           │           │
 │        │            │◀─ allowed ───│           │           │
 │        │            │─ensure_session(PG)        │           │
 │        │            │─────────────────────────▶stream()   │
 │        │            │                          │─POST──────▶│
 │        │  SSE data  │◀─────────────────── chunk │◀──chunk───│
 │◀─delta─│◀─data:json─│                          │           │
 │        │  (逐token)  │◀─────────────────── chunk │◀──chunk───│
 │◀─delta─│◀─data:json─│                          │           │
 │        │            │◀──────────── done ────────│◀──[DONE]──│
 │        │            │─_save_trace(PG)           │           │
 │        │◀─done:true─│                          │           │
 │        │ finalizeStreaming()                    │           │
```

### 6.3 会话列表加载

```
前端          后端           PostgreSQL
  │              │                │
  │─GET /conversations─▶│          │
  │  Authorization: JWT  │          │
  │              │─verify JWT      │
  │              │─SELECT chat_sessions─▶│
  │              │  WHERE user_id=X     │
  │              │  ORDER BY last_active│
  │              │◀─rows─────────────────│
  │◀─200 [{...}]─│                │
  │ Sidebar渲染  │                │
```

### 6.4 新建会话并发消息

```
前端         后端
  │            │
  │─POST /conversations─▶│
  │◀─{id, title}──────────│  新 ChatSession 写入 PG
  │                       │
  │─POST /chat ───────────▶│
  │  {query, session_id}  │
  │  stream: true         │
  │                       │  _ensure_session: 已存在
  │◀─SSE stream───────────│  → LLM → 流式输出
  │                       │  → _save_trace (TraceLog)
```
