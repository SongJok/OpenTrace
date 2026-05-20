"""
DAG Builder — constructs a DagPlan from CognitiveContext and feature flags.

Pure function with no side effects. Given the current cognitive state and
which sub-agents are enabled, builds the optimal DAG topology for execution.

DAG Topology:
  Level 0 (parallel): IntentAgent, EntityAgent, MetricAgent, TimeReasoningAgent, JoinAgent
  Level 1: SemanticAgent (depends on Intent + Entity)
  Level 2: PlannerAgent (depends on all Level 0/1)
  Level 3: SQLCompilerAgent (depends on Planner)
  Level 4: VerificationAgent (depends on Compiler)

If the Knowledge Layer detects a metadata query (fast path), the DAG is
a single-node plan that skips all reasoning.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DagNodeSpec:
    """Lightweight DAG node specification for the Supervisor."""
    node_id: str
    agent_type: str
    query: str
    depends_on: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


@dataclass
class DagPlanSpec:
    """DAG plan with nodes and execution hints."""
    nodes: list[DagNodeSpec] = field(default_factory=list)
    parallel_enabled: bool = True
    metadata: dict = field(default_factory=dict)


def build_cognitive_dag(
    query: str,
    enabled: dict[str, bool],
    parallel: bool = True,
    is_metadata: bool = False,
) -> DagPlanSpec:
    """Build the cognitive DAG plan based on feature flags.

    Args:
        query: The original user query
        enabled: Dict of agent_name → enabled flag
        parallel: Whether Level 0 agents should run in parallel
        is_metadata: If True, returns a single-node plan (fast path)

    Returns:
        DagPlanSpec ready for scheduling
    """
    if is_metadata:
        return DagPlanSpec(
            nodes=[DagNodeSpec(
                node_id="intent",
                agent_type="data_intent",
                query=query,
            )],
            parallel_enabled=False,
            metadata={"fast_path": "metadata"},
        )

    nodes: list[DagNodeSpec] = []
    base_params = {"query": query}

    # ── Level 0: Independent agents (parallel) ─────────────────────
    level0_nodes: list[str] = []

    if enabled.get("intent"):
        nodes.append(DagNodeSpec(
            node_id="intent", agent_type="data_intent",
            query=query, params=base_params,
        ))
        level0_nodes.append("intent")

    if enabled.get("entity"):
        nodes.append(DagNodeSpec(
            node_id="entity", agent_type="data_entity",
            query=query, params=base_params,
        ))
        level0_nodes.append("entity")

    if enabled.get("metric"):
        nodes.append(DagNodeSpec(
            node_id="metric", agent_type="data_metric",
            query=query, params=base_params,
        ))
        level0_nodes.append("metric")

    if enabled.get("time"):
        nodes.append(DagNodeSpec(
            node_id="time", agent_type="data_time",
            query=query, params=base_params,
        ))
        level0_nodes.append("time")

    if enabled.get("join"):
        nodes.append(DagNodeSpec(
            node_id="join", agent_type="data_join",
            query=query, params=base_params,
        ))
        level0_nodes.append("join")

    # ── Level 1: SemanticAgent (depends on Intent + Entity) ────────
    semantic_deps: list[str] = []
    if enabled.get("intent"):
        semantic_deps.append("intent")
    if enabled.get("entity"):
        semantic_deps.append("entity")

    if enabled.get("semantic") and semantic_deps:
        nodes.append(DagNodeSpec(
            node_id="semantic", agent_type="data_semantic",
            query=query, depends_on=semantic_deps, params=base_params,
        ))

    # ── Level 2: PlannerAgent (depends on Semantic+Metric+Time+Join+Entity) ─
    planner_deps: list[str] = []
    if enabled.get("semantic"):
        planner_deps.append("semantic")
    if enabled.get("metric"):
        planner_deps.append("metric")
    if enabled.get("time"):
        planner_deps.append("time")
    if enabled.get("join"):
        planner_deps.append("join")
    if enabled.get("entity"):
        planner_deps.append("entity")
    if enabled.get("intent"):
        planner_deps.append("intent")

    if enabled.get("planner"):
        nodes.append(DagNodeSpec(
            node_id="planner", agent_type="data_planner",
            query=query, depends_on=planner_deps, params=base_params,
        ))

    # ── Level 3: SQLCompilerAgent ─────────────────────────────────
    if enabled.get("compiler"):
        nodes.append(DagNodeSpec(
            node_id="compiler", agent_type="data_compiler",
            query=query, depends_on=["planner"], params=base_params,
        ))

    # ── Level 4: VerificationAgent ────────────────────────────────
    if enabled.get("verifier"):
        nodes.append(DagNodeSpec(
            node_id="verification", agent_type="data_verification",
            query=query, depends_on=["compiler"], params=base_params,
        ))

    return DagPlanSpec(
        nodes=nodes,
        parallel_enabled=parallel,
        metadata={
            "level0_count": len(level0_nodes),
            "total_nodes": len(nodes),
            "levels": 5,
        },
    )


def to_dag_plan(spec: DagPlanSpec, task) -> "DagPlan":
    """Convert DagPlanSpec (V2) to kernel DagPlan for DagScheduler."""
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
    """Read feature flags from settings."""
    from infra.config.settings import settings

    return {
        "intent": bool(getattr(settings, "data_agent_v2_intent_enabled", True)),
        "entity": bool(getattr(settings, "data_agent_v2_entity_enabled", True)),
        "metric": bool(getattr(settings, "data_agent_v2_metric_enabled", True)),
        "time": bool(getattr(settings, "data_agent_v2_time_enabled", True)),
        "join": bool(getattr(settings, "data_agent_v2_join_enabled", True)),
        "semantic": bool(getattr(settings, "data_agent_v2_semantic_enabled", True)),
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
