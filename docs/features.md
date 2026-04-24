## 3. 功能列表

### 用户认证
- [x] 注册（邮箱 + 密码）
- [x] 登录（JSON 接口 + OAuth2 表单）
- [x] JWT Token 认证（7 天有效期，localStorage 持久化）
- [x] 当前用户信息查询 `/api/v1/auth/me`

### AI 对话
- [x] 流式 SSE 对话（逐 token 输出）
- [x] 同步对话（一次性返回）
- [x] 会话管理（创建 / 列出 / 删除）
- [x] 消息历史记录（TraceLog 持久化）
- [x] 会话标题自动生成（首条消息前 60 字）
- [x] Markdown 渲染（代码高亮 + 复制按钮）
- [x] 流式光标动画 ▋ + 打字指示器
- [ ] 多模态（图片/文件）— 规划中
- [ ] 语音输入 — 规划中

### 安全与守卫
- [x] 攻击模式检测（SQL 注入、XSS、越狱等）
- [x] PII 检测与脱敏（手机号、邮箱、信用卡、身份证）
- [x] 策略引擎（速率限制、内容策略）
- [x] 审计日志

### Agent 运行时
- [x] BaseAgent 框架
- [x] Planner（任务规划）
- [x] Executor（工具执行）
- [x] Critic（质量评估）
- [x] Reflector（自我反思）
- [x] AgentMarket（Agent 注册与调度）

### 内置工具
- [x] `datetime` — 当前 UTC 时间
- [x] `calculator` — 数学表达式计算
- [x] `summarize` — 文本摘要
- [x] `web_search` — 网络搜索（需 Serper API Key）
- [x] `python_repl` — Python 代码执行

### 记忆系统
- [x] 工作记忆 WorkingMemory（Redis，当前会话上下文）
- [x] 情景记忆 EpisodicMemory（PostgreSQL，对话历史）
- [x] 语义记忆 SemanticMemory（pgvector，知识库向量检索）
- [x] 程序性记忆 ProceduralMemory（技能/工作流）
- [x] 统一记忆路由器 MemoryRouter

### 执行引擎
- [x] DAG 引擎（有向无环图任务调度）
- [x] 认知节点 CognitiveNode
- [x] 工作流引擎 WorkflowEngine
- [x] 工具路由器 ToolRouter
- [x] 沙箱执行环境 Sandbox

### 自我进化
- [x] 元学习 MetaLearner
- [x] 自我对弈 SelfPlay
- [x] 数据飞轮 DataFlywheel
- [x] 反馈收集 FeedbackCollector
- [x] 评估引擎 EvaluationEngine
- [x] 持续学习 ContinuousLearning

### 基础设施
- [x] 异步 PostgreSQL（SQLAlchemy 2.0 async + asyncpg）
- [x] Redis 多 DB 分区
  - DB 20: 会话（Session）
  - DB 21: 缓存（Cache）
  - DB 22: 记忆（Memory）
  - DB 23: 队列（Queue）
  - DB 24: 速率限制（Rate Limit）
  - DB 25: 发布订阅（PubSub）
- [x] 消息总线 MessageBus
- [x] 结构化日志 structlog
- [x] OpenTelemetry 链路追踪（可选）
- [x] Prometheus 指标采集（可选）
- [x] Docker 容器化 + Docker Compose
