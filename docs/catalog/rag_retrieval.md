# RAG 检索增强模块

## 1. 模块概述

**RAG（Retrieval-Augmented Generation）检索增强模块**是 OpenTrace 系统的核心检索组件，负责从文档知识库、LLMWiki 和用户记忆中检索相关证据，为问答提供上下文支持。其核心价值在于将大语言模型的生成能力与外部知识库相结合，显著提升回答的准确性和时效性，有效缓解幻觉问题。

当前主链采用知识编排优先的检索顺序：已发布的 `KnowledgePage`、`KnowledgeClaim` 和
`KnowledgeRelation` 先作为可治理证据，原始 `DocumentChunk`、LLMWiki 和记忆作为补充 lane。
知识结果必须保留 source version、chunk/span 和访问范围，答案不能只引用无来源的摘要。

元数据层由 `KnowledgeRule` 版本化管理编译 schema/instructions，只有 `approved` 规则会被编译器采用；
Lint 会记录 `KnowledgeObservation`，并通过 `/api/v1/knowledge/evolution/proposal` 生成需人工批准的演化建议。
跨 active source 的重复声明会形成 `KnowledgeMergeCase`，通过合并审核接口闭环，不会静默覆盖来源。


## 企业知识空间与授权

企业知识检索不再只按 `owner_id` 判断。在线查询通过 `knowledge.access` 解析用户、部门、组、岗位、Project、空间角色和密级，并在候选召回前过滤 Source ACL、有效期、撤回状态及 Project 挂载关系。旧个人资产继续按 owner/project 兼容。证据对象同时携带 `space_id`、`classification`、`source_system`、`sync_status`、有效期和复审日期，Session 热证据每轮重新授权。

排序在文本相关性之外加入权威级别与过期复审惩罚；RAG 仍通过多 lane RRF 融合受治理知识和原始文档证据。

## Responses 主链路的 RAG 路由

当前在线入口不再依赖旧 `force_mode`。`/api/v2/responses` 通过 `opentrace.knowledge_mode`
和服务端语义判定形成确定性 RAG 路由：

- 消息以 `/rag`、`/kb` 或 `/knowledge` 开头时，前端发送
  `opentrace.knowledge_mode=required`，Worker 会移除命令前缀后执行一次受治理 RAG 预取；
- “根据/查询/检索/搜索知识库或文档”等明确请求会自动进入同一路由，且不会被规划模型降级为
  普通问答或个人记忆直答；
- 企业认知 manifest 标记 `requires_grounding=true` 时，RAG 只允许查询已发布且当前用户有权
  访问的 `KnowledgeSource`，空间范围为空时 fail closed，不回退到个人记忆或未发布文档；
- 普通 `/rag` 同时查询受治理知识和用户文档，但不把个人记忆作为知识库证据兜底；
- 路由与预取状态通过 `opentrace.rag.routing`、`opentrace.rag.prefetched` 事件及
  `context_manifest.rag_routing` 持久化，便于前端展示和审计。

Project 会话中的 RAG 文档 lane 会检索“当前 Project 文档 + 当前用户未绑定 Project 的我的资料”。
该兼容范围只用于 RAG；`POST /documents/search` 的 `project_id` 仍保持严格 Project 过滤。所有候选继续先
执行 user/tenant/workspace 权限谓词，管理员权限也不能借此读取其他用户的未绑定个人文档。

## 2. 核心职责

- **文档分块检索**：从向量数据库中检索与查询相关的文档片段
- **LLMWiki 检索**：从结构化知识图谱中检索问答对
- **记忆检索**：从用户的语义记忆和情景记忆中检索相关信息
- **查询优化**：对用户查询进行改写和扩展，提升检索效果
- **结果重排序**：使用神经重排序模型优化检索结果顺序
- **证据质量评估**：评估检索结果的可信度和相关性
- **知识编排查询**：按摘要→页面→声明→关系→原始证据渐进式披露
- **知识健康治理**：对孤立页、死链接、过期版本和无证据声明执行 Lint

## 3. 关键策略与算法

### 策略落地过程

**当初设计时为什么选择这个方案**

在设计 RAG 模块时，团队面临以下技术选择：

1. **单一向量检索**：仅使用向量相似度进行检索
2. **混合检索**：结合向量检索、关键词检索和神经重排序

选择混合检索方案的原因：
- **向量检索擅长语义匹配**：能理解查询的语义含义
- **关键词检索擅长精确匹配**：对专有名词和术语效果好
- **神经重排序能优化结果**：基于更深层的语义理解重新排序
- **多源融合提升召回率**：文档 + LLMWiki + 记忆多源互补

**实现时的关键代码片段**

核心检索流程位于 `rag_agent.py` 的 `execute` 方法：

```python
async def execute(self, task: TaskMessage) -> AgentResult:
    # 1. 查询标准化
    query = self._normalize_query(task.query or "")
    rewritten_query = self._rewrite_query(query)
    
    # 2. 查询类型分类
    qtype_info = self._classify_query_type(rewritten_query)
    query_type = qtype_info["query_type"]
    hints = qtype_info["hints"]
    
    # 3. 动态调整检索阈值
    min_score = float(task.params.get("min_score", "0.35"))
    if "lower_threshold" in hints:
        min_score = max(0.20, min_score - 0.08)
    elif "higher_precision" in hints:
        min_score = min(0.55, min_score + 0.05)
    
    # 4. 构建扩展查询词
    query_terms = self._expand_query_terms(rewritten_query)
    
    # 5. 并行执行多源检索
    parallel_results = await asyncio.gather(
        *[_search_one(sq) for sq in search_queries],
        return_exceptions=True,
    )
    
    # 6. 神经重排序
    if settings.rag_rerank_enabled and deduped:
        deduped = await self._rerank_evidence(rewritten_query, deduped, top_k)
    
    # 7. 计算置信度
    confidence = self._calculate_confidence(sorted_chunks)
    
    return AgentResult(...)
```

**测试时发现的调整**

在测试阶段发现以下问题并进行了调整：

1. **检索延迟过高**：原始实现中多个搜索查询串行执行。调整方案：使用 `asyncio.gather` 并行执行多个搜索查询，将搜索查询限制为最多 3 个。

2. **语义匹配不准确**：某些专业术语无法被向量检索正确匹配。调整方案：增加关键词扩展策略，构建同义词映射表。

3. **结果质量不稳定**：不同查询类型需要不同的检索策略。调整方案：引入查询类型分类器，根据查询类型动态调整检索参数。

4. **缺乏证据质量评估**：无法判断检索结果的可靠性。调整方案：增加证据质量门控（DocumentEvidenceGate）和置信度计算。

### 查询改写策略

`_rewrite_query` 方法对查询进行标准化处理：

```python
def _rewrite_query(self, query: str) -> str:
    # 移除尾部疑问词和语气词
    q = re.sub(r"[？?！!]+$", "", q)
    q = re.sub(r"[吗呢啊吧呀嘛哈哦喔]{1,2}$", "", q)
    
    # 移除前缀礼貌用语
    q = re.sub(r"^(请问|我想问一下|我想知道|告诉我)", "", q)
    
    # 模式规范化
    replacements = [
        ("怎么做", "如何操作"),
        ("有没有", "是否有"),
        ("是不是", "是否是"),
        ("能不能", "是否可以"),
    ]
    for old, new in replacements:
        q = q.replace(old, new)
    
    return q.strip()
```

### 查询词扩展策略

`_expand_query_terms` 方法构建同义词扩展：

```python
def _expand_query_terms(self, query: str) -> list[str]:
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", q)
    
    synonym_map = {
        "公司": ["企业", "单位", "组织", "机构"],
        "地址": ["地点", "所在地", "办公地址"],
        "电话": ["联系电话", "联系方式", "手机"],
        "申请": ["请求", "申领", "报名", "注册"],
        "什么是": ["定义", "含义", "是指", "意思是"],
    }
    
    for term in terms:
        for key, values in synonym_map.items():
            if key in term:
                for value in values:
                    add(value)
    
    return expanded
```

### 神经重排序策略

`_rerank_evidence` 方法使用 qwen3-vl-rerank 模型进行重排序：

```python
async def _rerank_evidence(self, query: str, evidence: list[dict], top_k: int) -> list[dict]:
    try:
        reranker = get_reranker()
        texts = [str(e.get("text") or e.get("answer") or "")[:800] for e in evidence]
        
        ranked = await reranker.rerank(query, texts, top_k=min(top_k * 3, len(texts)))
        
        # 融合原始分数和重排序分数
        for e in evidence:
            txt = str(e.get("text") or e.get("answer") or "")[:800]
            if txt in rerank_score_map:
                original_score = float(e.get("score", 0.0))
                rerank_score = rerank_score_map[txt]
                # 加权融合：60% 重排序分数，40% 原始检索分数
                e["score"] = round(original_score * 0.40 + rerank_score * 0.60, 4)
        
        return evidence
    except Exception:
        return evidence  # 失败时回退到原始排序
```

## 4. 输入/输出/依赖的外部服务

### 输入

| 输入参数 | 类型 | 说明 |
|---------|------|------|
| `query` | str | 用户查询文本 |
| `user_id` | str | 用户 ID |
| `top_k` | int | 返回结果数量（默认 5） |
| `llmwiki_top_k` | int | LLMWiki 返回数量（默认 3） |
| `sources` | list[str] | 检索源（documents/semantic_memory/episodic_memory） |
| `min_score` | float | 最低匹配分数阈值 |

### 输出

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `content` | str | 格式化的证据内容 |
| `confidence` | float | 置信度评分（0-1） |
| `metadata.chunks` | list | 排序后的所有证据 |
| `metadata.vector_chunks` | list | 文档检索结果 |
| `metadata.llmwiki_entries` | list | LLMWiki 检索结果 |
| `metadata.sources` | list | 使用的检索源 |
| `metadata.query_type` | str | 查询类型分类 |
| `metadata.quality` | dict | 质量评估信息 |
| `evidence` | list | 结构化证据列表 |
| `result_refs` | list | 结果引用 |

### 依赖服务

| 依赖模块 | 路径 | 职责 |
|---------|------|------|
| DocumentPlugin | `plugins/document_plugin.py` | 文档检索插件 |
| DocumentEvidenceGate | `plugins/document_retrieval.py` | 证据质量门控 |
| Reranker | `model/reranker/base.py` | 神经重排序模型 |
| Embedding | `model/embedding/base.py` | 向量嵌入模型 |
| UserMemory | `infra/storage/models.py` | 用户记忆存储 |

## 5. 关键函数/类说明

### 5.1 RagAgent 类

**职责**：RAG 专职 Agent，负责多源证据检索

```python
class RagAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("rag")
    
    async def execute(self, task: TaskMessage) -> AgentResult:
        # 核心检索逻辑
        ...
```

**关键方法**：
- `execute()`: 主检索入口
- `_normalize_query()`: 查询标准化
- `_rewrite_query()`: 查询改写
- `_classify_query_type()`: 查询类型分类
- `_expand_query_terms()`: 查询词扩展
- `_rerank_evidence()`: 神经重排序
- `_build_vector_evidence()`: 构建文档证据
- `_build_llmwiki_evidence()`: 构建 LLMWiki 证据

### 5.2 DocumentEvidenceGate 类

**职责**：评估证据质量的门控机制

```python
@dataclass
class DocumentEvidenceGate:
    min_score: float = 0.35
    min_gap: float = 0.05
    
    def passes(self, scored: list[ScoredDocumentChunk]) -> bool:
        if not scored:
            return False
        best = scored[0].score
        second = scored[1].score if len(scored) > 1 else 0.0
        return best >= self.min_score or (best - second) >= self.min_gap
```

### 5.3 查询类型分类

**职责**：根据查询特征分类，为检索策略提供提示

```python
def _classify_query_type(query: str) -> dict[str, Any]:
    definition_kw = ["什么是", "定义", "含义", "是指", "解释一下"]
    fact_kw = ["是谁", "多少", "什么时候", "在哪里", "联系方式"]
    procedure_kw = ["怎么做", "如何", "步骤", "流程", "方法"]
    comparison_kw = ["区别", "对比", "不同", "vs"]
    memory_kw = ["偏好", "之前", "上次", "历史", "记忆"]
    
    scores = {
        "definition": sum(1 for k in definition_kw if k in q),
        "fact": sum(1 for k in fact_kw if k in q),
        "procedure": sum(1 for k in procedure_kw if k in q),
        "comparison": sum(1 for k in comparison_kw if k in q),
        "memory": sum(1 for k in memory_kw if k in q),
    }
    
    hints = []
    if query_type == "definition":
        hints = ["prefer_llmwiki", "lower_threshold"]
    elif query_type == "fact":
        hints = ["prefer_documents", "higher_precision"]
    # ...
    
    return {"query_type": query_type, "hints": hints}
```

## 6. 配置项说明

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `RAG_MIN_SCORE` | 默认最低匹配分数阈值 | 0.35 |
| `rag_rerank_enabled` | 是否启用神经重排序 | False |
| `llmwiki_top_k` | LLMWiki 默认返回数量 | 3 |
| `use_pgvector` | 是否使用 PostgreSQL 向量索引 | True |
| `embedding_dims` | 嵌入向量维度 | 384 |

## 7. 异常场景与容错设计

### 7.1 异常场景

| 场景 | 描述 | 处理策略 |
|------|------|---------|
| 无文档结果 | 文档检索返回空 | 尝试 LLMWiki 和记忆检索 |
| 重排序失败 | 神经重排序模型调用失败 | 回退到原始排序 |
| 嵌入模型不可用 | 向量检索失败 | 使用关键词检索作为 fallback |
| 查询为空 | 用户输入为空 | 返回错误提示 |
| 文档未就绪 | 文档状态不是 ready | 跳过该文档 |

### 7.2 容错机制

```python
# 重排序的异常处理
async def _rerank_evidence(self, query: str, evidence: list[dict], top_k: int) -> list[dict]:
    if not evidence or len(evidence) <= 1:
        return evidence
    if not settings.rag_rerank_enabled:
        return evidence
    
    try:
        reranker = get_reranker()
        # ... 重排序逻辑
    except Exception:
        return evidence  # 静默失败，返回原始结果
```

### 7.3 证据质量评估

```python
# 置信度计算
if sorted_chunks:
    scores = [float(chunk.get("score", 0.0)) for chunk in sorted_chunks]
    avg_score = sum(scores) / len(scores)
    max_score = max(scores)
    source_types = {chunk.get("source_type") for chunk in sorted_chunks}
    source_diversity = min(1.0, len(source_types) / 3.0)
    
    confidence = (
        0.30
        + 0.25 * max_score
        + 0.15 * avg_score
        + 0.12 * source_diversity
        + 0.10 * min(1.0, score_spread * 2)
    )
    confidence = min(0.95, max(0.25, confidence))
```

## 8. 性能注意事项

### 8.1 性能优化策略

1. **并行检索**：使用 `asyncio.gather` 并行执行多个搜索查询
2. **查询数量限制**：最多执行 3 个搜索查询，避免延迟爆炸
3. **异步优先**：所有 IO 操作使用异步方式
4. **结果截断**：文本内容截断到 500 字符以内
5. **缓存机制**：可扩展支持检索结果缓存

### 8.2 监控指标

| 指标 | 说明 |
|------|------|
| `total_retrieved` | 检索到的证据总数 |
| `avg_score` | 平均匹配分数 |
| `max_score` | 最高匹配分数 |
| `confidence` | 综合置信度 |

### 8.3 潜在瓶颈

- 向量检索的性能依赖于数据库索引质量
- 神经重排序会增加额外的延迟
- 多源检索需要多次数据库查询

## 9. 拓扑图

```
用户查询
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              RagAgent.execute()                    │
└─────────────────────────────────────────────────────┘
    │
    ├──► _normalize_query() ──► 移除前缀后缀
    │
    ├──► _rewrite_query() ──► 模式规范化
    │
    ├──► _classify_query_type() ──► 查询类型分类
    │
    ├──► _expand_query_terms() ──► 同义词扩展
    │
    ├──► 并行多源检索
    │       │
    │       ├──► DocumentPlugin.search_chunks()
    │       ├──► DocumentPlugin.search_llmwiki()
    │       └──► UserMemory 查询
    │
    ├──► _rerank_evidence() ──► 神经重排序（可选）
    │
    ├──► _calculate_confidence() ──► 置信度计算
    │
    └──► AgentResult
```

## 10. 完整架构和策略过程

### 10.1 架构层次

```
┌─────────────────────────────────────────────────────────┐
│                    用户查询入口                          │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                     RagAgent                           │  ← 检索协调层
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │查询预处理    │→│查询类型分类  │→│查询词扩展    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    多源检索层                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ 文档检索     │  │ LLMWiki      │  │ 用户记忆     │ │
│  │ (向量+关键词) │  │ (知识图谱)   │  │ (语义+情景) │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    结果处理层                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ 去重合并    │→│ 神经重排序   │→│ 质量评估    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    输出层                               │
│         AgentResult + Evidence + ResultRefs            │
└─────────────────────────────────────────────────────────┘
```

### 10.2 执行流程

**阶段 1：查询预处理**
1. `_normalize_query()`：移除前缀（"请告诉我"、"帮我查一下"等）和后缀（"吗"、"呢"等）
2. `_rewrite_query()`：模式规范化（"怎么做" → "如何操作"）

**阶段 2：查询类型分类**
1. 根据关键词判断查询类型（定义类、事实类、流程类、比较类、记忆类）
2. 根据类型生成检索策略提示（hints）

**阶段 3：动态参数调整**
1. 根据查询类型调整 `min_score` 阈值
2. 根据查询类型调整 `llmwiki_top_k`

**阶段 4：多源并行检索**
1. 构建多个搜索查询（原始查询 + 扩展查询）
2. 并行执行文档检索、LLMWiki 检索和记忆检索
3. 限制最多 3 个搜索查询，避免延迟爆炸

**阶段 5：结果处理**
1. 去重合并：使用 `source_type::id::text` 作为去重 key
2. 神经重排序：使用 qwen3-vl-rerank 模型优化排序
3. 质量评估：计算置信度和证据质量

**阶段 6：输出构建**
1. 构建格式化的证据内容
2. 构建结构化的证据列表
3. 构建结果引用（ResultRefs）

### 10.3 设计原则

1. **多源互补**：文档、LLMWiki、记忆多源融合，提升召回率
2. **动态策略**：根据查询类型自适应调整检索参数
3. **优雅降级**：重排序失败时回退到原始排序
4. **可观测性**：输出详细的质量评估指标
5. **异步优先**：所有 IO 操作异步执行

---

**相关文件**：
- `agents/rag_agent.py` - RAG Agent 核心逻辑
- `plugins/document_plugin.py` - 文档检索插件
- `plugins/document_retrieval.py` - 文档检索辅助函数
- `model/reranker/base.py` - 重排序模型接口
- `model/embedding/base.py` - 嵌入模型接口
- `infra/storage/models.py` - 用户记忆模型
