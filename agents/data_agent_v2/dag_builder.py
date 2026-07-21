"""
DAG 构建器 — 由 CognitiveContext 与特性开关生成 DagPlan。

纯函数、无副作用；根据认知状态与启用的子 Agent 构建最优 DAG 拓扑。

DAG 拓扑：
  第 0 层（并行）：Intent、Entity、Metric、TimeReasoning、Join
  第 1 层：Semantic（依赖 Intent + Entity）
  第 2 层：Planner（依赖 0/1 层）
  第 3 层：SQLCompiler（依赖 Planner）
  第 4 层：Verification（依赖 Compiler）

知识层识别为元数据查询（快路径）时，DAG 为单节点，跳过推理。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Level-0 agent keys → (node_id, agent_type)
_LEVEL0_AGENTS: tuple[tuple[str, str, str], ...] = (
    ("intent", "intent", "data_intent"),
    ("entity", "entity", "data_entity"),
    ("metric", "metric", "data_metric"),
    ("time", "time", "data_time"),
    ("join", "join", "data_join"),
)


@dataclass
class DagNodeSpec:
    """供 Supervisor 使用的轻量 DAG 节点规格。"""
    node_id: str
    agent_type: str
    query: str
    depends_on: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass
class DagPlanSpec:
    """DAG 计划，包含节点和执行提示。"""
    nodes: list[DagNodeSpec] = field(default_factory=list)
    parallel_enabled: bool = True
    metadata: dict = field(default_factory=dict)


def _node(
    node_id: str,
    agent_type: str,
    query: str,
    *,
    depends_on: list[str] | None = None,
    params: dict | None = None,
) -> DagNodeSpec:
    return DagNodeSpec(
        node_id=node_id,
        agent_type=agent_type,
        query=query,
        depends_on=list(depends_on or []),
        params=dict(params or {}),
    )


def _append_level0(
    nodes: list[DagNodeSpec],
    level0_ids: list[str],
    query: str,
    enabled: dict[str, bool],
    base_params: dict,
) -> None:
    for key, node_id, agent_type in _LEVEL0_AGENTS:
        if enabled.get(key):
            nodes.append(_node(node_id, agent_type, query, params=base_params))
            level0_ids.append(node_id)


def _deps_from_enabled(enabled: dict[str, bool], keys: tuple[str, ...]) -> list[str]:
    return [k for k in keys if enabled.get(k)]


def build_cognitive_dag(
    query: str,
    enabled: dict[str, bool],
    parallel: bool = True,
    is_metadata: bool = False,
) -> DagPlanSpec:
    """根据特性开关构建认知 DAG 计划。"""
    if is_metadata:
        return DagPlanSpec(
            nodes=[_node("intent", "data_intent", query)],
            parallel_enabled=False,
            metadata={"fast_path": "metadata"},
        )

    nodes: list[DagNodeSpec] = []
    level0_nodes: list[str] = []
    base_params = {"query": query}

    _append_level0(nodes, level0_nodes, query, enabled, base_params)

    semantic_deps = _deps_from_enabled(enabled, ("intent", "entity"))
    if enabled.get("semantic") and semantic_deps:
        nodes.append(
            _node("semantic", "data_semantic", query, depends_on=semantic_deps, params=base_params)
        )

    business_deps = _deps_from_enabled(enabled, ("metric", "time", "intent"))
    if enabled.get("business_semantic") and business_deps:
        nodes.append(
            _node(
                "business_semantic",
                "data_business_semantic",
                query,
                depends_on=business_deps,
                params=base_params,
            )
        )

    planner_deps = _deps_from_enabled(
        enabled,
        ("business_semantic", "semantic", "metric", "time", "join", "entity", "intent"),
    )
    if enabled.get("planner"):
        nodes.append(
            _node("planner", "data_planner", query, depends_on=planner_deps, params=base_params)
        )

    if enabled.get("compiler"):
        nodes.append(
            _node("compiler", "data_compiler", query, depends_on=["planner"], params=base_params)
        )

    if enabled.get("verifier"):
        nodes.append(
            _node(
                "verification",
                "data_verification",
                query,
                depends_on=["compiler"],
                params=base_params,
            )
        )

    return DagPlanSpec(
        nodes=nodes,
        parallel_enabled=parallel,
        metadata={
            "level0_count": len(level0_nodes),
            "total_nodes": len(nodes),
            "levels": 5,
        },
    )


def validate_dag_spec(spec: DagPlanSpec) -> list[str]:
    """Return validation errors for dependency integrity (pure, for tests)."""
    errors: list[str] = []
    ids = {n.node_id for n in spec.nodes}
    for n in spec.nodes:
        for dep in n.depends_on:
            if dep not in ids:
                errors.append(f"node {n.node_id} depends on missing {dep}")
    return errors


def validate_dag_against_manifest(spec: DagPlanSpec) -> list[str]:
    """Ensure DAG agent_type values match tier-2 manifest keys."""
    from kernel.agent_runtime.manifest import get_manifest

    m = get_manifest()
    tier2 = set(m.tier2_node_keys())
    errors: list[str] = []
    for n in spec.nodes:
        at = (n.agent_type or "").strip().lower()
        if not at:
            errors.append(f"node {n.node_id} missing agent_type")
            continue
        if at not in tier2:
            errors.append(f"node {n.node_id} unknown tier2 agent_type:{at}")
    sem = m.get("data_semantic")
    if sem:
        deps = tuple(sem.topology.get("depends_on_nodes") or ())
        for n in spec.nodes:
            if n.agent_type == "data_semantic":
                expected = [d.replace("data_", "") for d in deps]
                if sorted(n.depends_on) != sorted(expected):
                    errors.append(
                        f"semantic_deps_mismatch:got={n.depends_on} expected={expected}"
                    )
    return errors


def to_dag_plan(spec: DagPlanSpec, task) -> "DagPlan":
    """将 DagPlanSpec（V2）转换为内核 DagPlan，供 DagScheduler 使用。"""
    from kernel.dag_plan import DagNode, DagPlan

    nodes = [
        DagNode(
            node_id=n.node_id,
            agent_type=n.agent_type,
            query=n.query,
            depends_on=n.depends_on,
            params={
                **n.params,
                "session_id": task.session_id or "",
                "user_id": task.user_id or "",
            },
        )
        for n in spec.nodes
    ]
    return DagPlan(
        nodes=nodes,
        speculative_execution=spec.parallel_enabled,
    )


def get_enabled_agents() -> dict[str, bool]:
    """从设置中读取特性开关。"""
    from infra.config.settings import settings

    return {
        "intent": bool(getattr(settings, "data_agent_v2_intent_enabled", True)),
        "entity": bool(getattr(settings, "data_agent_v2_entity_enabled", True)),
        "metric": bool(getattr(settings, "data_agent_v2_metric_enabled", True)),
        "time": bool(getattr(settings, "data_agent_v2_time_enabled", True)),
        "join": bool(getattr(settings, "data_agent_v2_join_enabled", True)),
        "semantic": bool(getattr(settings, "data_agent_v2_semantic_enabled", True)),
        "business_semantic": bool(
            getattr(settings, "data_agent_business_semantic_enabled", True)
        ),
        "planner": bool(getattr(settings, "data_agent_v2_planner_enabled", True)),
        "compiler": bool(getattr(
            settings,
            "data_agent_v2_sql_compiler_enabled",
            getattr(settings, "data_agent_v2_compiler_enabled", True),
        )),
        "verifier": bool(getattr(settings, "data_agent_v2_verifier_enabled", True)),
        "statistical": bool(getattr(settings, "data_agent_v2_statistical_enabled", False)),
        "insight": bool(getattr(settings, "data_agent_v2_insight_enabled", False)),
        "visualization": bool(getattr(settings, "data_agent_v2_visualization_enabled", False)),
        "skill_execution": bool(getattr(settings, "data_agent_v2_skill_execution_enabled", False)),
    }