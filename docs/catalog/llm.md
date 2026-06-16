# OpenTrace LLM 模型使用场景梳理

## 1. LLM 角色定义

OpenTrace 采用**角色化 LLM 路由**架构，根据不同场景选择最合适的模型。共定义了 9 种角色：

| 角色 | 模型 | 模型规格 | 用途 | 环境变量前缀 |
|------|------|----------|------|--------------|
| `QUERY` | qwen3.6-plus | 3.6T | 核心问答、推理 | `DEFAULT_LLM_QUERY_*` |
| `COMPRESS` | qwen3.5-27b | 27B | 上下文压缩、评估 | `DEFAULT_LLM_COMPRESS_*` |
| `PLANNING` | qwen3.6-plus | 3.6T | 任务规划、意图识别、SQL生成 | `DEFAULT_LLM_PLANING_*` |
| `ROUTER` | qwen3-1.7b | 1.7B | L1 分类路由 | `DEFAULT_LLM_JUNIORSHORT_*` |
| `FAST` | qwen3-8b | 8B | 简单问答、快速响应 | `DEFAULT_LLM_MIDDLESHORT_*` |
| `CHEAP_CRITIC` | qwen3-14b | 14B | 轻量评估、审查 | `DEFAULT_LLM_SENIORSORT_*` |
| `KNOWLEDGE` | qwen3-14b | 14B | 知识库问答 | `DEFAULT_LLM_SENIORSORT_*` |
| `IDENTITY` | qwen3-0.6b | 0.6B | 身份回答 | `DEFAULT_LLM_MINSHORT_*` |
| `VISION` | qwen3.6-vl-plus | 多模态 | 图像/图表理解 | `DEFAULT_LLM_VISION_*` |

## 2. 各场景 LLM 使用详情

### 2.1 认知内核层

#### 2.1.1 问题分解
- **位置**: `kernel/cognitive_kernel.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=400`
- **用途**: 将复合问题拆分为独立子问题

```python
resp = await gw.complete(
    [LLMMessage(role="user", content=prompt)],
    role=LLMRole.PLANNING,
    temperature=0.0,
    max_tokens=400,
)
```

#### 2.1.2 工具选择
- **位置**: `kernel/cognitive_kernel.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=100`
- **用途**: 根据问题复杂度选择合适工具

#### 2.1.3 意图引擎
- **位置**: `kernel/intent_engine/engine.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=256`
- **用途**: 将原始查询解析为结构化 Intent

#### 2.1.4 规划 Agent
- **位置**: `kernel/plan_agent.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=400`
- **用途**: 生成执行计划和子任务

---

### 2.2 推理引擎层

#### 2.2.1 直接推理 (DIRECT)
- **位置**: `kernel/reasoning/engine.py`
- **角色**: `LLMRole.QUERY`
- **模型**: qwen3.6-plus
- **参数**: `temperature=temperature` (动态)
- **用途**: 简单问题直接回答

#### 2.2.2 思维链推理 (COT)
- **位置**: `kernel/reasoning/engine.py`
- **角色**: `LLMRole.QUERY`
- **模型**: qwen3.6-plus
- **参数**: `temperature=temperature` (动态)
- **用途**: 中等复杂度问题的逐步推理

#### 2.2.3 树状推理 (ToT)
- **位置**: `kernel/reasoning/engine.py`
- **角色**: `LLMRole.QUERY`
- **模型**: qwen3.6-plus
- **参数**: 探索阶段 `temperature=0.7`，评判阶段 `temperature=0.1`
- **用途**: 复杂问题的多分支探索

```python
# 分支探索
self._gateway.complete(msgs, role=LLMRole.QUERY, temperature=0.7)

# 方案评判
self._gateway.complete(messages, role=LLMRole.QUERY, temperature=0.1)
```

---

### 2.3 数据认知层 (Text2SQL)

#### 2.3.1 SQL 规划
- **位置**: `kernel/data_cognition/sql_planner.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: 单候选 `temperature=0.0`, `max_tokens=300`；多候选 `temperature=0.3/0.7`, `max_tokens=400`
- **用途**: 生成 SQL 查询语句

#### 2.3.2 SQL 重写
- **位置**: `kernel/data_cognition/sql_rewriter.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=400`
- **用途**: 根据错误反馈修正 SQL

#### 2.3.3 Schema 链接
- **位置**: `kernel/data_cognition/schema_linker.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`
- **用途**: 将自然语言实体映射到数据库 Schema

#### 2.3.4 查询规划
- **位置**: `kernel/data_cognition/query_planner.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`
- **用途**: 规划多表查询的执行路径

---

### 2.4 DataAgent V2

#### 2.4.1 意图分类
- **位置**: `agents/data_agent_v2/intent_agent.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=256`
- **用途**: 识别用户查询的意图类型

#### 2.4.2 规划 Agent
- **位置**: `agents/data_agent_v2/planner_agent.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`, `max_tokens=600`
- **用途**: 生成认知 DAG 执行计划

#### 2.4.3 洞察 Agent
- **位置**: `agents/data_agent_v2/insight_agent.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`
- **用途**: 从数据中提取洞察

#### 2.4.4 指标优化
- **位置**: `agents/data_agent_v2/metric_refiner.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`
- **用途**: 优化指标定义和计算

---

### 2.5 记忆系统

#### 2.5.1 上下文压缩
- **位置**: `memory/evolution/evolution.py`
- **角色**: `LLMRole.COMPRESS`
- **模型**: qwen3.5-27b
- **参数**: `temperature=0.1`, `max_tokens=512`
- **用途**: 压缩对话历史，减少上下文长度

#### 2.5.2 记忆聚类
- **位置**: `memory/evolution/evolution.py`
- **角色**: `LLMRole.COMPRESS`
- **模型**: qwen3.5-27b
- **参数**: `temperature=0.0`, `max_tokens=512`
- **用途**: 将相似记忆分组聚类

#### 2.5.3 记忆进化
- **位置**: `memory/evolution/evolution.py`
- **角色**: `LLMRole.COMPRESS`
- **模型**: qwen3.5-27b
- **参数**: `temperature=0.2`, `max_tokens=512`
- **用途**: 从案例中提取模式和技能

#### 2.5.4 反思器
- **位置**: `agent_runtime/reflector/reflector.py`
- **角色**: `LLMRole.COMPRESS`
- **模型**: qwen3.5-27b
- **参数**: `temperature=0.0`
- **用途**: 对执行过程进行反思总结

---

### 2.6 融合引擎

#### 2.6.1 证据融合
- **位置**: `kernel/fusion_engine/sequence_fusion.py`
- **角色**: `LLMRole.QUERY`
- **模型**: qwen3.6-plus
- **参数**: 数据域 `temperature=0.7`, 知识域 `temperature=0.3`, `max_tokens=1024`
- **用途**: 将多源结果融合为最终回答

```python
# 数据类问题
gateway.chat(messages, temperature=0.7, max_tokens=1024)

# 事实类问题
gateway.chat(messages, temperature=0.3, max_tokens=1024)
```

---

### 2.7 编排器

#### 2.7.1 多问题处理
- **位置**: `kernel/orchestrator_v4.py`
- **角色**: `LLMRole.PLANNING`, `LLMRole.IDENTITY`, `LLMRole.QUERY`
- **模型**: qwen3.6-plus / qwen3-0.6b
- **参数**: `temperature=0.35`, `max_tokens=4096`
- **用途**: 任务分解、答案生成、身份识别

```python
# 任务规划
gw.complete(messages, role=LLMRole.PLANNING)

# 身份查询
gw.complete(messages, role=LLMRole.IDENTITY)

# 最终答案生成
gw.complete(msgs, role=LLMRole.QUERY, temperature=0.35, max_tokens=4096)
```

---

### 2.8 元认知层

#### 2.8.1 答案验证
- **位置**: `kernel/meta_cognition/meta_cognition.py`
- **角色**: `LLMRole.COMPRESS` (评分), `LLMRole.QUERY` (优化)
- **模型**: qwen3.5-27b / qwen3.6-plus
- **参数**: 评分 `temperature=0.0`, `max_tokens=200`；优化 `temperature=0.3`, `max_tokens=2048`
- **用途**: 评估答案质量、检测幻觉、优化回答

```python
# 评分
self._gateway.complete(messages, role=LLMRole.COMPRESS, temperature=0.0, max_tokens=200)

# 优化
self._gateway.complete(messages, role=LLMRole.QUERY, temperature=0.3, max_tokens=2048)
```

---

### 2.9 V6 多轮对话增强

#### 2.9.1 澄清门控
- **位置**: `kernel/clarification_gate.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`
- **用途**: 识别需要追问的模糊问题

---

### 2.10 演化与学习系统

#### 2.10.1 自我对弈
- **位置**: `evolution/self_play/self_play.py`
- **角色**: `LLMRole.PLANNING` (生成), `LLMRole.QUERY` (解决), `LLMRole.COMPRESS` (评判)
- **模型**: qwen3.6-plus / qwen3.5-27b
- **参数**: 
  - 任务生成: `temperature=0.8`, `max_tokens=256`
  - 问题解决: `temperature=0.3`, `max_tokens=512`
  - 质量评判: `temperature=0.0`, `max_tokens=256`

#### 2.10.2 元学习
- **位置**: `evolution/meta_learning/meta_learner.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: `temperature=0.0`
- **用途**: 从经验中学习策略

---

### 2.11 内置工具

#### 2.11.1 知识库问答
- **位置**: `tools/builtin_tools/builtins.py`
- **角色**: `LLMRole.KNOWLEDGE`
- **模型**: qwen3-14b
- **参数**: 默认参数
- **用途**: 基于知识库回答问题

#### 2.11.2 内容总结
- **位置**: `tools/builtin_tools/builtins.py`
- **角色**: `LLMRole.COMPRESS`
- **模型**: qwen3.5-27b
- **参数**: 默认参数
- **用途**: 总结长文本内容

---

### 2.12 上下文重写
- **位置**: `kernel/context/query_rewriter.py`
- **角色**: `LLMRole.QUERY`
- **模型**: qwen3.6-plus
- **参数**: 默认参数
- **用途**: 结合上下文重写用户查询

---

### 2.13 策略引擎
- **位置**: `kernel/policy/engine.py`
- **角色**: `LLMRole.PLANNING`
- **模型**: qwen3.6-plus
- **参数**: 默认参数
- **用途**: 策略决策和路由选择

---

## 3. LLM 参数汇总表

| 场景 | 角色 | 温度 | Max Tokens | 典型用途 |
|------|------|------|------------|----------|
| 任务规划 | PLANNING | 0.0 | 256-600 | 意图识别、子任务分解 |
| SQL生成 | PLANNING | 0.0-0.7 | 300-400 | NL2SQL转换 |
| 直接推理 | QUERY | 0.35 | 4096 | 简单问答 |
| COT推理 | QUERY | 0.35 | - | 中等复杂度推理 |
| ToT探索 | QUERY | 0.7 | - | 多分支探索 |
| ToT评判 | QUERY | 0.1 | - | 方案选择 |
| 上下文压缩 | COMPRESS | 0.0-0.1 | 512 | 记忆压缩 |
| 记忆进化 | COMPRESS | 0.2 | 512 | 模式提取 |
| 答案验证 | COMPRESS | 0.0 | 200 | 质量评估 |
| 答案优化 | QUERY | 0.3 | 2048 | 回答改进 |
| 身份回答 | IDENTITY | 0.7 | 256 | 自我介绍 |
| 自我对弈生成 | PLANNING | 0.8 | 256 | 任务生成 |
| 自我对弈解决 | QUERY | 0.3 | 512 | 问题解答 |
| 自我对弈评判 | COMPRESS | 0.0 | 256 | 质量评分 |
| 融合回答 | QUERY | 0.3-0.7 | 1024 | 多源融合 |

---

## 4. 模型配置说明

### 4.1 默认配置来源

所有 LLM 配置均从 `infra/config/settings.py` 读取，支持通过环境变量覆盖：

```python
# QUERY 模型配置
default_llm_query_provider: str = "阿里巴巴Qwen(DashScope)"
default_llm_query_model: str = "qwen3.6-plus"
default_llm_query_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

### 4.2 熔断机制

每个 LLM 角色独立配备熔断器，防止级联失败：

- **失败阈值**: 3次
- **恢复超时**: 30秒
- **状态流转**: CLOSED → OPEN → HALF-OPEN

### 4.3 重试策略

根据异常类型决定是否重试：

| 异常类型 | 是否重试 | 基础延迟(秒) |
|----------|----------|--------------|
| 认证错误 | 否 | 0 |
| 模型不存在 | 否 | 0 |
| 限流 | 是 | 1.5 |
| 超时 | 是 | 0.6 |
| 网络连接 | 是 | 0.6 |
| 其他 | 是 | 0.4 |

---

## 5. 离线降级响应

当所有 LLM 候选都失败时，系统会根据角色返回预设的离线响应：

| 角色 | 离线响应内容 |
|------|--------------|
| ROUTER | `{"route": "complex", "difficulty": "simple"}` |
| IDENTITY | 固定身份回答 |
| FAST | "我目前处于离线降级模式..." |
| CHEAP_CRITIC | `{"verdict": "pass", "confidence": 0.5, "issues": []}` |
| KNOWLEDGE | "我目前处于离线降级模式，暂时无法查询知识库..." |
| PLANNING | 生成简单任务规划 |
| 其他 | 根据问题类型返回预设响应 |
