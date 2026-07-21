"""
SkillsEngine — 解析 analytical_skills.plan_template 以扩展认知 DAG。

当知识层匹配分析技能（如 cohort_retention、funnel_analysis）时：
1. 将 plan_template 解析为可执行 DAG 节点
2. 用当前查询上下文参数化模板
3. 在基础 DAG 上追加技能专属步骤
4. 处理技能依赖（如 compute_cohort → compute_retention_matrix）

无需为每种模式硬编码即可支持多步分析工作流。
"""
from __future__ import annotations

from typing import Any

from agents.data_agent_v2.dag_builder import DagNodeSpec, DagPlanSpec


class SkillsEngine:
    """将分析技能模板展开为 DAG 执行计划。

    解析 analytical_skills.plan_template（JSON），生成并入认知 DAG 的 DagNodeSpec。

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

    # 技能模板中的 agent 名称到 V2 agent 类型的映射
    AGENT_TYPE_MAP: dict[str, str] = {
        "data": "data",  # 重入：生成另一个查询
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
        """将技能模板展开为 DAG 节点。

        Args:
            skill: 来自 ctx.matched_skills 的匹配技能
            base_dag: 现有认知 DAG 计划
            ctx: 当前认知上下文

        Returns:
            追加技能步骤后的 DagPlanSpec
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

        # 从上下文解析参数值
        resolved_params = self._resolve_parameters(template_params, ctx)

        # 找到基础 DAG 中最后一个节点 ID（用于依赖链）
        base_node_ids = {n.node_id for n in base_dag.nodes}
        prev_step_ids: set[str] = set()

        # 若步骤需基于基础查询构建，则首步依赖 compiler
        first_step_deps: list[str] = []
        if base_node_ids:
            compiler_exists = "compiler" in base_node_ids
            if compiler_exists:
                first_step_deps = ["compiler"]
            else:
                # 依赖所有现有节点
                first_step_deps = sorted(base_node_ids)

        new_nodes: list[DagNodeSpec] = []
        skill_step_ids: dict[str, str] = {}  # step_id → node_id

        for i, step in enumerate(steps):
            step_id = step.get("id", f"skill_step_{i}")
            agent_name = step.get("agent", "data")
            agent_type = self.AGENT_TYPE_MAP.get(agent_name, agent_name)

            # 解析依赖
            deps: list[str] = []
            if i == 0 and first_step_deps:
                deps = first_step_deps
            else:
                for dep_id in step.get("depends_on", []):
                    if dep_id in skill_step_ids:
                        deps.append(skill_step_ids[dep_id])
                    elif dep_id in base_node_ids:
                        deps.append(dep_id)

            # 解析步骤参数
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

        # 合并基础 DAG + 技能步骤
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
        """从上下文解析模板参数。"""
        resolved: dict[str, str] = {}

        for param_name, param_def in template_params.items():
            if isinstance(param_def, dict):
                default = param_def.get("default", "")
            else:
                default = str(param_def)

            # 尝试从上下文解析
            value = self._resolve_value(param_name, default, ctx)
            resolved[param_name] = value

        return resolved

    def _resolve_value(
        self, name: str, default: str, ctx: CognitiveContext
    ) -> str:
        """从上下文解析单个参数值。"""
        # 检查时间窗口
        if name == "time_window" and ctx.time_window:
            tw = ctx.time_window
            return tw.get("description", str(tw.get("days", default)))

        # 检查指标
        if name == "metric" and ctx.metrics:
            return ctx.metrics[0].get("mention", default)

        if name == "cohort_dimension" and ctx.intent:
            dims = ctx.intent.get("dimensions", [])
            return dims[0] if dims else default

        # 直接检查查询
        if name in ("query",):
            return ctx.query or default

        return default

    def _resolve_step_params(
        self,
        step_params: dict,
        resolved: dict[str, str],
        ctx: CognitiveContext,
    ) -> dict:
        """将步骤参数中的 $param 引用替换为已解析的值。"""
        result: dict = {}
        for key, val in step_params.items():
            if isinstance(val, str) and val.startswith("$"):
                param_name = val[1:]
                result[key] = resolved.get(param_name, val)
            else:
                result[key] = val
        return result

    def get_skill_agent_types(self, skill: dict) -> list[str]:
        """返回技能步骤所需的 agent 类型列表。"""
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
