# DAG 执行引擎模块

## 1. 模块概述

**DAG（Directed Acyclic Graph）执行引擎**是 OpenTrace 系统的核心执行引擎，负责协调和调度具有依赖关系的任务图执行。其核心价值在于支持复杂多步骤任务的并行执行，通过资源感知调度、重试机制和检查点恢复等特性，确保任务图高效可靠地完成。

## 2. 核心职责

- **任务图构建**：将任务列表转换为有向无环图（DAG）
- **并行调度**：根据依赖关系和资源限制，并行执行就绪任务
- **资源管理**：CPU/GPU/IO 资源的动态分配和释放
- **重试机制**：任务级别的失败重试和退避策略
- **检查点机制**：定期保存执行状态，支持故障恢复
- **事件通知**：任务生命周期事件的发布和订阅

## 3. 关键策略与算法

### 策略落地过程

**当初设计时为什么选择这个方案**

在设计 DAG 引擎时，团队面临以下技术选择：

1. **简单线性执行**：按顺序执行所有任务
2. **依赖驱动的并行执行**：根据依赖关系并行执行就绪任务
3. **资源感知的调度**：结合资源限制进行调度

选择资源感知的依赖驱动并行执行方案的原因：
- **性能提升**：无依赖的任务可以并行执行，减少总耗时
- **资源控制**：避免资源耗尽，支持多租户场景
- **容错能力**：支持重试和检查点恢复
- **可扩展性**：支持动态任务注入

**实现时的关键代码片段**

核心执行循环位于 `dag_engine.py` 的 `run` 方法：

```python
async def run(self, dag: DAGGraph, dag_id=None, context=None, resume=False) -> dict[str, Any]:
    did = dag_id or str(uuid.uuid4())[:12]
    completed: set[str] = set()
    results: dict[str, Any] = {}
    failed: set[str] = set()
    
    # 从检查点恢复（如果启用）
    if resume:
        cp = await self._state.load(did)
        if cp:
            completed, results = self._state.restore_task_statuses(dag.tasks, cp)
    
    await self._bus.publish("dag.started", {"dag_id": did, "task_count": len(dag.tasks)})
    
    while True:
        # 获取所有就绪任务（依赖已完成）
        ready = dag.get_ready(completed)
        
        # 检查终止条件
        if not ready and dag.all_done(completed, failed):
            break
        
        # 调度就绪任务（考虑资源限制）
        scheduled = self._scheduler.schedule(ready)
        
        # 资源获取
        granted = []
        for task in scheduled:
            if await self._scheduler.acquire(task):
                granted.append(task)
        
        # 并行执行已获取资源的任务
        await asyncio.gather(
            *[self._execute_task(task, dag, results, ctx, did, completed, failed)
              for task in granted]
        )
        
        # 更新完成状态
        for task in granted:
            if task.status == TaskStatus.SUCCESS:
                completed.add(task.task_id)
            elif task.status == TaskStatus.FAILED:
                failed.add(task.task_id)
        
        # 定期检查点保存
        if self._checkpoint and n_completed % _CHECKPOINT_INTERVAL == 0:
            asyncio.create_task(self._state.save(did, dag.tasks, results, completed))
    
    return results
```

**测试时发现的调整**

在测试阶段发现以下问题并进行了调整：

1. **资源竞争**：多个任务竞争同一资源时可能导致死锁。调整方案：引入资源调度器（ResourceScheduler），实现资源获取和释放机制。

2. **任务失败传播**：单个任务失败后，其依赖任务没有正确处理。调整方案：在任务执行前检查依赖状态，跳过依赖失败的任务。

3. **检查点开销**：频繁的检查点保存影响性能。调整方案：设置检查点间隔（每 5 个任务完成后保存），并且异步保存。

4. **动态任务注入**：原始实现不支持运行时添加任务。调整方案：支持 `task.dynamic` 属性，允许任务执行结果注入新任务。

### 资源调度策略

`ResourceScheduler` 负责资源分配：

```python
class ResourceScheduler:
    def __init__(self, limits: ResourceLimits):
        self._limits = limits
        self._acquired = {"cpu": 0, "gpu": 0, "io": 0}
    
    async def acquire(self, task: Task) -> bool:
        """尝试为任务获取资源"""
        resource = getattr(task, "resource", ResourceType.CPU)
        need = task.resource_weight or 1
        
        if self._acquired[resource.value] + need > getattr(self._limits, resource.value):
            return False
        
        self._acquired[resource.value] += need
        return True
    
    async def release(self, task: Task) -> None:
        """释放任务占用的资源"""
        resource = getattr(task, "resource", ResourceType.CPU)
        need = task.resource_weight or 1
        self._acquired[resource.value] -= need
```

### 任务执行与重试策略

`_execute_task` 方法处理任务执行和重试：

```python
async def _execute_task(self, task: Task, dag: DAGGraph, results: dict, ctx: dict, 
                         dag_id: str, completed: set, failed: set) -> None:
    # 检查依赖状态
    for dep in task.deps:
        if dep in failed or results.get(f"__err_{dep}"):
            task.status = TaskStatus.SKIPPED
            await self._scheduler.release(task)
            return
    
    task.status = TaskStatus.RUNNING
    task.started_at = time.monotonic()
    
    try:
        result = await asyncio.wait_for(task.fn(task, ctx), timeout=task.timeout)
        task.result = result
        task.status = TaskStatus.SUCCESS
        results[task.task_id] = result
        
        # 动态任务注入
        if task.dynamic and isinstance(result, list):
            new_tasks = [t for t in result if isinstance(t, Task)]
            for nt in new_tasks:
                dag.add_task(nt)
    
    except (asyncio.TimeoutError, Exception) as exc:
        # 重试机制
        if task.retries > 0 and task.attempt <= task.retries + 1:
            task.retries -= 1
            backoff = min(2 ** task.attempt, 30)
            await asyncio.sleep(backoff)
            task.status = TaskStatus.PENDING  # 重新入队
        else:
            task.status = TaskStatus.FAILED
            results[f"__err_{task.task_id}"] = exc
            # 回滚钩子
            if task.rollback_fn:
                await task.rollback_fn(task, ctx)
    
    finally:
        await self._scheduler.release(task)
```

## 4. 输入/输出/依赖的外部服务

### 输入

| 输入参数 | 类型 | 说明 |
|---------|------|------|
| `dag` | DAGGraph | DAG 图对象 |
| `dag_id` | str | DAG ID（可选，自动生成） |
| `context` | dict | 执行上下文 |
| `resume` | bool | 是否从检查点恢复 |

### 输出

| 输出字段 | 类型 | 说明 |
|---------|------|------|
| `results` | dict | 任务结果映射（task_id -> result） |

### 依赖服务

| 依赖模块 | 路径 | 职责 |
|---------|------|------|
| ResourceScheduler | `execution/dag_engine/scheduler.py` | 资源调度器 |
| StateManager | `execution/dag_engine/state.py` | 状态管理和检查点 |
| EventBus | `execution/dag_engine/events.py` | 事件总线 |
| DAGGraph | `execution/dag_engine/graph.py` | DAG 图数据结构 |

## 5. 关键函数/类说明

### 5.1 DAGEngine 类

**职责**：DAG 执行引擎的核心类

```python
class DAGEngine:
    def __init__(self, limits=None, event_bus=None, state_manager=None, checkpoint=False):
        self._scheduler = ResourceScheduler(limits or ResourceLimits())
        self._bus = event_bus or _default_bus
        self._state = state_manager or _default_state
        self._checkpoint = checkpoint
    
    async def run(self, dag: DAGGraph, dag_id=None, context=None, resume=False) -> dict:
        # 执行 DAG
        ...
    
    async def execute(self, tasks: list[Task], context=None) -> dict:
        # 兼容旧接口，将任务列表转换为 DAGGraph
        ...
```

### 5.2 DAGGraph 类

**职责**：管理任务节点和依赖关系

```python
class DAGGraph:
    def __init__(self):
        self.tasks: dict[str, Task] = {}
    
    def add_task(self, task: Task) -> None:
        # 添加任务到图中
    
    def get_ready(self, completed: set[str]) -> list[Task]:
        # 获取所有就绪任务（依赖已完成）
    
    def all_done(self, completed: set[str], failed: set[str]) -> bool:
        # 检查是否所有任务都已完成或失败
```

### 5.3 Task 类

**职责**：表示单个执行任务

```python
@dataclass
class Task:
    task_id: str
    fn: Callable  # 任务执行函数
    deps: list[str] = field(default_factory=list)
    resource: ResourceType = ResourceType.CPU
    timeout: float = 60.0
    retries: int = 0
    rollback_fn: Optional[Callable] = None
    dynamic: bool = False  # 是否允许动态任务注入
```

### 5.4 ResourceLimits 类

**职责**：定义资源限制

```python
@dataclass
class ResourceLimits:
    cpu: int = 8
    gpu: int = 2
    io: int = 16
```

## 6. 配置项说明

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `CHECKPOINT_INTERVAL` | 检查点保存间隔（任务数） | 5 |
| `default_timeout` | 默认任务超时时间（秒） | 60 |
| `default_retries` | 默认重试次数 | 0 |

## 7. 异常场景与容错设计

### 7.1 异常场景

| 场景 | 描述 | 处理策略 |
|------|------|---------|
| 任务超时 | 任务执行时间超过 timeout | 标记失败，触发重试或跳过依赖任务 |
| 任务异常 | 任务执行抛出异常 | 标记失败，触发重试或跳过依赖任务 |
| 资源不足 | 无法获取所需资源 | 等待资源释放，稍后重试 |
| 依赖失败 | 依赖任务失败 | 跳过当前任务，标记为 SKIPPED |
| 检查点失败 | Redis 不可用导致检查点保存失败 | 记录警告，继续执行（检查点是 best-effort） |

### 7.2 容错机制

```python
# 重试和回滚机制
except (asyncio.TimeoutError, Exception) as exc:
    if task.retries > 0 and task.attempt <= task.retries + 1:
        # 重试策略：指数退避
        task.retries -= 1
        backoff = min(2 ** task.attempt, 30)
        await asyncio.sleep(backoff)
        task.status = TaskStatus.PENDING  # 重新入队
    else:
        task.status = TaskStatus.FAILED
        # 执行回滚钩子
        if task.rollback_fn:
            await task.rollback_fn(task, ctx)
```

### 7.3 失败传播策略

```python
# 依赖检查
for dep in task.deps:
    if dep in failed or results.get(f"__err_{dep}"):
        task.status = TaskStatus.SKIPPED
        await self._bus.publish("task.skipped", {
            "dag_id": dag_id, "task_id": task.task_id, "dep": dep
        })
        await self._scheduler.release(task)
        return
```

## 8. 性能注意事项

### 8.1 性能优化策略

1. **并行执行**：使用 `asyncio.gather` 并行执行所有就绪任务
2. **资源感知调度**：根据资源限制动态调整并发度
3. **异步检查点**：检查点保存异步执行，不阻塞主流程
4. **事件驱动**：使用事件总线解耦状态变更通知

### 8.2 监控指标

| 指标 | 说明 |
|------|------|
| `DAG_EXECUTIONS_TOTAL` | DAG 执行总数（按状态） |
| `DAG_TASK_DURATION` | 任务执行耗时分布 |
| `dag.tasks.success` | 成功任务数 |
| `dag.tasks.failed` | 失败任务数 |

### 8.3 潜在瓶颈

- 资源调度器的锁竞争
- 大量任务时的调度开销
- 检查点保存的 IO 开销

## 9. 拓扑图

```
任务列表 / DAGGraph
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              DAGEngine.run()                       │
└─────────────────────────────────────────────────────┘
    │
    ├──► 检查点恢复（可选）
    │
    ├──► 发布 "dag.started" 事件
    │
    ├──► [主循环]
    │       │
    │       ├──► get_ready() 获取就绪任务
    │       │
    │       ├──► scheduler.schedule() 调度任务
    │       │
    │       ├──► scheduler.acquire() 获取资源
    │       │
    │       ├──► asyncio.gather() 并行执行
    │       │       │
    │       │       └──► _execute_task()
    │       │               │
    │       │               ├──► 依赖检查
    │       │               ├──► 执行任务函数
    │       │               ├──► 动态任务注入
    │       │               └──► 重试/回滚
    │       │
    │       ├──► 更新 completed/failed 集合
    │       │
    │       └──► 异步保存检查点
    │
    └──► 发布 "dag.completed" 事件
```

## 10. 完整架构和策略过程

### 10.1 架构层次

```
┌─────────────────────────────────────────────────────────┐
│                    调用层                              │
│    execute(tasks) / run(dag)                          │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    DAGEngine                           │  ← 执行引擎层
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Resource     │  │ StateManager │  │ EventBus     │ │
│  │ Scheduler   │  │ (Redis)      │  │ (Pub/Sub)    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    DAGGraph                           │  ← 图数据层
│         Tasks + Dependencies + Status                 │
└─────────────────────────────────────────────────────────┘
```

### 10.2 执行流程

**阶段 1：初始化**
1. 创建或获取 DAG ID
2. 如果启用检查点且 resume=True，从 Redis 加载状态
3. 发布 `dag.started` 事件

**阶段 2：主循环**
1. `get_ready()` 获取所有就绪任务（依赖已完成的任务）
2. `scheduler.schedule()` 根据资源限制调度任务
3. `scheduler.acquire()` 为调度的任务获取资源
4. `asyncio.gather()` 并行执行已获取资源的任务
5. 更新 `completed` 和 `failed` 集合
6. 每完成 5 个任务，异步保存检查点
7. 重复直到所有任务完成或失败

**阶段 3：任务执行**
1. 检查依赖状态，如果依赖失败则跳过
2. 设置任务状态为 RUNNING
3. 执行任务函数（带超时）
4. 如果成功，保存结果并处理动态任务注入
5. 如果失败且有重试次数，执行指数退避后重新入队
6. 如果失败且无重试次数，执行回滚钩子（如果有）

**阶段 4：结束**
1. 发布 `dag.completed` 事件
2. 删除检查点（如果启用）
3. 返回任务结果

### 10.3 设计原则

1. **并行优先**：最大化并行执行，减少总耗时
2. **资源可控**：通过资源调度器防止资源耗尽
3. **优雅降级**：单个任务失败不影响其他无关任务
4. **可恢复性**：检查点机制支持故障恢复
5. **可观测性**：事件总线提供完整的执行追踪

---

**相关文件**：
- `execution/dag_engine/engine.py` - DAG 引擎核心逻辑
- `execution/dag_engine/graph.py` - DAG 图数据结构
- `execution/dag_engine/scheduler.py` - 资源调度器
- `execution/dag_engine/state.py` - 状态管理和检查点
- `execution/dag_engine/events.py` - 事件总线
- `execution/dag_engine/cognitive_nodes.py` - 认知节点类型