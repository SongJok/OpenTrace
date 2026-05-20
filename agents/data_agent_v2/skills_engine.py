"""
SkillsEngine — parses analytical_skills.plan_template to expand the cognitive DAG.

When a Knowledge Layer matches an analytical_skill (e.g., "cohort_retention",
"funnel_analysis"), the SkillsEngine:
1. Parses the plan_template into executable DAG nodes
2. Parameterizes templates with the current query context
3. Expands the base DAG with skill-specific steps
4. Handles skill dependencies (e.g., "compute_cohort" → "compute_retention_matrix")

This enables multi-step analytical workflows without hardcoding each pattern.
"""
from __future__ import annotations

from typing import Any

from agents.data_agent_v2.dag_builder import DagNodeSpec, DagPlanSpec


class SkillsEngine:
    """Expand analytical skill templates into DAG execution plans.

    Parses analytical_skills.plan_template (JSON) and generates DagNodeSpec
    entries that plug into the existing cognitive DAG pipeline.

    Template format in analytical_skills.plan_template:
    {
      "steps": [
        {
          "id": "compute_cohort",
          "agent": "data",
          "description": "Calculate cohort groups",
          "params": { "time_window": "$time_window" },
          "depends_on": []
        },
        {
          "id": "compute_retention",
          "agent": "data",
          "depends_on": ["compute_cohort"],
          "params": { "metric": "retention_rate" }
        },
        {
          "id": "statistical_test",
          "agent": "statistical",
          "depends_on": ["compute_retention"]
        },
        {
          "id": "generate_insight",
          "agent": "insight",
          "depends_on": ["statistical_test", "compute_retention"]
        },
        {
          "id": "suggest_chart",
          "agent": "visualization",
          "depends_on": ["compute_retention"]
        }
      ],
      "parameters": {
        "time_window": {"type": "string", "default": "last_30_days"},
        "cohort_dimension": {"type": "string", "default": "signup_month"}
      }
    }
    """

    # Map skill template agent names to V2 agent types
    AGENT_TYPE_MAP: dict[str, str] = {
        "data": "data",  # re-entrant: spawns another query
        "statistical": "data_statistical",
        "insight": "data_insight",
        "visualization": "data_visualization",
    }

    def expand(
        self,
        skill: dict[str, Any],
        base_dag: DagPlanSpec,
        ctx,  # CognitiveContext
    ) -> DagPlanSpec:
        """Expand a skill template into DAG nodes.

        Args:
            skill: Matched skill from ctx.matched_skills
            base_dag: The existing cognitive DAG plan
            ctx: Current cognitive context

        Returns:
            DagPlanSpec with skill steps appended after existing nodes
        """
        plan_template = skill.get("plan_template")
        if not plan_template:
            return base_dag

        if isinstance(plan_template, str):
            import json
            try:
                plan_template = json.loads(plan_template)
            except (json.JSONDecodeError, TypeError):
                return base_dag

        template_params = plan_template.get("parameters", {})
        steps = plan_template.get("steps", [])

        if not steps:
            return base_dag

        # Resolve parameter values from context
        resolved_params = self._resolve_parameters(template_params, ctx)

        # Find the last node ID in the base DAG (for dependency chaining)
        base_node_ids = {n.node_id for n in base_dag.nodes}
        prev_step_ids: set[str] = set()

        # If steps should build on the base query, first step depends on compiler
        first_step_deps: list[str] = []
        if base_node_ids:
            compiler_exists = "compiler" in base_node_ids
            if compiler_exists:
                first_step_deps = ["compiler"]
            else:
                # Depends on all existing nodes
                first_step_deps = sorted(base_node_ids)

        new_nodes: list[DagNodeSpec] = []
        skill_step_ids: dict[str, str] = {}  # step_id → node_id

        for i, step in enumerate(steps):
            step_id = step.get("id", f"skill_step_{i}")
            agent_name = step.get("agent", "data")
            agent_type = self.AGENT_TYPE_MAP.get(agent_name, agent_name)

            # Resolve dependencies
            deps: list[str] = []
            if i == 0 and first_step_deps:
                deps = first_step_deps
            else:
                for dep_id in step.get("depends_on", []):
                    if dep_id in skill_step_ids:
                        deps.append(skill_step_ids[dep_id])
                    elif dep_id in base_node_ids:
                        deps.append(dep_id)

            # Resolve step parameters
            step_params = self._resolve_step_params(
                step.get("params", {}), resolved_params, ctx
            )

            node_id = f"skill_{step_id}"
            skill_step_ids[step_id] = node_id

            new_nodes.append(DagNodeSpec(
                node_id=node_id,
                agent_type=agent_type,
                query=ctx.query,
                depends_on=deps,
                params={
                    **step_params,
                    "skill_name": skill.get("name", ""),
                    "skill_type": skill.get("skill_type", ""),
                    "step_description": step.get("description", ""),
                },
            ))

        # Combine base DAG + skill steps
        combined_nodes = list(base_dag.nodes) + new_nodes

        return DagPlanSpec(
            nodes=combined_nodes,
            parallel_enabled=base_dag.parallel_enabled,
            metadata={
                **base_dag.metadata,
                "skill_expanded": skill.get("name", ""),
                "skill_steps": len(new_nodes),
            },
        )

    def _resolve_parameters(
        self, template_params: dict, ctx: CognitiveContext
    ) -> dict[str, str]:
        """Resolve template parameters from context."""
        resolved: dict[str, str] = {}

        for param_name, param_def in template_params.items():
            if isinstance(param_def, dict):
                default = param_def.get("default", "")
            else:
                default = str(param_def)

            # Try to resolve from context
            value = self._resolve_value(param_name, default, ctx)
            resolved[param_name] = value

        return resolved

    def _resolve_value(
        self, name: str, default: str, ctx: CognitiveContext
    ) -> str:
        """Resolve a single parameter value from context."""
        # Check time window
        if name == "time_window" and ctx.time_window:
            tw = ctx.time_window
            return tw.get("description", str(tw.get("days", default)))

        # Check metrics
        if name == "metric" and ctx.metrics:
            return ctx.metrics[0].get("mention", default)

        if name == "cohort_dimension" and ctx.intent:
            dims = ctx.intent.get("dimensions", [])
            return dims[0] if dims else default

        # Check query directly
        if name in ("query",):
            return ctx.query or default

        return default

    def _resolve_step_params(
        self,
        step_params: dict,
        resolved: dict[str, str],
        ctx: CognitiveContext,
    ) -> dict:
        """Replace $param references in step params with resolved values."""
        result: dict = {}
        for key, val in step_params.items():
            if isinstance(val, str) and val.startswith("$"):
                param_name = val[1:]
                result[key] = resolved.get(param_name, val)
            else:
                result[key] = val
        return result

    def get_skill_agent_types(self, skill: dict) -> list[str]:
        """Return the agent types needed for a skill's steps."""
        plan_template = skill.get("plan_template")
        if not plan_template:
            return []

        if isinstance(plan_template, str):
            import json
            try:
                plan_template = json.loads(plan_template)
            except (json.JSONDecodeError, TypeError):
                return []

        agent_types: list[str] = []
        for step in plan_template.get("steps", []):
            agent_name = step.get("agent", "data")
            agent_type = self.AGENT_TYPE_MAP.get(agent_name, agent_name)
            if agent_type not in agent_types:
                agent_types.append(agent_type)

        return agent_types
