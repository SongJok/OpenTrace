# 认知内核 (Cognitive Kernel) 模块

## 1. 模块概述

**认知内核**是 OpenTrace 系统的唯一中枢入口，负责协调所有认知能力的调度和执行。其核心价值在于实现多 Prompt 链执行流程，通过意图识别、任务规划、工具选择、推理生成、反思优化和质量门控等多个阶段，将用户请求转换为高质量的响应。

## 2. 核心职责

- **意图识别**：识别用户查询的意图类别和复杂程度
- **任务规划**：将复杂请求分解为可执行的子任务
- **工具选择**：选择合适的工具/插件来完成任务
- **推理生成**：生成最终响应
- **反思优化**：对响应进行质量优化
- **质量门控**：验证响应质量，确保输出可靠
- **记忆管理**：管理会话记忆和长期记忆

## 3. 关键策略与算法

### 策略落地过程

**当初设计时为什么选择这个方案**

在设计认知内核时，团队面临以下技术选择：

1. **单一 LLM 调用**：直接使用 LLM 生成响应
2. **多阶段管道**：意图识别 → 规划 → 工具选择 → 推理 → 反思

选择多阶段管道方案的原因：
- **性能优化**：意图识别和规划使用小模型，推理使用大模型
- **可解释性**：每个阶段都可以独立监控和调试
- **灵活性**：可以根据意图选择不同的处理路径
- **质量控制**：多个质量门控点确保输出质量

**实现时的关键代码片段**

核心执行流程位于 `cognitive_kernel.py` 的 `run` 方法：

```python
async def run(self, request: KernelRequest) -> KernelResponse:
    # V5 路由层
    if settings.kernel_v5_routing_enabled:
        # L0: 规则路由（零LLM，<1ms）
        if settings.kernel_l0_rule_router_enabled:
            l0_result = await self._get_l0_router().route(...)
            if l0_result.hit and l0_result.answer is not None:
                return KernelResponse(content=l0_result.answer, ...)
        
        # L0.5: 语义缓存
        if settings.kernel_semantic_cache_enabled:
            cached = await self._get_semantic_cache().lookup(...)
            if cached:
                return KernelResponse(content=cached.answer, ...)
        
        # L1: 复杂度引擎 + Tiny Router
        if settings.kernel_l1_tiny_router_enabled:
            complexity = self._get_complexity_engine().assess(...)
            if complexity.recommended_pipeline in ("L0", "L1"):
                l1_result = await self._get_tiny_router().route(...)
                return KernelResponse(content=l1_result.answer, ...)
    
    # 内存上下文注入
    memory_context = []
    if settings.kernel_memory_context_enabled:
        memory_chunks = await self._get_memory_router().retrieve(...)
        memory_context = [...]
    
    # ContextAssembler — 统一上下文组装
    if settings.kernel_context_composer_enabled:
        assembled_ctx = await self._get_context_composer().assemble(...)
    
    # 调用 V4 编排器
    orchestrator = CognitiveOrchestratorV4(...)
    resp = await orchestrator.process(OrchestratorV4Request(...))
    
    # 保存到语义缓存
    if settings.kernel_semantic_cache_enabled:
        await self._get_semantic_cache().store(...)
    
    # 保存到工作记忆和情景记忆
    if settings.kernel_memory_context_enabled:
        await self._save_to_memory(request.session_id, request.query, resp.content)
    
    return KernelResponse(
        content=resp.content,
        route=resp.route,
        validation_score=resp.validation_score,
        ...
    )
```

**测试时发现的调整**

在测试阶段发现以下问题并进行了调整：

1. **延迟过高**：原始实现中所有阶段串行执行。调整方案：引入 V5 路由层，增加多个快速路径（规则路由、语义缓存、Tiny Router）。

2. **内存上下文质量**：直接使用原始历史对话作为上下文效果不佳。调整方案：引入 ContextAssembler，对上下文进行压缩和摘要。

3. **上下文窗口限制**：长对话历史导致上下文过长。调整方案：实现上下文压缩策略，只保留最相关的对话历史。

4. **多轮对话一致性**：跨会话的上下文保持困难。调整方案：引入工作记忆（WorkingMemory）和情景记忆（EpisodicMemory）的分层记忆体系。

### V5 路由层策略

V5 路由层提供多级快速路径：

```python
# L0: 规则路由 — 零LLM，基于规则匹配
if settings.kernel_l0_rule_router_enabled:
    l0_result = await self._get_l0_router().route(
        request.query,
        sid,
        is_multi=is_multi,
        conversation_history=request.history,
    )
    if l0_result.hit and l0_result.answer is not None:
        # 命中规则，直接返回
        return KernelResponse(content=l0_result.answer, route="l0")

# L0.5: 语义缓存 — 基于语义相似度的缓存
if settings.kernel_semantic_cache_enabled:
    ctx_hash = _context_hash(request.history)
    cached = await self._get_semantic_cache().lookup(request.query, ctx_hash)
    if cached:
        return KernelResponse(content=cached.answer, route="semantic_cache")

# L1: Tiny Router — 使用小模型进行简单问答
if settings.kernel_l1_tiny_router_enabled:
    complexity = self._get_complexity_engine().assess(request.query)
    if complexity.recommended_pipeline in ("L0", "L1"):
        l1_result = await self._get_tiny_router().route(request.query, request.history)
        if l1_result.route != "complex":
            return KernelResponse(content=l1_result.answer, route=f"l1_{l1_result.route}")
```

### 上下文组装策略

`ContextAssembler` 对上下文进行智能组装：

```python
# 上下文组装
if settings.kernel_context_composer_enabled and request.history:
    assembler = get_context_assembler()
    tctx = TurnContext(
        query=request.query,
        session_id=request.session_id,
        user_id=request.user_id,
        recent_history=request.history,
        memory_context=memory_context,
        attachment_contexts=request.metadata.get("attachment_contexts", []),
        conversation_state=request.conversation_state,
        metadata=request.metadata,
    )
    assembled_ctx = await assembler.assemble(tctx)
    
    # 使用压缩后的历史
    effective_history = assembled_ctx.recent_turns if assembled_ctx.compressed else request.history
    conversation_summary = assembled_ctx.summary_block if assembled_ctx else ""
```

## 4. 输入/输出/依赖的外部服务

### 输入

| 输入参数 | 类型 | 说明 |
|---------|------|------|
| `query` | str | 用户查询文本 |
| `session_id` | str | 会话 ID |
| `user_id` | str | 用户 ID |
| `history` | list | 对话历史 |
| `stream` | bool | 是否流式输出 |
| `web_enabled` | bool | 是否启用联网搜索 |
| `metadata` | dict | 元数据 |
| `trace_ctx` | Any | 追踪上下文 |
| `conversation_state` | Any | 对话状态 |

### 输出

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `content` | str | 响应内容 |
| `session_id` | str | 会话 ID |
| `route` | str | 处理路径 |
| `validation_score` | float | 验证分数 |
| `passed_validation` | bool | 是否通过验证 |
| `hallucination_risk` | float | 幻觉风险 |
| `intent_category` | str | 意图类别 |
| `intent_complexity` | str | 意图复杂度 |
| `context_latency_ms` | int | 上下文延迟 |
| `total_latency_ms` | int | 总延迟 |
| `metadata` | dict | 元数据 |
| `state_patch` | dict | 状态补丁 |
| `result_refs` | list | 结果引用 |

### 依赖服务

| 依赖模块 | 路径 | 职责 |
|---------|------|------|
| L0RuleRouter | `kernel/query_router_v2.py` | 规则路由 |
| SemanticCache | `kernel/semantic_cache.py` | 语义缓存 |
| ComplexityEngine | `kernel/complexity_engine.py` | 复杂度评估 |
| TinyRouter | `kernel/tiny_router.py` | 轻量级路由 |
| MemoryRouter | `memory/memory_router/router.py` | 记忆路由 |
| ContextAssembler | `kernel/context_assembler.py` | 上下文组装 |
| CognitiveOrchestratorV4 | `kernel/orchestrator_v4.py` | V4 编排器 |
| SelfModel | `kernel/cognition/self_model.py` | 自我模型 |

## 5. 关键函数/类说明

### 5.1 CognitiveKernel 类

**职责**：认知内核的核心协调器

```python
class CognitiveKernel:
    def __init__(self, intent_engine=None, policy_engine=None, reasoning_engine=None, 
                 meta_cognition=None, memory_router=None):
        self._intent_engine = intent_engine
        self._policy_engine = policy_engine
        self._reasoning_engine = reasoning_engine
        self._meta_cognition = meta_cognition
        self._memory_router = memory_router
        self.self_model = SelfModel()
    
    async def run(self, request: KernelRequest) -> KernelResponse:
        # 核心执行逻辑
        ...
    
    async def stream(self, request: KernelRequest) -> AsyncIterator[dict]:
        # 流式输出
        ...
```

**关键方法**：
- `run()`: 同步执行入口
- `stream()`: 流式执行入口
- `_get_l0_router()`: 获取 L0 规则路由
- `_get_semantic_cache()`: 获取语义缓存
- `_get_complexity_engine()`: 获取复杂度引擎
- `_get_tiny_router()`: 获取 Tiny Router

### 5.2 KernelRequest 类

**职责**：封装内核请求参数

```python
@dataclass
class KernelRequest:
    query: str
    session_id: str = ""
    user_id: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    stream: bool = False
    web_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_ctx: Any = None
    conversation_state: Any = None
```

### 5.3 KernelResponse 类

**职责**：封装内核响应

```python
@dataclass
class KernelResponse:
    content: str
    session_id: str = ""
    route: str = "direct"
    validation_score: float = 1.0
    passed_validation: bool = True
    hallucination_risk: float = 0.0
    intent_category: str = "qa"
    intent_complexity: str = "simple"
    context_latency_ms: int = 0
    total_latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    state_patch: dict[str, Any] | None = None
    result_refs: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
```

### 5.4 路由层组件

**L0RuleRouter**：基于规则的快速路由（零 LLM 调用）

**SemanticCache**：基于语义相似度的响应缓存

**ComplexityEngine**：评估查询复杂度，推荐处理管道

**TinyRouter**：使用轻量级模型处理简单查询

## 6. 配置项说明

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `kernel_v5_routing_enabled` | 是否启用 V5 路由层 | True |
| `kernel_l0_rule_router_enabled` | 是否启用 L0 规则路由 | True |
| `kernel_semantic_cache_enabled` | 是否启用语义缓存 | True |
| `kernel_l1_tiny_router_enabled` | 是否启用 L1 Tiny Router | True |
| `kernel_memory_context_enabled` | 是否启用内存上下文 | True |
| `kernel_context_composer_enabled` | 是否启用上下文组装 | True |
| `kernel_agent_timeout_sec` | Agent 超时时间 | 60 |
| `kernel_agent_max_parallel` | 最大并行数 | 4 |

## 7. 异常场景与容错设计

### 7.1 异常场景

| 场景 | 描述 | 处理策略 |
|------|------|---------|
| 路由失败 | L0/L1 路由返回空结果 | 回退到完整编排器 |
| 内存获取失败 | Redis 不可用 | 使用空上下文继续执行 |
| 上下文组装失败 | ContextAssembler 异常 | 使用原始历史继续执行 |
| 编排器失败 | CognitiveOrchestratorV4 异常 | 返回错误响应 |
| LLM 服务不可用 | 模型网关异常 | 返回降级响应 |

### 7.2 容错机制

```python
# 内存获取的异常处理
try:
    memory_chunks = await self._get_memory_router().retrieve(
        query=request.query,
        episodic_chunks=episodic_chunks,
        keyword_chunks=keyword_chunks,
        top_k=8,
    )
    memory_context = [...]
except Exception as exc:
    logger.debug("MemoryRouter.retrieve failed", error=str(exc))
    memory_context = []  # 使用空上下文继续
```

### 7.3 自我模型保护

```python
# 能力评估和保护
intent = self._classify_intent_domain(request.query)
assessment = self.self_model.introspect(request.query, intent)

if assessment.level == CapabilityLevel.UNAVAILABLE:
    return KernelResponse(
        content=f"抱歉，我目前无法处理这类请求。{assessment.reasoning}",
        route="self_model_guard",
        validation_score=1.0,
        ...
    )
```

## 8. 性能注意事项

### 8.1 性能优化策略

1. **多级路由**：L0（规则）→ L0.5（缓存）→ L1（小模型）→ 完整编排器
2. **上下文压缩**：ContextAssembler 压缩历史对话
3. **异步记忆写入**：记忆写入异步执行，不阻塞响应
4. **缓存优先**：语义缓存减少重复计算

### 8.2 监控指标

| 指标 | 说明 |
|------|------|
| `total.latency_ms` | 总延迟 |
| `identity.cache_hit` | 身份缓存命中 |
| `memory_context.hits` | 内存上下文命中数 |
| `context.compressed` | 上下文是否被压缩 |
| `context.total_tokens` | 上下文总 token 数 |

### 8.3 潜在瓶颈

- LLM 调用是主要性能瓶颈
- 上下文组装在长对话时可能较慢
- 内存检索涉及多次 Redis 操作

## 9. 拓扑图

```
用户请求
    │
    ▼
┌─────────────────────────────────────────────────────┐
│           CognitiveKernel.run()                    │
└─────────────────────────────────────────────────────┘
    │
    ├──► [V5 路由层]
    │       │
    │       ├──► L0 Rule Router (零LLM)
    │       │       └──► 命中 → 直接返回
    │       │
    │       ├──► L0.5 Semantic Cache
    │       │       └──► 命中 → 直接返回
    │       │
    │       └──► L1 Tiny Router (小模型)
    │               └──► 简单 → 直接返回
    │
    ├──► [内存上下文注入]
    │       │
    │       ├──► Episodic Memory
    │       ├──► Working Memory
    │       └──► Semantic Memory
    │
    ├──► [ContextAssembler]
    │       │
    │       └──► 上下文压缩 + 摘要
    │
    ├──► [CognitiveOrchestratorV4]
    │       │
    │       └──► 完整推理管道
    │
    └──► [记忆写入] (异步)
            │
            ├──► Working Memory
            ├──► Episodic Memory
            └──► Semantic Cache
```

## 10. 完整架构和策略过程

### 10.1 架构层次

```
┌─────────────────────────────────────────────────────────┐
│                    用户请求入口                          │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    V5 路由层                            │  ← 快速路径
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ L0 Rule  │  │ L0.5     │  │ L1 Tiny  │            │
│  │ Router   │  │ Cache    │  │ Router   │            │
│  └──────────┘  └──────────┘  └──────────┘            │
└─────────────────────────────────────────────────────────┘
                              │ (未命中)
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    上下文层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ Memory   │→│ Context  │→│ Context  │            │
│  │ Router   │  │ Assembler│  │ Composer │            │
│  └──────────┘  └──────────┘  └──────────┘            │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    编排层                              │
│          CognitiveOrchestratorV4                       │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    记忆持久化层                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ Working  │  │ Episodic │  │ Semantic │            │
│  │ Memory   │  │ Memory   │  │ Cache    │            │
│  └──────────┘  └──────────┘  └──────────┘            │
└─────────────────────────────────────────────────────────┘
```

### 10.2 执行流程

**阶段 1：身份缓存检查**
1. 如果是身份查询且有缓存，直接返回缓存答案

**阶段 2：V5 路由层**
1. L0 规则路由：基于规则匹配快速响应
2. L0.5 语义缓存：基于语义相似度返回缓存
3. L1 Tiny Router：小模型处理简单查询

**阶段 3：内存上下文注入**
1. 获取情景记忆（最近 20 条）
2. 获取工作记忆（最近 8 轮）
3. 通过 MemoryRouter 检索相关记忆

**阶段 4：上下文组装**
1. ContextAssembler 压缩历史对话
2. 生成对话摘要
3. 构建上下文块

**阶段 5：编排执行**
1. 调用 CognitiveOrchestratorV4
2. 执行完整推理管道

**阶段 6：结果处理**
1. 保存到语义缓存
2. 保存到工作记忆
3. 异步保存到情景记忆
4. 返回响应

### 10.3 设计原则

1. **多级路由**：从快到慢的多层路由策略
2. **缓存优先**：减少重复计算，提升响应速度
3. **优雅降级**：任一组件失败不影响整体流程
4. **记忆分层**：工作记忆、情景记忆、语义记忆各司其职
5. **可观测性**：完整的追踪和指标体系

---

**相关文件**：
- `kernel/cognitive_kernel.py` - 认知内核核心逻辑
- `kernel/query_router_v2.py` - L0 规则路由
- `kernel/semantic_cache.py` - 语义缓存
- `kernel/complexity_engine.py` - 复杂度引擎
- `kernel/tiny_router.py` - Tiny Router
- `kernel/context_assembler.py` - 上下文组装器
- `kernel/orchestrator_v4.py` - V4 编排器
- `kernel/cognition/self_model.py` - 自我模型