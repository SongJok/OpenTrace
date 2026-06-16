# Agent Runtime 模块

## 1. 模块概述

**Agent Runtime** 是 OpenTrace 系统的多智能体编排核心，负责协调 Planner → DAG Engine → Executor → Critic → Reflector 五阶段流水线的执行。其核心价值在于将复杂用户请求自动分解为可并行执行的子任务 DAG，通过多智能体协作完成复杂认知任务，显著提升系统处理复杂问题的能力和响应质量。

## 2. 核心职责

- **任务规划分解**：将用户复杂请求分解为具有依赖关系的子任务 DAG
- **DAG 执行编排**：管理子任务的并行执行和依赖约束
- **工具执行调度**：调用工具或 LLM 完成单个子任务
- **结果质量校验**：通过 Critic 模块验证聚合答案的正确性
- **反思学习**：通过 Reflector 模块提取执行经验（异步）

## 3. 关键策略与算法

### 策略落地过程

**当初设计时为什么选择这个方案**

在设计初期，团队面临两种架构选择：
1. **单一 LLM 直接回答**：简单但无法处理复杂多步骤任务
2. **多智能体协作**：复杂但能处理需要多工具调用的场景

经过分析，我们选择了多智能体协作方案，原因如下：
- 复杂业务场景（如数据分析、文档检索、多步骤推理）需要多个工具配合
- 单一 LLM 在长上下文和多工具调用时容易出错
- 模块化设计便于后续扩展和维护

**实现时的关键代码片段**

核心执行流程位于 `agent_runtime.py` 的 `_run_plan` 方法：

```python
async def _run_plan(self, run_id: str, plan: Plan, goal: str) -> RuntimeResult:
    # 1. 构建 DAG 任务
    dag_tasks = self._build_dag_tasks(plan)
    
    # 2. 执行 DAG（并行执行，尊重依赖）
    subtask_results = await self._dag_engine.execute(dag_tasks, context=ctx)
    
    # 3. 聚合结果
    final_answer = self._aggregate(plan, subtask_results)
    
    # 4. Critic 校验
    critic_result = await self.critic.critique(task=goal, output=final_answer)
    
    # 5. Reflector 反思（异步）
    reflection = await self.reflector.reflect(
        task=goal,
        steps=[str(subtask_results.get(st.task_id, "")) for st in plan.subtasks],
        result=final_answer,
    )
```

**测试时发现的调整**

在测试阶段发现以下问题并进行了调整：

1. **性能瓶颈**：原始实现中 Planner 和 Executor 串行执行，导致延迟过高。调整方案：将工具调用改为并行执行（通过 asyncio.gather）。

2. **错误传播**：单个子任务失败会导致整个流程中断。调整方案：增加任务级别的重试机制和依赖检查，失败任务的依赖任务自动跳过。

3. **结果聚合质量**：简单的文本拼接导致回答不够连贯。调整方案：引入 Fusion Engine 进行多源结果融合。

### DAG 构建策略

`_build_dag_tasks` 方法负责将 Plan 转换为可执行的 DAG 任务：

```python
def _build_dag_tasks(self, plan: Plan) -> list[Task]:
    tasks: list[Task] = []
    for st in plan.subtasks:
        _st = st  # closure capture
        async def _fn(task: Task, ctx: dict[str, Any], _s: SubTask = _st) -> str:
            return await self.executor.execute(_s, ctx)
        
        tasks.append(Task(
            task_id=st.task_id, fn=_fn, deps=st.deps,
            task_type="subtask", timeout=60.0,
        ))
    return tasks
```

该策略的核心特点：
- 每个子任务封装为独立的可执行函数
- 通过闭包捕获子任务上下文
- 显式声明依赖关系，支持并行调度

## 4. 输入/输出/依赖的外部服务

### 输入

| 输入参数 | 类型 | 说明 |
|---------|------|------|
| `RuntimeRequest.query` | str | 用户查询文本 |
| `RuntimeRequest.session_id` | str | 会话 ID |
| `RuntimeRequest.context` | str | 上下文信息 |
| `RuntimeRequest.metadata` | dict | 元数据（可选） |

### 输出

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `RuntimeResult.run_id` | str | 运行 ID |
| `RuntimeResult.goal` | str | 原始目标 |
| `RuntimeResult.final_answer` | str | 聚合后的最终答案 |
| `RuntimeResult.subtask_results` | dict | 各子任务结果 |
| `RuntimeResult.reflection` | Any | 反思结果 |
| `RuntimeResult.passed_critic` | bool | 是否通过 Critic 校验 |
| `RuntimeResult.metadata` | dict | 元数据 |

### 依赖服务

| 依赖模块 | 路径 | 职责 |
|---------|------|------|
| Planner | `agent_runtime/planner/planner.py` | 任务分解 |
| Executor | `agent_runtime/executor/executor.py` | 工具执行 |
| Critic | `agent_runtime/critic/critic.py` | 质量校验 |
| Reflector | `agent_runtime/reflector/reflector.py` | 反思学习 |
| DAG Engine | `execution/dag_engine/engine.py` | DAG 执行引擎 |

## 5. 关键函数/类说明

### 5.1 AgentRuntime 类

**职责**：多智能体流水线的核心协调器

```python
class AgentRuntime:
    def __init__(self, planner=None, executor=None, critic=None, reflector=None):
        self.planner = planner or Planner()
        self.executor = executor or Executor()
        self.critic = critic or Critic()
        self.reflector = reflector or Reflector()
        self._dag_engine = DAGEngine()
```

**关键方法**：
- `run(request)`: 主要入口，处理 RuntimeRequest
- `execute(plan)`: 执行预构建的计划

### 5.2 RuntimeRequest 数据类

**职责**：封装运行时请求参数

```python
@dataclass
class RuntimeRequest:
    query: str
    session_id: str = ""
    context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 5.3 RuntimeResult 数据类

**职责**：封装运行时结果

```python
@dataclass
class RuntimeResult:
    run_id: str
    goal: str
    final_answer: str
    subtask_results: dict[str, Any]
    reflection: Optional[Any] = None
    passed_critic: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 5.4 Planner 类

**职责**：将用户目标分解为子任务 DAG

```python
class Planner:
    async def create_plan(self, goal: str, context: str = "") -> Plan:
        # 使用 LLM 生成子任务列表
        resp = await self._gateway.complete(
            messages=messages,
            role=LLMRole.PLANNING,
            temperature=0.1,
            max_tokens=2048,
        )
        subtasks = self._parse_plan(resp.content)
        return Plan(goal=goal, subtasks=subtasks)
```

### 5.5 SubTask / Plan 数据类

**职责**：表示子任务和完整计划结构

```python
@dataclass
class SubTask:
    task_id: str
    description: str
    deps: list[str] = field(default_factory=list)

@dataclass
class Plan:
    goal: str
    subtasks: list[SubTask]
```

## 6. 配置项说明

目前 Agent Runtime 模块主要依赖以下环境配置：

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `AGENT_TASKS_TOTAL` | Prometheus 指标：任务总数统计 | - |
| `kernel_agent_timeout_sec` | 单个 Agent 任务超时时间 | 60 秒 |
| `kernel_agent_max_parallel` | 最大并行任务数 | 4 |

## 7. 异常场景与容错设计

### 7.1 异常场景

| 场景 | 描述 | 处理策略 |
|------|------|---------|
| Planner 生成失败 | LLM 返回无效 JSON | 使用单任务 fallback |
| 子任务执行超时 | 单个任务超过时间限制 | 标记失败，依赖任务跳过 |
| 子任务执行异常 | 工具调用异常 | 记录错误，继续其他任务 |
| Critic 校验失败 | 答案质量不达标 | 标记 `passed_critic=False` |
| Reflector 失败 | 反思学习异常 | 记录警告，不影响主流程 |

### 7.2 容错机制

```python
# Reflector 的异常处理
try:
    reflection = await self.reflector.reflect(
        task=goal or "task",
        steps=[str(subtask_results.get(st.task_id, "")) for st in plan.subtasks],
        result=final_answer,
    )
except Exception as exc:
    logger.warning("Reflection failed", error=str(exc))  # 不阻塞主流程
```

### 7.3 失败传播策略

```python
# 子任务依赖检查
for dep in task.deps:
    if dep in failed or results.get(f"__err_{dep}"):
        task.status = TaskStatus.SKIPPED  # 跳过依赖失败的任务
        continue
```

## 8. 性能注意事项

### 8.1 性能优化策略

1. **并行执行**：使用 `asyncio.gather` 并行执行多个子任务
2. **超时控制**：每个子任务设置独立超时（默认 60 秒）
3. **异步反思**：Reflector 在后台执行，不阻塞响应
4. **闭包优化**：使用 `_st = st` 避免 Python 闭包延迟绑定问题

### 8.2 监控指标

- `AGENT_TASKS_TOTAL`: 任务总数（按 agent_type 和 status 标签）
- `DAG_TASK_DURATION`: DAG 任务执行耗时
- `dag.tasks.success` / `dag.tasks.failed`: 任务成功/失败数

### 8.3 潜在瓶颈

- Planner 使用 LLM 生成计划，可能成为性能瓶颈
- 大量子任务时，DAG Engine 的调度开销增加
- Critic 模块的质量校验可能增加延迟

## 9. 拓扑图

```
用户请求
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                    AgentRuntime.run()                       │
└─────────────────────────────────────────────────────────────┘
    │
    ├──► Planner.create_plan() ──► 生成子任务 DAG
    │
    ├──► DAGEngine.execute() ──► 并行执行子任务
    │       │
    │       ├──► Executor.execute(subtask1)
    │       ├──► Executor.execute(subtask2)
    │       └──► Executor.execute(subtask3)
    │
    ├──► _aggregate() ──► 聚合子任务结果
    │
    ├──► Critic.critique() ──► 质量校验
    │
    └──► Reflector.reflect() ──► 反思学习（异步）
            │
            ▼
       RuntimeResult
```

## 10. 完整架构和策略过程

### 10.1 架构层次

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cognitive Orchestrator                      │  ← 调用入口
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AgentRuntime                              │  ← 核心协调层
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Planner  │→│ DAGEngine │→│ Executor │→│  Critic  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                              │                 │
│                                        ┌─────┴─────┐           │
│                                        ▼           ▼           │
│                                  ┌─────────┐ ┌──────────┐      │
│                                  │Reflector│ │Fusion    │      │
│                                  │ (异步)  │ │ Engine   │      │
│                                  └─────────┘ └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Tools / Plugins / LLMs                       │  ← 执行层
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 执行流程

**阶段 1：任务规划**
1. 用户请求进入 `AgentRuntime.run()`
2. `Planner.create_plan()` 使用 LLM 将目标分解为子任务
3. 生成包含依赖关系的 `Plan` 对象

**阶段 2：DAG 执行**
1. `_build_dag_tasks()` 将 Plan 转换为 DAG 任务列表
2. `DAGEngine.execute()` 并行执行所有就绪任务
3. 尊重依赖约束：只有依赖任务完成后才执行

**阶段 3：结果聚合**
1. `_aggregate()` 将子任务结果拼接为最终答案
2. 使用简单的文本拼接策略

**阶段 4：质量门控**
1. `Critic.critique()` 评估答案质量
2. 根据校验结果设置 `passed_critic` 标志

**阶段 5：反思学习**
1. `Reflector.reflect()` 异步提取执行经验
2. 不阻塞主流程，失败仅记录日志

### 10.3 设计原则

1. **模块化**：每个组件独立，便于替换和测试
2. **异步优先**：关键路径使用异步执行，提高吞吐量
3. **优雅降级**：单个组件失败不影响整体流程
4. **可观测性**：集成 Prometheus 指标和 OpenTelemetry 追踪

---

**相关文件**：
- `agent_runtime/agent_runtime.py` - 核心协调逻辑
- `agent_runtime/planner/planner.py` - 任务规划器
- `agent_runtime/executor/executor.py` - 工具执行器
- `agent_runtime/critic/critic.py` - 质量校验器
- `agent_runtime/reflector/reflector.py` - 反思学习器
- `execution/dag_engine/engine.py` - DAG 执行引擎