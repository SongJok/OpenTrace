# 数据认知引擎 (Data Cognition) 模块

## 1. 模块概述

**数据认知引擎**是 OpenTrace 系统的核心组件，负责将自然语言查询转换为可执行的 SQL 查询。该模块通过语义解析、查询规划、SQL 构建和验证等多个阶段，实现从用户自然语言到数据库查询的完整转换流程。其核心价值在于让用户能够以自然语言方式查询数据库，无需编写 SQL 代码，显著降低数据分析门槛。

## 2. 核心职责

- **语义解析**：从自然语言中提取实体、指标、过滤条件、时间窗口等结构化信息
- **查询规划**：将语义解析结果转换为逻辑查询计划（LogicalPlan）
- **SQL 构建**：将逻辑计划转换为符合特定数据库方言的 SQL 语句
- **SQL 验证**：验证生成的 SQL 语法正确性和安全性
- **SQL 重写**：优化 SQL 查询，提升执行效率
- **结果解释**：为 SQL 执行结果提供自然语言解释

## 3. 关键策略与算法

### 策略落地过程

**当初设计时为什么选择这个方案**

在设计数据认知引擎时，团队面临两种技术路线选择：

1. **端到端 LLM 生成 SQL**：直接使用 LLM 根据自然语言生成 SQL
2. **多阶段管道**：语义解析 → 逻辑规划 → SQL 构建 → 验证

选择多阶段管道的原因：
- **可解释性**：每个阶段输出可观测、可调试
- **可验证性**：可以在每个阶段进行验证和修正
- **可扩展性**：支持多种数据库方言和复杂场景
- **安全性**：可以在多个层面进行安全检查
- **性能**：语义解析可以使用轻量级模型，降低延迟

**实现时的关键代码片段**

核心语义解析流程位于 `semantic_parser.py`：

```python
async def parse(self, query: str, dialect: SQLDialectSpec | None = None) -> SemanticParseResult:
    # 1. 尝试缓存
    cached = await self._get_cached(query)
    if cached:
        return cached

    # 2. 实体链接
    entities = await self._schema_linker.link_entities(query, table_columns=self._table_columns)
    
    # 3. 指标链接
    metrics = await self._schema_linker.link_metrics(query)
    
    # 4. 过滤条件提取
    filters = self._extract_filters(query)
    
    # 5. GROUP BY 推断
    group_by = self._infer_group_by(query)
    
    # 6. ORDER BY 推断
    order_by = self._infer_order_by(query)
    
    # 7. LIMIT 推断
    limit = self._infer_limit(query)
    
    # 8. 时间窗口提取
    time_window = self._extract_time_window(query, dialect)
    
    # 9. 缓存结果
    await self._set_cache(query, result)
    return result
```

**测试时发现的调整**

在测试阶段发现以下问题并进行了调整：

1. **缓存失效**：初始实现未考虑 schema 版本变化，导致缓存返回过期结果。调整方案：在缓存 key 中加入 schema_version。

2. **时间窗口提取不准确**：正则表达式无法处理复杂的时间表达式。调整方案：引入 SemanticLayer 的结构化时间提取作为主策略，正则作为 fallback。

3. **实体链接歧义**：同一实体可能映射到多个表。调整方案：增加 confidence 评分机制，选择最匹配的表。

### 时间窗口提取策略

`_extract_time_window` 方法支持多种时间表达式：

```python
def _extract_time_window(self, query: str, dialect: SQLDialectSpec | None) -> dict[str, Any]:
    # 优先使用 SemanticLayer 的结构化提取
    sl_time = SemanticLayer.extract_time_intent(query)
    if sl_time:
        if sl_time.get("days"):
            return {"type": "relative_days", "days": sl_time["days"]}
        elif sl_time.get("start") and sl_time.get("end"):
            return {"type": "date_range", "start": sl_time["start"], "end": sl_time["end"]}
    
    # Fallback: 正则匹配
    _TIME_FILTER_PATTERNS = [
        (r"(?:最近|近|过去|前)\s*(\d+)\s*(?:个)?([年月天日周])", "relative_days"),
        (r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})\s*(?:到|至|~|-)\s*(\d{4})[年-](\d{1,2})[月-](\d{1,2})", "date_range"),
        (r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})", "date_exact"),
    ]
    # ... 处理匹配结果
```

### 查询规划策略

`QueryPlanner.plan` 方法使用 LLM 生成逻辑计划：

```python
async def plan(self, semantics: SemanticParseResult, query: str, ...) -> LogicalPlan:
    for round_idx in range(self.MAX_PLAN_ROUNDS):
        # 使用 LLM 生成逻辑计划
        plan_dict = await self._generate_logical_plan(...)
        
        # 构建计划对象
        plan = self._build_plan_from_dict(plan_dict, tables, cols)
        
        # 验证计划
        issues = self._validate_plan(plan, tables, cols)
        if not issues:
            break
        
        # 如果有问题，重试并提供错误反馈
        last_errors = issues
    
    # 验证 JOIN 路径
    plan = self._validate_joins(plan, tables)
    
    # 应用时间窗口过滤器
    if semantics.time_window and semantics.time_window.get("days"):
        plan.filters.append(FilterSpec(expr=f"__TIME_FILTER__{days}__"))
    
    return plan
```

## 4. 输入/输出/依赖的外部服务

### 输入

| 输入参数 | 类型 | 说明 |
|---------|------|------|
| `query` | str | 用户自然语言查询 |
| `schema_summary` | str | 数据库 schema 摘要 |
| `table_names` | list[str] | 可用表名列表 |
| `table_columns` | dict | 表列映射 |
| `dialect` | SQLDialectSpec | 数据库方言 |

### 输出

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `SemanticParseResult` | object | 语义解析结果（实体、指标、过滤器等） |
| `LogicalPlan` | object | 逻辑查询计划 |
| `CandidateSQL` | list | 候选 SQL 语句列表 |
| `ValidationResult` | object | SQL 验证结果 |
| `Explanation` | object | 结果解释 |

### 依赖服务

| 依赖模块 | 路径 | 职责 |
|---------|------|------|
| SchemaLinker | `kernel/data_cognition/schema_linker.py` | 实体/指标与表/列的映射 |
| SemanticLayer | `kernel/data_cognition/semantic_layer.py` | 语义配置和时间提取 |
| TableRelationshipGraph | `kernel/data_cognition/table_graph.py` | 表关系图，用于 JOIN 路径推断 |
| ModelGateway | `model/model_gateway/gateway.py` | LLM 服务调用 |
| Redis | `infra/cache/redis_client.py` | 语义解析结果缓存 |

## 5. 关键函数/类说明

### 5.1 SemanticParser 类

**职责**：将自然语言查询解析为结构化语义表示

```python
class SemanticParser:
    def __init__(self, schema_summary="", table_names=None, schema_version="", enable_cache=True):
        self._schema_linker = SchemaLinker(...)
        self._semantic_layer = SemanticLayer(...)
        self._schema_version = schema_version
        self._enable_cache = enable_cache
    
    async def parse(self, query: str, dialect=None) -> SemanticParseResult:
        # 核心解析逻辑
        ...
```

**关键方法**：
- `parse()`: 主解析入口
- `_extract_filters()`: 提取过滤条件
- `_infer_group_by()`: 推断分组字段
- `_extract_time_window()`: 提取时间窗口

### 5.2 QueryPlanner 类

**职责**：将语义解析结果转换为逻辑查询计划

```python
class QueryPlanner:
    MAX_PLAN_ROUNDS = 2  # 最多重试次数
    
    async def plan(self, semantics: SemanticParseResult, query: str, ...) -> LogicalPlan:
        # 生成逻辑计划，支持多轮重试
        ...
```

### 5.3 SQLPlanner 类

**职责**：生成候选 SQL 语句，支持多种采样策略

```python
class SQLPlanner:
    async def generate_candidates(self, question: str, schema_hint="", n=4) -> list[CandidateSQL]:
        # 使用不同模板和温度生成多个候选 SQL
        for i in range(n):
            template = templates[i % len(templates)]
            temp = 0.3 if i < 2 else 0.7  # 混合低温和高温采样
            # 调用 LLM 生成 SQL
            ...
```

### 5.4 SQLValidator 类

**职责**：验证 SQL 语句的语法正确性和安全性

### 5.5 SQLRewriter 类

**职责**：优化和重写 SQL 查询，提升执行效率

## 6. 配置项说明

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `semantic_parse_cache_ttl` | 语义解析缓存有效期 | 86400 秒（24小时） |
| `embedding_dims` | 嵌入向量维度 | 384 |
| `use_pgvector` | 是否使用 PostgreSQL 向量索引 | True |

## 7. 异常场景与容错设计

### 7.1 异常场景

| 场景 | 描述 | 处理策略 |
|------|------|---------|
| LLM 生成失败 | LLM 返回无效 JSON | 回退到结构化解析 |
| 实体链接失败 | 无法识别实体 | 使用 fallback 计划 |
| SQL 验证失败 | 生成的 SQL 无效 | 重新生成（最多 2 次） |
| 缓存失效 | schema 变化导致缓存过期 | 缓存 key 包含 schema_version |
| 表不存在 | 引用了不存在的表 | 验证时报错并返回空结果 |

### 7.2 容错机制

```python
# QueryPlanner 的多轮重试机制
async def plan(self, semantics: SemanticParseResult, ...) -> LogicalPlan:
    last_errors = []
    for round_idx in range(self.MAX_PLAN_ROUNDS):
        plan_dict = await self._generate_logical_plan(
            query=query,
            semantics=semantics,
            previous_errors=last_errors if round_idx > 0 else [],
        )
        # ... 验证和修正
        issues = self._validate_plan(plan, tables, cols)
        if not issues:
            break
        last_errors = issues
    
    # 如果所有轮次都失败，使用 fallback
    if not plan_dict:
        return self._fallback_plan(semantics, tables, query, dialect)
```

### 7.3 Fallback 策略

```python
def _fallback_plan(self, semantics: SemanticParseResult, tables: list[str], ...) -> LogicalPlan:
    # 从检测到的指标构建投影
    projections = []
    for m in semantics.metrics:
        if m.agg and m.mapped_column:
            projections.append(Projection(
                expr=f"{m.agg}({m.mapped_column})",
                alias=m.mention,
                agg_func=m.agg,
            ))
    
    # 如果没有指标，使用实体对应的表
    plan_tables = [e.mapped_table for e in semantics.entities if e.mapped_table]
    if not plan_tables:
        plan_tables = tables[:3]
    
    return LogicalPlan(
        tables=plan_tables,
        projections=projections,
        filters=[...],
        group_by=semantics.group_by,
        limit=semantics.limit if semantics.limit else 100,
        metadata={"fallback": True},
    )
```

## 8. 性能注意事项

### 8.1 性能优化策略

1. **语义解析缓存**：使用 Redis 缓存解析结果，key 包含 query、schema_version 和 table_names
2. **轻量级模型**：语义解析使用 PLANNING 角色（小模型），降低延迟
3. **多阶段并行**：实体链接和指标提取可以并行执行
4. **渐进式验证**：先验证逻辑计划，再生成 SQL，避免无效计算

### 8.2 监控指标

| 指标 | 说明 |
|------|------|
| `SEMANTIC_PARSE_CACHE_LATENCY` | 缓存操作延迟 |
| `SEMANTIC_PARSE_CACHE_TOTAL` | 缓存命中/未命中/错误计数 |

### 8.3 潜在瓶颈

- LLM 调用是主要性能瓶颈，尤其是在生成候选 SQL 时
- schema 较大时，schema_linker 的实体匹配可能较慢
- 多轮重试机制会增加延迟

## 9. 拓扑图

```
用户自然语言查询
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                  SemanticParser.parse()                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 实体链接     │  │ 指标提取     │  │ 过滤条件     │  │
│  │ SchemaLinker │  │ SchemaLinker │  │ _extract_    │  │
│  └──────────────┘  └──────────────┘  │ filters()    │  │
│         │                 │          └──────────────┘  │
│         ▼                 ▼                │           │
│  ┌─────────────────────────────────────────────────┐   │
│  │           SemanticParseResult                   │   │
│  │  (entities, metrics, filters, group_by, ...)   │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    QueryPlanner.plan()                 │
│  ┌─────────────────────────────────────────────────┐   │
│  │  LLM 生成 → 验证 → 修正 → 验证 → ...           │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                              │
│                         ▼                              │
│              ┌─────────────────┐                       │
│              │  LogicalPlan    │                       │
│              │ (IR 表示)       │                       │
│              └─────────────────┘                       │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    SQLBuilder.build()                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │  LogicalPlan → SQL (dialect-specific)           │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    SQLValidator.validate()             │
│  ┌─────────────────────────────────────────────────┐   │
│  │  语法检查 → 安全检查 → 权限检查                  │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
    │
    ▼
最终 SQL 查询
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
│                    SemanticParser                      │  ← 语义解析层
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │Schema    │  │Semantic  │  │Time      │  │Cache    │ │
│  │Linker    │  │Layer     │  │Extractor │  │(Redis)  │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    QueryPlanner                        │  ← 逻辑规划层
│  ┌─────────────────────────────────────────────────┐   │
│  │  LLM + Schema Validation + JOIN Path Inference  │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    SQLPlanner                          │  ← SQL 生成层
│  ┌─────────────────────────────────────────────────┐   │
│  │  Multi-candidate generation + Ranking          │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    SQLValidator / SQLRewriter          │  ← 验证优化层
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    数据库执行层                          │
└─────────────────────────────────────────────────────────┘
```

### 10.2 执行流程

**阶段 1：语义解析**
1. 用户查询进入 `SemanticParser.parse()`
2. 尝试从 Redis 缓存获取解析结果
3. 使用 SchemaLinker 进行实体链接和指标链接
4. 使用正则表达式提取过滤条件、GROUP BY、ORDER BY、LIMIT
5. 使用 SemanticLayer 提取时间窗口
6. 缓存解析结果

**阶段 2：逻辑规划**
1. `QueryPlanner.plan()` 将语义结果转换为逻辑计划
2. 使用 LLM 生成初步计划
3. 验证计划与 schema 的一致性
4. 如果有问题，重试并提供错误反馈（最多 2 轮）
5. 使用 TableRelationshipGraph 验证 JOIN 路径
6. 应用时间窗口过滤器

**阶段 3：SQL 生成**
1. `SQLPlanner.generate_candidates()` 生成多个候选 SQL
2. 使用不同模板和温度采样策略
3. 每个候选 SQL 包含特征信息（dialect、temperature、join_depth）

**阶段 4：验证优化**
1. `SQLValidator.validate()` 验证 SQL 语法和安全性
2. `SQLRewriter.rewrite()` 优化查询性能
3. `SQLRanker.rank()` 对候选 SQL 进行排序

### 10.3 设计原则

1. **模块化**：每个阶段独立，便于替换和扩展
2. **可验证性**：每个阶段的输出都可以验证
3. **容错性**：支持多轮重试和 fallback
4. **缓存优先**：语义解析结果缓存，减少重复计算
5. **方言无关**：逻辑计划与数据库方言无关，SQL 生成时再考虑方言

---

**相关文件**：
- `kernel/data_cognition/semantic_parser.py` - 语义解析器
- `kernel/data_cognition/query_planner.py` - 查询规划器
- `kernel/data_cognition/sql_planner.py` - SQL 生成器
- `kernel/data_cognition/sql_validator.py` - SQL 验证器
- `kernel/data_cognition/sql_rewriter.py` - SQL 重写器
- `kernel/data_cognition/schema_linker.py` - 实体链接器
- `kernel/data_cognition/table_graph.py` - 表关系图
- `kernel/data_cognition/types.py` - 类型定义