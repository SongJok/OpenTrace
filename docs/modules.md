## 7. 核心模块详解

### 7.1 API 网关 (gateway/api_gateway/main.py)

FastAPI 应用入口，负责：
- CORS 配置（允许所有来源，开发环境）
- 生命周期管理（startup/shutdown）
- 路由注册（auth / chat / conversations / health / feedback / admin）
- OpenTelemetry 仪表化（可选）
- Prometheus `/metrics` 端点

### 7.2 认证模块 (routers/auth.py)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/register` | POST | 注册新用户，返回 JWT |
| `/api/v1/auth/token` | POST | OAuth2 表单登录（Swagger 用） |
| `/api/v1/auth/login` | POST | JSON 登录（前端用） |
| `/api/v1/auth/me` | GET | 当前用户信息 |

JWT 配置：算法 HS256，默认 10080 分钟（7天）

### 7.3 对话模块 (routers/chat.py)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/chat` | POST | AI 对话（stream=true 为 SSE） |

SSE 流程：
1. 安全检查（Guardrails.check_input）
2. 确保会话存在（_ensure_session）
3. ModelGateway.stream() 逐 token 输出
4. 每个 token 包装为 `data: {"delta": "...", "done": false}`
5. 完成后调用 _save_trace 持久化到 TraceLog
6. 发送 `data: {"done": true}`

### 7.4 模型网关 (model/model_gateway/gateway.py)

- 支持多个 LLM 候选（query / compress / planning 角色）
- 熔断器（circuit breaker）：失败 3 次开路，30 秒后半开
- 自动重试（tenacity：最多 3 次，指数退避）
- Qwen3 特殊处理：`extra_body={"enable_thinking": False}`
- httpx `trust_env=False`：绕过无效代理

### 7.5 记忆系统 (memory/)

| 类型 | 存储 | 用途 |
|------|------|------|
| WorkingMemory | Redis DB22 | 当前会话上下文（TTL 2小时）|
| EpisodicMemory | PostgreSQL | 历史对话记录 |
| SemanticMemory | pgvector | 知识库向量检索 |
| ProceduralMemory | PostgreSQL | 技能/工作流模板 |

### 7.6 安全层 (safety/)

**Guardrails**
- 攻击模式：hack/exploit/sql injection/rm -rf/jailbreak 等
- PII 检测：email/phone_cn/phone_intl/credit_card/id_cn
- 输出脱敏：将 PII 替换为 `[EMAIL_REDACTED]` 等

**PolicyEngine**
- 速率限制：基于 Redis 滑动窗口
- 内容策略：可配置允许/拒绝规则

### 7.7 前端状态管理

**useAuthStore (Zustand + persist)**
```typescript
{ token, userId, email, displayName, login(), logout() }
```
- 持久化到 localStorage key: `opentrace-auth`

**useChatStore (Zustand)**
```typescript
{ conversations[], activeId, messages{}, streaming,
  appendMessage(), updateLastMessage(), finalizeStreaming() }
```
- SSE 流式接收：每个 delta 追加到最后一条 assistant 消息
