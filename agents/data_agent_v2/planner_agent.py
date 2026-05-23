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

# Intent types that use GROUP BY + aggregation
_DEFAULT_PLAN_ANALYTICAL_INTENTS = frozenset({
    "aggregation", "ranking", "distribution", "composition",
    "comparison", "trend", "anomaly_detection",
})


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
        """LLM-based plan generation with validation and retry.

        For analytical intents (aggregation, distribution, ranking, etc.) where
        the IntentAgent has already resolved dimension→table mappings, we skip
        the LLM entirely and use the deterministic fallback. This avoids the LLM
        hallucinating wrong tables/columns for GROUP BY queries.
        """
        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""
        dimensions = intent.get("dimensions", []) or [] if isinstance(intent, dict) else []

        # Bypass LLM for analytical queries — deterministic code is more reliable
        # for GROUP BY + aggregation patterns than an LLM that ignores constraints.
        if intent_type in _DEFAULT_PLAN_ANALYTICAL_INTENTS and dimensions:
            return await self._fallback_plan(ctx)

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

    @staticmethod
    def _table_alias(table_name: str) -> str:
        """Derive the SQL alias for a table, matching SQLBuilder._extract_alias()."""
        parts = table_name.strip().split()
        return parts[1] if len(parts) >= 2 else parts[0][0].lower()

    async def _fallback_plan(self, ctx: CognitiveContext) -> dict:
        """Build minimal LogicalPlan from available cognitive data.

        Uses intent type, entities, metrics, and query text to construct
        a meaningful plan even when LLM is unavailable.
        """
        tables = ctx.table_names[:] or []
        if ctx.entities:
            for e in ctx.entities:
                # Only use table-mapping entities for table selection.
                # Entities with mapped_column are categorical filters, not table refs.
                if e.get("mapped_column"):
                    continue
                t = e.get("mapped_table", "")
                if t and t not in tables:
                    tables.append(t)

            # If all entities are filter-type, still need tables from their mapped_table
            if not tables:
                for e in ctx.entities:
                    t = e.get("mapped_table", "")
                    if t and t not in tables:
                        tables.append(t)

        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""
        dimensions: list[str] = list(intent.get("dimensions", []) or [])

        # ── Resolve projections ──────────────────────────────────────────
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

        # Safety: build set of valid columns for the selected tables
        valid_columns: set[str] = set()
        for t in tables:
            for col in (ctx.table_columns or {}).get(t, []):
                valid_columns.add(col.lower())

        # Intent-aware fallback: if no metrics but intent is analytical,
        # generate COUNT(*) + dimension projections instead of SELECT *

        # Filter dimensions to only valid columns
        safe_dimensions = [d for d in dimensions if d.lower() in valid_columns]

        if not projections and intent_type in _DEFAULT_PLAN_ANALYTICAL_INTENTS:
            # Default: COUNT(*) with GROUP BY on dimensions
            projections.append({
                "expr": "*",
                "alias": "count",
                "agg_func": "COUNT",
            })
            # Add dimension columns as label projections (no aggregation)
            for dim in safe_dimensions:
                projections.append({
                    "expr": dim,
                    "alias": dim,
                    "agg_func": None,
                })
        elif not projections and safe_dimensions:
            # Has dimensions but no analytical intent — still add COUNT(*)
            projections.append({
                "expr": "*",
                "alias": "count",
                "agg_func": "COUNT",
            })
            for dim in safe_dimensions:
                projections.append({
                    "expr": dim,
                    "alias": dim,
                    "agg_func": None,
                })

        # ── Resolve group_by ─────────────────────────────────────────────
        group_by: list[str] = list(safe_dimensions)

        # If no dimensions from intent, but intent is analytical, try to
        # extract columns from schema that match query terms
        if not group_by and intent_type in _DEFAULT_PLAN_ANALYTICAL_INTENTS:
            group_by = self._infer_group_by_from_query(ctx)

        # ── Resolve order_by ─────────────────────────────────────────────
        order_by: list[dict] = []
        if intent_type in ("ranking", "aggregation", "distribution"):
            # Order by the first metric projection DESC
            for p in projections:
                if p.get("agg_func"):
                    col = p.get("alias") or p.get("expr", "")
                    if col and col != "*":
                        order_by.append({"expr": col, "direction": "DESC"})
                        break
            if not order_by and projections:
                order_by.append({"expr": projections[0].get("alias", "count"), "direction": "DESC"})
        elif intent_type == "trend" and group_by:
            # Order by time column ASC if available, otherwise by count DESC
            first_gb = group_by[0].lower()
            is_time_col = any(t in first_gb for t in ("time", "date", "day", "month", "year", "week"))
            if is_time_col:
                order_by.append({"expr": group_by[0], "direction": "ASC"})
            else:
                order_by.append({"expr": projections[0].get("alias", "count"), "direction": "DESC"})

        # ── Filters ──────────────────────────────────────────────────────
        filters: list[dict] = []
        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            days = ctx.time_window.get("days", 0)
            if days > 0:
                filters.append({"expr": f"__TIME_FILTER__{days}__", "is_having": False})

        # Entity-based categorical filters (e.g. "队长" → dim_user.role = 'captain')
        if ctx.entities:
            for e in ctx.entities:
                col = e.get("mapped_column", "")
                val = e.get("mapped_value", "")
                tbl = e.get("mapped_table", "")
                if col and val:
                    alias = self._table_alias(tbl)
                    safe_val = val.replace("'", "''")  # SQL-standard escaping
                    expr = f"{alias}.{col} = '{safe_val}'"
                    filters.append({"expr": expr, "is_having": False})

        # ── Joins ────────────────────────────────────────────────────────
        joins: list[dict] = []
        if ctx.join_paths:
            for jp in ctx.join_paths:
                path = jp.get("path", "")
                if path:
                    joins.append({"join_type": jp.get("type", "LEFT"), "on_clause": path})

        return {
            "tables": tables,
            "projections": projections or [{"expr": "*", "alias": None, "agg_func": None}],
            "filters": filters,
            "joins": joins,
            "group_by": group_by,
            "order_by": order_by,
            "limit": 100,
            "having": [],
            "metadata": {"source": "fallback", "confidence": 0.4, "intent_type": intent_type},
        }

    def _infer_group_by_from_query(self, ctx: CognitiveContext) -> list[str]:
        """Infer GROUP BY columns from query keywords matching schema columns."""
        import re
        all_columns: dict[str, str] = {}  # col_name → table_name
        for table, cols in (ctx.table_columns or {}).items():
            for col in cols:
                all_columns[col.lower()] = col

        query = ctx.query or ""
        group_by = []
        # Match column names mentioned in the query
        for col_lower, col_name in all_columns.items():
            if col_lower in query.lower() and col_name not in group_by:
                group_by.append(col_name)
        # Also try schema_hint for column mentions
        schema_lower = (ctx.schema_hint or "").lower()
        for col_lower, col_name in all_columns.items():
            if col_lower in query.lower() and col_name not in group_by:
                group_by.append(col_name)

        return group_by

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
                # Resolve each dimension to its parent table(s) so the LLM
                # picks the right table, not a similarly-named column elsewhere.
                dim_table_map: dict[str, list[str]] = {}
                for d in dims:
                    parents = []
                    for t, cols in (ctx.table_columns or {}).items():
                        if d in cols:
                            parents.append(t)
                    dim_table_map[d] = parents
                dim_strs = [f"{d} (table: {dim_table_map[d][0]})" if dim_table_map.get(d)
                           else d for d in dims]
                parts.append(f"Dimensions: {', '.join(dim_strs)}")
                # If any dimension is found in exactly one table, tell the LLM
                # to use that table
                dim_tables = set()
                for parents in dim_table_map.values():
                    dim_tables.update(parents)
                if dim_tables:
                    parts.append(f"Dimension Tables (MUST use): {', '.join(sorted(dim_tables))}")

            intent_filters = ctx.intent.get("filters", [])
            if intent_filters:
                parts.append(f"Filters (自然语言): {', '.join(intent_filters)}")

        if ctx.metrics:
            metric_strs = [
                f"{m.get('mention', '')} → {m.get('mapped_column', '')} ({m.get('agg', 'SUM')})"
                + (f" [formula: {m.get('formula', '')}]" if m.get('formula') else "")
                for m in ctx.metrics
            ]
            parts.append("Metrics:\n" + "\n".join(metric_strs))

        if ctx.entities:
            entity_strs = []
            for e in ctx.entities:
                mention = e.get("mention", "")
                tbl = e.get("mapped_table", "")
                col = e.get("mapped_column", "")
                val = e.get("mapped_value", "")
                if col and val:
                    alias = self._table_alias(tbl)
                    safe_val = val.replace("'", "''")
                    entity_strs.append(
                        f"{mention} → FILTER {alias}.{col} = '{safe_val}' (table: {tbl})"
                    )
                else:
                    entity_strs.append(f"{mention} → {tbl}")
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
        """Validate plan against known schema and intent semantics."""
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

        # Semantic validation: intent-plan alignment
        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""

        if intent_type in _DEFAULT_PLAN_ANALYTICAL_INTENTS:
            projections = plan.get("projections", [])
            group_by = plan.get("group_by", [])
            has_agg = any(p.get("agg_func") for p in projections)
            has_star_only = (
                len(projections) == 1
                and projections[0].get("expr") == "*"
                and not projections[0].get("agg_func")
            )

            if has_star_only:
                errors.append(
                    f"Intent is '{intent_type}' but plan uses SELECT * with no aggregation. "
                    f"Add agg_func (COUNT/SUM/AVG) to projections and specify group_by."
                )

            if not has_agg and not has_star_only:
                # Has specific columns but no aggregation — might be OK for some intents
                pass

            dimensions: list[str] = list(intent.get("dimensions", []) or [])
            if dimensions and not group_by:
                errors.append(
                    f"Intent dimensions {dimensions} are not in group_by. "
                    f"Add them to group_by for correct aggregation."
                )

            if intent_type == "trend" and not group_by:
                errors.append(
                    "Trend intent requires a time column in group_by. "
                    "Add the time dimension column to group_by."
                )

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
- Entity FILTER constraints (e.g. "FILTER dim_user.role = 'captain'") MUST be added to the "filters" array
- If a skill template is provided, use it as reference
- Tables in "tables" must match tables from the schema exactly
- When "Dimension Tables (MUST use)" is in the prompt, include ONLY those tables. Do NOT add unrelated tables.
- Every dimension is annotated with its parent table (e.g. "grade_name (table: dim_user)"). Use the annotated table — never substitute a column from a different table.

CRITICAL — Intent-driven plan generation:
- If intent_type is "aggregation" or "distribution": you MUST include agg_func (COUNT/SUM/AVG/MAX/MIN) in projections, and you MUST put the dimension columns in group_by. DO NOT output {"expr": "*"} — that is WRONG for aggregation queries.
- If intent_type is "ranking": projections must include the ranking metric with agg_func, group_by must include the entity column, and order_by must sort by the metric DESC.
- If intent_type is "comparison": group_by the comparison dimension, include comparison metrics in projections.
- If intent_type is "trend": group_by must include the time column, projections must include the trend metric.
- If "dimensions" are provided in the context, put EVERY dimension column into both "projections" (without agg_func for label columns) and "group_by".
- If "metrics" are provided, use them directly in projections with their agg_func.
- If no metrics are provided but intent is aggregation/ranking/distribution, infer COUNT(*) with alias matching the question semantics.
- Only use {"expr": "*", "agg_func": null} for raw data queries (intent_type: "metadata", "query", or "inspection").

Only output JSON, no other text."""
