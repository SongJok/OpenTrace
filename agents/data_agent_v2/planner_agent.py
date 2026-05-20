"""
PlannerAgent — aggregates all cognitive outputs into a LogicalPlan (query DAG).

Wraps QueryPlanner with enriched context from all upstream agents:
- Entities + entity metadata
- Metric definitions
- Time window
- Join paths
- Semantic context
- Analytical skill templates (if matched)

LLM-based (PLANNING role) with hard validation and deterministic fallback.
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class PlannerAgent(BaseAgent):
    """Generate a LogicalPlan (query DAG) from all upstream cognitive outputs.

    This is the "brain" of the reasoning layer — it synthesizes all cognitive
    evidence into a concrete query plan that the SQLCompilerAgent can execute.
    """

    def __init__(self) -> None:
        super().__init__("data_planner")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            plan = await self._generate_plan(ctx)
            ctx.logical_plan = plan

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"plan generated: {len(plan.get('tables', []))} tables, {len(plan.get('projections', []))} projections",
                confidence=0.80,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="planner_agent",
                    source_type="data_cognition",
                    payload={"plan_tables": plan.get("tables", []), "plan_summary": plan.get("metadata", {})},
                    credibility=0.85,
                    relevance=1.0,
                )],
            )
        except Exception as exc:
            # Fallback: build minimal plan from entities + metrics
            plan = await self._fallback_plan(ctx)
            ctx.logical_plan = plan
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="plan generated via fallback",
                confidence=0.4,
                metadata={"cognitive_context": ctx.to_dict()},
                agent_trace={"warning": f"LLM plan failed, using fallback: {exc}"},
            )

    async def _generate_plan(self, ctx: CognitiveContext) -> dict:
        """LLM-based plan generation with validation and retry."""
        from model.model_gateway.gateway import LLMRole, get_model_gateway
        from model.llm_adapter.base import LLMMessage

        prompt = self._build_prompt(ctx)
        gw = get_model_gateway()

        for attempt in range(2):
            try:
                response = await gw.chat(
                    messages=[
                        LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=prompt),
                    ],
                    role=LLMRole.PLANNING,
                    temperature=0.0,
                    max_tokens=600,
                )

                import json
                plan = json.loads(response.content.strip())

                # Validate against schema
                errors = self._validate_plan(plan, ctx)
                if not errors:
                    return plan

                # Retry with error feedback
                if attempt < 1:
                    prompt = f"{prompt}\n\nPrevious plan had errors:\n" + "\n".join(errors) + "\nGenerate a corrected plan."

            except json.JSONDecodeError:
                continue

        # All attempts failed — use fallback
        return await self._fallback_plan(ctx)

    async def _fallback_plan(self, ctx: CognitiveContext) -> dict:
        """Build minimal LogicalPlan from available cognitive data."""
        tables = ctx.table_names[:] or []
        if ctx.entities:
            for e in ctx.entities:
                t = e.get("mapped_table", "")
                if t and t not in tables:
                    tables.append(t)

        projections: list[dict] = []
        if ctx.metrics:
            for m in ctx.metrics:
                col = m.get("mapped_column", "")
                agg = m.get("agg", "SUM")
                if col:
                    projections.append({
                        "expr": col,
                        "alias": m.get("mention", f"agg_{col}"),
                        "agg_func": agg,
                    })

        filters: list[dict] = []
        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            days = ctx.time_window.get("days", 0)
            if days > 0:
                filters.append({"expr": f"__TIME_FILTER__{days}__", "is_having": False})

        joins: list[dict] = []
        if ctx.join_paths:
            for jp in ctx.join_paths:
                path = jp.get("path", "")
                if path:
                    joins.append({"join_type": jp.get("type", "LEFT"), "on_clause": path})

        group_by: list[str] = []
        if ctx.intent and ctx.intent.get("dimensions"):
            group_by = ctx.intent.get("dimensions", [])

        return {
            "tables": tables,
            "projections": projections or [{"expr": "*", "alias": None, "agg_func": None}],
            "filters": filters,
            "joins": joins,
            "group_by": group_by,
            "order_by": [],
            "limit": 100,
            "having": [],
            "metadata": {"source": "fallback", "confidence": 0.4},
        }

    def _build_prompt(self, ctx: CognitiveContext) -> str:
        """Build comprehensive prompt from all upstream agents."""
        parts = [
            f"User Query: {ctx.query}",
            f"Available Tables: {', '.join(ctx.table_names)}",
            f"Schema Hint: {ctx.schema_hint}",
            f"Dialect: {ctx.dialect}",
        ]

        if ctx.intent:
            parts.append(f"Intent: {ctx.intent.get('intent_type', '')}")
            parts.append(f"Target Entity: {ctx.intent.get('target_entity', '')}")
            parts.append(f"Target Metric: {ctx.intent.get('metric', '')}")
            dims = ctx.intent.get("dimensions", [])
            if dims:
                parts.append(f"Dimensions: {', '.join(dims)}")

        if ctx.metrics:
            metric_strs = [
                f"{m.get('mention', '')} → {m.get('mapped_column', '')} ({m.get('agg', 'SUM')})"
                + (f" [formula: {m.get('formula', '')}]" if m.get('formula') else "")
                for m in ctx.metrics
            ]
            parts.append("Metrics:\n" + "\n".join(metric_strs))

        if ctx.entities:
            entity_strs = [
                f"{e.get('mention', '')} → {e.get('mapped_table', '')}"
                for e in ctx.entities
            ]
            parts.append("Entities:\n" + "\n".join(entity_strs))

        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            tw = ctx.time_window
            parts.append(f"Time Window: {tw.get('description', '')} ({tw.get('start', '')} to {tw.get('end', '')})")
            if tw.get("column_hint"):
                parts.append(f"Time Column: {tw['column_hint']}")

        if ctx.join_paths:
            join_strs = [jp.get("path", "") for jp in ctx.join_paths]
            parts.append("Join Paths:\n" + "\n".join(join_strs))

        if ctx.semantic_context and ctx.semantic_context.get("resolved_sql_fragments"):
            parts.append(f"Semantic Hints:\n{ctx.semantic_context['resolved_sql_fragments']}")

        # Inject analytical skill template if available
        if ctx.matched_skills:
            skill = ctx.matched_skills[0]
            if skill.get("plan_template"):
                import json
                parts.append(f"Skill Template ({skill['name']}):\n{json.dumps(skill['plan_template'], ensure_ascii=False)}")
            if skill.get("sql_template"):
                parts.append(f"Reference SQL:\n{skill['sql_template']}")

        return "\n\n".join(parts)

    def _validate_plan(self, plan: dict, ctx: CognitiveContext) -> list[str]:
        """Validate plan against known schema."""
        errors: list[str] = []
        valid_tables = set(ctx.table_names)

        for table in plan.get("tables", []):
            if table not in valid_tables:
                errors.append(f"Table '{table}' not found in schema. Valid tables: {', '.join(sorted(valid_tables))}")

        # Validate join tables exist
        for join in plan.get("joins", []):
            for part in (join.get("on_clause", "") or "").split():
                if "." in part:
                    t = part.split(".")[0]
                    if t not in valid_tables:
                        errors.append(f"Join references unknown table '{t}'")

        return errors


PLANNER_SYSTEM_PROMPT = """You are a query planner. Given a user query and context from upstream cognitive analysis, generate a LogicalPlan as JSON.

Output format:
{
  "tables": ["table1", "table2"],
  "projections": [
    {"expr": "column_name", "alias": "readable_name", "agg_func": "SUM"}
  ],
  "joins": [
    {"left_table": "orders", "right_table": "users", "join_type": "LEFT", "on_clause": "orders.user_id = users.id"}
  ],
  "filters": [
    {"expr": "column > 100", "is_having": false}
  ],
  "group_by": ["column1", "column2"],
  "order_by": [{"expr": "column", "direction": "DESC"}],
  "limit": 100,
  "having": [],
  "metadata": {}
}

Rules:
- Use ONLY tables from the provided schema
- Use join paths from the context when available
- Use time filter marker __TIME_FILTER__N__ for time-based filters
- If a skill template is provided, use it as reference
- Tables in "tables" must match tables from the schema exactly
- Only output JSON, no other text."""
