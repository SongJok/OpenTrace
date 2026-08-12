# 内存系统 (Memory) 模块

## 1. 模块概述

**内存系统**是 OpenTrace 系统的记忆管理核心，采用分层记忆架构（工作记忆、情景记忆、语义记忆）来存储和检索会话信息。其核心价值在于支持长对话上下文保持、用户偏好记忆和知识积累，使 AI 能够记住历史对话和用户偏好，提供更个性化的交互体验。

### 当前在线主动记忆主链路

在线 Responses 主链路在每个 Response 完成后，由 Worker 调用
`kernel/agent_loop/memory_learner.py`。用户不需要说“请记住”，系统也会主动识别：

- 用户直接陈述的姓名、职业等稳定身份事实；
- 长期回答偏好和默认输出方式；
- 长期目标、职责、重复工作流程、个人术语、审批习惯和常用模板；
- 当前工作区的稳定技术或业务约定。

确定性规则命中且置信度足够高的低风险候选会自动写入 `UserMemory`，并记录来源
Response、证据和 `learning_mode=proactive`。模型补充发现、较弱习惯或与旧记忆冲突的
候选只进入记忆收件箱，用户确认后才会生效。明确要求记住的内容使用
`learning_mode=explicit` 并保持最高优先级。

主动学习始终受以下边界约束：

- `memory_mode=disabled`、临时会话、用户关闭学习或 Assistant Profile 禁止学习时不写入；
- 健康、财务、身份号码、联系方式、认证信息、密钥及一次性请求不会持久化；
- user、tenant、workspace、conversation 作用域必须同时隔离；
- 同一稳定 key 的主动冲突不会静默覆盖，而是进入收件箱等待确认；
- 不同 Response 对同一内容的重复观察会强化原记忆并追加证据，不创建重复节点；
- 具名遗忘只失效当前有效 scope 内精确主题匹配的记忆；模糊全量删除仍在 Memories 页面确认；
- “不要记住”以及一次性表达不会被确定性规则或模型补充提取重新写回；
- 用户可在 Memories 页面查看来源、编辑、禁用、置顶或删除记忆。
- 日历等会变化的业务事实不复制为长期 `UserMemory`：当前安排来自 `CalendarEvent`，过期后
  动态成为历史经历，取消后默认不召回，改期/取消过程由只追加修订账本按需提供证据。

## 2. 核心职责

- **工作记忆**：短期会话记忆，存储当前对话轮次
- **情景记忆**：长期事件记忆，存储历史对话记录
- **语义记忆**：结构化知识记忆，存储用户偏好和知识
- **记忆路由**：统一的记忆检索和存储入口
- **记忆演化**：记忆的自动演化和更新

## 3. 关键策略与算法

### 策略落地过程

**当初设计时为什么选择这个方案**

在设计内存系统时，团队面临以下技术选择：

1. **单一记忆存储**：所有记忆存储在一个地方
2. **分层记忆架构**：工作记忆、情景记忆、语义记忆分离

选择分层记忆架构的原因：
- **性能优化**：工作记忆使用内存存储，访问速度快
- **持久性**：情景记忆和语义记忆持久化到 Redis/数据库
- **可扩展性**：不同类型记忆可以独立扩展
- **语义检索**：语义记忆支持向量检索

**实现时的关键代码片段**

工作记忆的核心实现位于 `working_memory.py`：

```python
class WorkingMemory:
    def __init__(self, max_turns: int = 32, session_id: str | None = None) -> None:
        self._turns: deque[MemoryEntry] = deque(maxlen=max_turns)  # 环形缓冲区
        self._scratchpad: dict[str, Any] = {}  # 临时变量存储
        self._session_id: str | None = session_id
    
    def add_turn(self, role: str, content: str | None = None, **metadata) -> None:
        self._turns.append(MemoryEntry(
            role=role, content=content, metadata=metadata
        ))
        if self._session_id:
            self._schedule_redis_sync()  # 异步同步到 Redis
    
    async def _sync_to_redis(self) -> None:
        """异步同步到 Redis，确保进程重启后可以恢复"""
        if not self._session_id:
            return
        try:
            redis = await get_session_redis()
            pipe = redis.pipeline()
            # 写入对话轮次
            for entry in self._turns:
                pipe.rpush(self._turns_key(self._session_id), json.dumps({...}))
            pipe.expire(self._turns_key(self._session_id), _WM_TTL)
            # 写入 scratchpad
            for k, v in self._scratchpad.items():
                pipe.hset(self._scratch_key(self._session_id), k, json.dumps(v))
            pipe.expire(self._scratch_key(self._session_id), _WM_TTL)
            await pipe.execute()
        except Exception:
            pass  # Redis 不可用时静默失败
```

**测试时发现的调整**

在测试阶段发现以下问题并进行了调整：

1. **内存泄漏**：工作记忆在进程内存中无限增长。调整方案：使用 `deque(maxlen=32)` 实现环形缓冲区，自动淘汰旧数据。

2. **进程重启丢失**：工作记忆只存储在内存中，进程重启后丢失。调整方案：引入 Redis 持久化，异步同步工作记忆状态。

3. **记忆检索效率低**：直接遍历所有记忆条目进行匹配。调整方案：引入 MemoryRouter 统一路由，支持向量检索。

4. **并发问题**：多个请求同时访问工作记忆导致数据不一致。调整方案：使用进程内字典缓存，通过 Redis 进行跨进程同步。

### 分层记忆架构

内存系统包含四个层次：

```python
# 1. Working Memory - 短期会话记忆（进程内，快速访问）
# 2. Episodic Memory - 情景记忆（Redis，历史事件）
# 3. Semantic Memory - 语义记忆（数据库+向量索引，结构化知识）
# 4. Procedural Memory - 过程记忆（存储技能和流程）

# MemoryRouter 统一路由
class MemoryRouter:
    async def retrieve(self, query: str, episodic_chunks: list[str], 
                      keyword_chunks: list[str], top_k: int = 8) -> list[MemoryChunk]:
        # 综合检索多个记忆源
        results = []
        
        # 语义记忆检索（向量匹配）
        semantic_results = await self._semantic_memory.retrieve(query, top_k)
        results.extend(semantic_results)
        
        # 情景记忆检索（关键词匹配）
        episodic_results = await self._episodic_memory.retrieve(query, top_k)
        results.extend(episodic_results)
        
        # 排序去重
        results = sorted(results, key=lambda x: x.score, reverse=True)[:top_k]
        return results
```

### 记忆恢复策略

进程重启后的记忆恢复：

```python
async def load_or_create_session_memory(session_id: str, max_turns: int = 32) -> WorkingMemory:
    """从 Redis 恢复工作记忆，如果失败则创建新的"""
    memory = _SESSION_WORKING_MEMORIES.get(session_id)
    if memory is not None:
        return memory
    
    # 尝试从 Redis 恢复
    try:
        memory = await WorkingMemory.load_from_redis(session_id, max_turns=max_turns)
    except Exception:
        # 恢复失败，创建新的空记忆
        memory = WorkingMemory(max_turns=max_turns, session_id=session_id)
    
    _SESSION_WORKING_MEMORIES[session_id] = memory
    return memory
```

## 4. 输入/输出/依赖的外部服务

### 输入

| 输入参数 | 类型 | 说明 |
|---------|------|------|
| `session_id` | str | 会话 ID |
| `query` | str | 查询文本 |
| `user_id` | str | 用户 ID |
| `top_k` | int | 返回数量 |

### 输出

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `MemoryChunk` | list | 记忆片段列表 |
| `content` | str | 记忆内容 |
| `score` | float | 匹配分数 |
| `source` | str | 记忆来源 |

### 依赖服务

| 依赖模块 | 路径 | 职责 |
|---------|------|------|
| Redis | `infra/cache/redis_client.py` | 会话级存储 |
| PostgreSQL | `infra/storage/database.py` | 持久化存储 |
| Embedding | `model/embedding/base.py` | 向量嵌入 |

## 5. 关键函数/类说明

### 5.1 WorkingMemory 类

**职责**：短期会话记忆，存储当前对话轮次

```python
class WorkingMemory:
    def __init__(self, max_turns: int = 32, session_id: str | None = None) -> None:
        self._turns: deque[MemoryEntry] = deque(maxlen=max_turns)
        self._scratchpad: dict[str, Any] = {}
        self._session_id = session_id
    
    def add_turn(self, role: str, content: str | None = None, **metadata) -> None:
        # 添加对话轮次
    
    def get_turns(self, last_n: int | None = None) -> list[MemoryEntry]:
        # 获取最近的对话轮次
    
    def to_messages(self) -> list[dict[str, Any]]:
        # 转换为 OpenAI 格式的消息列表
    
    def set(self, key: str, value: Any) -> None:
        # 设置临时变量
    
    def get(self, key: str, default: Any = None) -> Any:
        # 获取临时变量
```

### 5.2 MemoryEntry 类

**职责**：单个记忆条目

```python
@dataclass
class MemoryEntry:
    role: str  # user | assistant | system | tool
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 5.3 EpisodicMemory 类

**职责**：情景记忆，存储历史事件

```python
class EpisodicMemory:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
    
    async def record(self, event_type: str, content: str) -> None:
        # 记录事件
    
    async def recall(self, last_n: int = 20) -> list[dict[str, Any]]:
        # 回忆最近的事件
```

### 5.4 MemoryRouter 类

**职责**：统一的记忆检索和存储入口

```python
class MemoryRouter:
    async def retrieve(self, query: str, episodic_chunks: list[str], 
                      keyword_chunks: list[str], top_k: int = 8) -> list[MemoryChunk]:
        # 综合检索多个记忆源
    
    async def store(self, session_id: str, query: str, answer: str, metadata: dict) -> None:
        # 存储记忆
```

## 6. 配置项说明

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `max_turns` | 工作记忆最大轮次 | 32 |
| `_WM_TTL` | 工作记忆 Redis TTL | 86400 秒（24小时） |
| `semantic_parse_cache_ttl` | 语义解析缓存 TTL | 86400 秒 |

## 7. 异常场景与容错设计

### 7.1 异常场景

| 场景 | 描述 | 处理策略 |
|------|------|---------|
| Redis 不可用 | 无法同步工作记忆 | 使用进程内存继续，记录警告 |
| 内存恢复失败 | 从 Redis 恢复时出错 | 创建新的空记忆 |
| 记忆检索失败 | 向量检索失败 | 返回空结果，不影响主流程 |
| 会话不存在 | 访问不存在的会话 | 创建新的工作记忆 |

### 7.2 容错机制

```python
# Redis 同步的异常处理
async def _sync_to_redis(self) -> None:
    if not self._session_id:
        return
    try:
        redis = await get_session_redis()
        # ... 同步逻辑
        await pipe.execute()
    except Exception:
        pass  # best-effort，失败不影响主流程
```

### 7.3 优雅降级

```python
# 记忆恢复的优雅降级
async def load_or_create_session_memory(session_id: str) -> WorkingMemory:
    try:
        # 尝试从 Redis 恢复
        memory = await WorkingMemory.load_from_redis(session_id)
    except Exception:
        # 失败时创建新的空记忆
        memory = WorkingMemory(session_id=session_id)
    return memory
```

## 8. 性能注意事项

### 8.1 性能优化策略

1. **环形缓冲区**：使用 `deque(maxlen=32)` 自动淘汰旧数据
2. **异步同步**：Redis 同步异步执行，不阻塞主流程
3. **进程内缓存**：工作记忆存储在进程内存中，快速访问
4. **批量操作**：Redis 操作使用 pipeline 批量执行

### 8.2 监控指标

| 指标 | 说明 |
|------|------|
| `memory_context.hits` | 记忆上下文命中数 |
| `memory.sync_errors` | Redis 同步错误数 |

### 8.3 潜在瓶颈

- 大量会话时的内存占用
- Redis 的网络延迟
- 向量检索的计算开销

## 9. 拓扑图

```
用户请求
    │
    ▼
┌─────────────────────────────────────────────────────┐
│               MemoryRouter                         │
│          统一记忆路由入口                           │
└─────────────────────────────────────────────────────┘
    │
    ├──► [检索路径]
    │       │
    │       ├──► WorkingMemory (进程内)
    │       │       └──► 最近对话轮次
    │       │
    │       ├──► EpisodicMemory (Redis)
    │       │       └──► 历史事件记录
    │       │
    │       └──► SemanticMemory (DB+Vector)
    │               └──► 用户偏好/知识
    │
    └──► [存储路径]
            │
            ├──► WorkingMemory.add_turn()
            │       └──► 异步同步到 Redis
            │
            ├──► EpisodicMemory.record()
            │
            └──► SemanticMemory.store()
```

## 10. 完整架构和策略过程

### 10.1 架构层次

```
┌─────────────────────────────────────────────────────────┐
│                    MemoryRouter                        │  ← 统一入口
└─────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ WorkingMemory   │  │ EpisodicMemory  │  │ SemanticMemory  │
│ (进程内缓存)    │  │  (Redis)       │  │  (DB+Vector)   │
│ 短期会话记忆    │  │ 情景记忆       │  │ 语义记忆       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Redis 持久化  │  │   Redis 存储    │  │ PostgreSQL     │
│   (异步)        │  │                 │  │ + Vector Index │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### 10.2 执行流程

**检索流程**：
1. 用户请求进入 MemoryRouter
2. 并行查询工作记忆、情景记忆、语义记忆
3. 合并结果并按分数排序
4. 返回 top_k 个记忆片段

**存储流程**：
1. 对话结束后，调用 MemoryRouter.store()
2. 添加到工作记忆（进程内）
3. 异步同步到 Redis
4. 异步写入情景记忆和语义记忆

**恢复流程**：
1. 新会话开始时，尝试从 Redis 恢复工作记忆
2. 如果恢复失败，创建新的空记忆
3. 后续操作会自动同步到 Redis

### 10.3 设计原则

1. **分层架构**：不同层次的记忆有不同的存储策略
2. **异步优先**：持久化操作异步执行，不阻塞响应
3. **优雅降级**：任一存储层失败不影响整体功能
4. **进程内缓存**：工作记忆保持在内存中，快速访问
5. **可恢复性**：进程重启后可从 Redis 恢复状态

---

**相关文件**：
- `memory/working_memory/working_memory.py` - 工作记忆
- `memory/episodic_memory/episodic_memory.py` - 情景记忆
- `memory/semantic_memory/semantic_memory.py` - 语义记忆
- `memory/memory_router/router.py` - 记忆路由
- `memory/procedural_memory/procedural_memory.py` - 过程记忆
- `infra/cache/redis_client.py` - Redis 客户端
