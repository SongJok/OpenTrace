# 融合引擎模块

## 1. 模块概述

融合引擎（Fusion Engine）是 OpenTrace 系统的结果融合核心组件，负责将来自多个数据源（文档检索、数据库查询、网络搜索、记忆系统等）的异构结果进行智能融合、冲突检测和置信度计算，最终生成统一、可靠的上下文供下游任务使用。

**业务价值**：在多智能体协作场景中，不同数据源可能返回互补或冲突的信息，融合引擎通过加权评分机制和冲突检测算法，确保最终输出的一致性和可信度，是实现多模态信息融合的关键基础设施。

## 2. 核心职责

- 多源异构结果的归一化处理
- 基于源权重的结果评分与排序
- 冲突检测与解决（同数据源多结果比较）
- 自适应融合策略（速度/质量/平衡模式）
- 置信度计算与证据追踪
- 子问题级结果的序列融合

## 3. 关键策略与算法

### 3.1 策略落地过程

**当初设计时为什么选择这个方案**：

在多智能体系统中，不同数据源的可靠性差异很大。例如，数据库查询结果通常比网络搜索更可靠，而历史记忆的可信度相对较低。因此需要设计一个加权评分系统来区分不同来源的可靠性。同时，用户场景对响应速度和结果质量的需求不同，需要支持自适应配置。

**实现时的关键代码片段**：

```python
_weights = {
    "llmwiki": 1.05,
    "document": 0.72,
    "sql": 1.0,
    "weather": 0.9,
    "time": 0.9,
    "search": 0.6,
    "web_search": 0.6,
    "attachment": 0.85,
    "memory": 0.55,
}
```

权重设计原则：
- SQL 数据库查询最高（1.0），数据可信度最高
- LLMWiki 增强问答（1.05），经过验证的知识增强
- 文档检索（0.72）和附件（0.85）次之
- 网络搜索较低（0.6），信息质量参差不齐
- 记忆系统最低（0.55），仅作为辅助参考

**测试时发现的调整**：

初始设计中权重差距过大，导致某些低权重源的有效信息被忽略。通过测试发现，需要引入优先级奖励机制和时效性奖励来平衡：

```python
def _priority_bonus(self, result: ToolResult) -> float:
    priority = max(1, int(getattr(result, "source_priority", 10) or 10))
    return max(0.0, 0.14 - ((priority - 1) * 0.03))
```

优先级奖励使得高优先级结果（数值越小优先级越高）获得额外加分，弥补了固定权重的局限性。

### 3.2 冲突检测算法

当同一数据源返回多个不同结果时，系统需要检测并解决冲突：

```python
if str(prev.data) != str(r.data):
    conflicts.append(f"conflict:{key}")
    prev_score = (prev.confidence or 0.5) + self._weight(key) + self._freshness_bonus(key, profile) + self._priority_bonus(prev)
    curr_score = (r.confidence or 0.5) + self._weight(key) + self._freshness_bonus(key, profile) + self._priority_bonus(r)
    if curr_score > prev_score:
        alternates.append(f"[{key}] {str(prev.data)[:500]}")
        picked[key] = r
```

评分公式：`最终得分 = 置信度 + 源权重 + 时效性奖励 + 优先级奖励`

### 3.3 自适应配置模式

支持三种运行模式：
- **speed（速度优先）**：仅对时间敏感数据源（time、weather、web_search）加时效性奖励
- **quality（质量优先）**：对 SQL 和文档检索加较高奖励，启用冲突模式保留更多备选结果
- **balanced（平衡模式）**：默认模式，不额外奖励

### 3.4 序列融合策略

对于复杂问题拆解后的子问题结果，SequenceFusionEngine 负责逐个处理并组装最终答案：

```python
for idx, sq in enumerate(sub_questions):
    matching = [r for r in agent_results if self._guess_sub_question_id(r, sub_question_id) == sub_question_id]
    if matching:
        answer = await self._generate_answer_for_question(gateway, text, domain, matching[0], background_materials)
```

## 4. 输入/输出/依赖的外部服务

### 输入

| 数据结构 | 来源 | 说明 |
|---------|------|------|
| `FusionInput` | Agent Runtime | 融合输入，包含查询、工具结果列表、自适应配置、对话历史 |
| `ToolResult` | 各执行 Agent | 单个工具调用结果，包含来源、数据、置信度、优先级 |
| `SequenceFusionInput` | Planner | 序列融合输入，包含子问题列表、Agent 结果、背景材料 |

### 输出

| 数据结构 | 用途 | 说明 |
|---------|------|------|
| `FusionOutput` | 认知内核 | 融合后的上下文、冲突列表、置信度、备选上下文、证据映射 |
| `SequenceFusionOutput` | Agent Runtime | 组装后的最终回答、各子问题结果、平均置信度 |

### 依赖的外部服务

| 服务 | 用途 | 调用时机 |
|------|------|----------|
| LLM Gateway | 序列融合时生成自然语言回答 | 子问题答案生成 |
| 各数据源 Agent | 提供待融合的原始结果 | 融合前阶段 |

## 5. 关键函数/类说明

### 5.1 FusionEngine 类

**功能**：核心融合引擎，负责多源结果的加权融合和冲突检测

**核心方法**：

| 方法 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `run(input_data)` | 执行融合流程 | `FusionInput` 对象 | `FusionOutput` 对象 |
| `_weight(source)` | 获取数据源权重 | `source`: 数据源名称 | `float`: 权重值 |
| `_priority_bonus(result)` | 计算优先级奖励 | `result`: ToolResult 对象 | `float`: 奖励值 |
| `_freshness_bonus(source, profile)` | 计算时效性奖励 | `source`: 数据源名称, `profile`: 配置文件 | `float`: 奖励值 |
| `_render_context(picked)` | 渲染最终上下文 | `picked`: 选中的结果字典 | `str`: 格式化后的上下文 |

### 5.2 SequenceFusionEngine 类

**功能**：序列融合引擎，处理子问题级别的结果融合和答案生成

**核心方法**：

| 方法 | 功能 | 参数 | 返回值 |
|------|------|------|--------|
| `run(input)` | 执行序列融合 | `SequenceFusionInput` 对象 | `SequenceFusionOutput` 对象 |
| `_generate_answer_for_question(gateway, query, domain, result, bg)` | 根据证据生成答案 | LLM网关、查询、领域、结果、背景材料 | `str`: 自然语言回答 |
| `_assemble_content(results)` | 组装子问题答案 | `PerQuestionResult` 列表 | `str`: 最终回答内容 |

### 5.3 ToolResult 数据类

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | `str` | 数据来源标识 |
| `data` | `Any` | 原始数据内容 |
| `confidence` | `float` | 置信度（0-1） |
| `source_priority` | `int` | 优先级（数值越小优先级越高） |
| `result_refs` | `list[dict]` | 结果引用列表 |

### 5.4 FusionOutput 数据类

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `merged_context` | `str` | 融合后的上下文文本 |
| `conflicts` | `list[str]` | 检测到的冲突列表 |
| `confidence` | `float` | 综合置信度 |
| `alternate_contexts` | `list[str]` | 备选上下文（冲突时保留） |
| `evidence_map` | `list[dict]` | 证据映射表 |
| `result_refs` | `list[dict]` | 所有结果引用 |

## 6. 配置项说明

### 6.1 数据源权重配置

在 `FusionEngine._weights` 中定义，可根据业务需求调整各数据源的权重系数。

### 6.2 自适应配置文件

```python
adaptive_profile = {
    "name": "balanced",  # 可选值: speed, balanced, quality
}
```

| 配置项 | 可选值 | 说明 |
|--------|--------|------|
| `name` | `speed` | 速度优先模式，减少处理开销 |
| `name` | `balanced` | 平衡模式，兼顾速度和质量 |
| `name` | `quality` | 质量优先模式，启用完整冲突检测 |

### 6.3 结果数量限制

- 最大保留数据源数：4（`ordered[:4]`）
- 最大备选上下文数：3（`alternates[:3]`）
- 上下文文本截断长度：1200字符

## 7. 异常场景与容错设计

### 7.1 空结果处理

```python
if not input_data.results:
    return FusionOutput(merged_context="", conflicts=[], confidence=0.0)
```

当没有输入结果时，返回空上下文和零置信度，避免下游处理异常。

### 7.2 数据格式异常

```python
if src == "document" and (
    text.strip().startswith("{") or "'chunks'" in text or '"chunks"' in text
):
    text = "未检索到可直接引用的内部文档内容。"
```

当文档检索返回 JSON 结构而非可读文本时，进行友好提示。

### 7.3 LLM 调用失败处理

```python
try:
    resp = await gateway.chat(messages, temperature=0.7, max_tokens=1024)
    return str(resp) if resp else "抱歉，我暂时无法回答「" + query + "」"
except Exception:
    meta = getattr(result, "metadata", {}) or {}
    error_msg = meta.get("error_reason", str(content))
    return f"执行出错" if not error_msg else error_msg
```

LLM 调用失败时，降级返回原始内容或错误信息。

### 7.4 权重和为零的保护

```python
if weight_sum <= 0:
    weight_sum = float(len(picked))
```

防止置信度计算时除以零的异常。

## 8. 性能注意事项

### 8.1 时间复杂度

- **FusionEngine.run()**: O(n)，n 为输入结果数量
- **冲突检测**: O(n^2)，但实际中同一数据源多结果情况较少
- **排序**: O(n log n)，n <= 4（受限于最大数据源数）

### 8.2 资源消耗

| 操作 | 资源消耗 | 优化建议 |
|------|----------|----------|
| LLM 调用（序列融合） | 高 | 仅在需要时调用，控制 max_tokens |
| 结果文本处理 | 中 | 截断长文本（1200字符） |
| 冲突检测计算 | 低 | 提前去重减少比较次数 |

### 8.3 性能优化策略

1. **结果限制**：最多处理来自4个不同数据源的结果
2. **文本截断**：长文本自动截断至1200字符
3. **异步处理**：序列融合使用 async/await 模式

## 9. 拓扑图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Fusion Engine 拓扑结构                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │ Document│    │  SQL    │    │WebSearch│    │ Memory  │    │  Other  │  │
│  │ Retrieval│    │ Query   │    │ Engine  │    │ System  │    │ Agents  │  │
│  └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘  │
│       │              │              │              │              │        │
│       └──────────────┴──────────────┴──────────────┴──────────────┘        │
│                         │                                                  │
│                         ▼                                                  │
│              ┌──────────────────────┐                                       │
│              │    FusionInput       │                                       │
│              │ (ToolResult 列表)     │                                       │
│              └──────────┬───────────┘                                       │
│                         │                                                  │
│                         ▼                                                  │
│              ┌──────────────────────┐                                       │
│              │    FusionEngine      │                                       │
│              │  ┌────────────────┐  │                                       │
│              │  │ 1. 权重计算    │  │                                       │
│              │  │ 2. 冲突检测    │  │                                       │
│              │  │ 3. 优先级排序  │  │                                       │
│              │  │ 4. 上下文渲染  │  │                                       │
│              │  └────────────────┘  │                                       │
│              └──────────┬───────────┘                                       │
│                         │                                                  │
│                         ▼                                                  │
│              ┌──────────────────────┐                                       │
│              │    FusionOutput      │                                       │
│              │ (merged_context,     │                                       │
│              │  conflicts,          │                                       │
│              │  confidence)         │                                       │
│              └──────────┬───────────┘                                       │
│                         │                                                  │
│                         ▼                                                  │
│              ┌──────────────────────┐                                       │
│              │   Cognitive Kernel   │                                       │
│              │   (生成最终回答)     │                                       │
│              └──────────────────────┘                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 10. 完整架构和策略过程

### 10.1 融合流程

```
输入 → 证据收集 → 冲突检测 → 加权评分 → 结果选择 → 上下文渲染 → 输出
        │              │            │            │            │
        ▼              ▼            ▼            ▼            ▼
    收集所有        同数据源      置信度+        按评分        格式化
    result_refs    结果比较      权重+奖励     排序取前4    输出文本
```

### 10.2 评分计算公式

```
单个结果得分 = 置信度(confidence) 
            + 源权重(_weight) 
            + 时效性奖励(_freshness_bonus) 
            + 优先级奖励(_priority_bonus)

综合置信度 = Σ(单个结果得分 × 该结果置信度) / Σ(单个结果得分)
```

### 10.3 冲突解决流程

```
检测到冲突 → 计算双方得分 → 得分差距判断 → 选择/保留
                │                │
                ▼                ▼
           差距 > 0.12      差距 ≤ 0.12
                │                │
                ▼                ▼
            选择高分者      保留双方作为备选
                           (quality模式)
```

### 10.4 序列融合流程

```
子问题列表 → 逐个匹配结果 → LLM生成答案 → 组装最终回答
                │              │              │
                ▼              ▼              ▼
           查找对应        根据领域        按display_order
           Agent结果      选择Prompt       排序输出
```

### 10.5 自适应策略矩阵

| 模式 | 时效性奖励 | 冲突检测 | 结果数量限制 | 适用场景 |
|------|-----------|----------|-------------|----------|
| speed | 仅时间敏感源 | 关闭 | 较少 | 快速响应场景 |
| balanced | 适度 | 基础 | 中等 | 通用场景 |
| quality | 高质量源 | 完整 | 较多 | 精准回答场景 |

---

**文档版本**: v1.0  
**最后更新**: 2024年  
**相关文件**:
- [engine.py](file:///Users/tuwan/work/code/agentos/opentrace/kernel/fusion_engine/engine.py)
- [models.py](file:///Users/tuwan/work/code/agentos/opentrace/kernel/fusion_engine/models.py)
- [sequence_fusion.py](file:///Users/tuwan/work/code/agentos/opentrace/kernel/fusion_engine/sequence_fusion.py)
- [sequence_models.py](file:///Users/tuwan/work/code/agentos/opentrace/kernel/fusion_engine/sequence_models.py)