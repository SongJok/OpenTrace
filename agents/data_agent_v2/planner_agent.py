"""
PlannerAgent — 汇总各认知 Agent 输出为 LogicalPlan（查询 DAG）。

封装 QueryPlanner，注入上游上下文：实体、指标定义、时间窗、JOIN 路径、
语义上下文、分析技能模板（若匹配）。

LLM（PLANNING）+ 硬校验 + 确定性回退。
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)

# 使用 GROUP BY + 聚合的意图类型
_DEFAULT_PLAN_ANALYTICAL_INTENTS = frozenset({
    "aggregation", "ranking", "distribution", "composition",
    "comparison", "trend", "anomaly_detection",
})


class PlannerAgent(BaseAgent):
    """从所有上游认知输出生成 LogicalPlan（查询 DAG）。

    这是推理层的"大脑" — 将所有认知证据综合为
    SQLCompilerAgent 可执行的具体查询计划。
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
            # 回退：从实体 + 指标构建最小计划
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
        """基于 LLM 的计划生成，含校验和重试。

        对于分析型意图（聚合、分布、排名等），当 IntentAgent 已解析
        维度→表映射时，跳过 LLM 直接使用确定性回退。这避免 LLM
        在 GROUP BY 查询中幻觉出错误的表/列。
        """
        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""
        dimensions = intent.get("dimensions", []) or [] if isinstance(intent, dict) else []

        # 对分析型查询跳过 LLM — 确定性代码比忽略约束的 LLM 更可靠
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

                # 校验计划是否符合 Schema
                errors = self._validate_plan(plan, ctx)
                if not errors:
                    return plan

                # 带错误反馈重试
                if attempt < 1:
                    prompt = f"{prompt}\n\nPrevious plan had errors:\n" + "\n".join(errors) + "\nGenerate a corrected plan."

            except json.JSONDecodeError:
                continue

        # 所有尝试失败 — 使用回退
        return await self._fallback_plan(ctx)

    @staticmethod
    def _table_alias(table_name: str) -> str:
        """推导表的 SQL 别名，与 SQLBuilder._extract_alias() 保持一致。"""
        parts = table_name.strip().split()
        return parts[1] if len(parts) >= 2 else parts[0][0].lower()

    async def _fallback_plan(self, ctx: CognitiveContext) -> dict:
        """从可用认知数据构建最小 LogicalPlan。

        使用意图类型、实体、指标和查询文本，
        即使 LLM 不可用也能构建有意义的计划。
        """
        tables = ctx.table_names[:] or []
        if ctx.entities:
            for e in ctx.entities:
                # 仅使用表映射实体进行表选择。
                # 带 mapped_column 的实体是分类筛选器，不是表引用。
                if e.get("mapped_column"):
                    continue
                t = e.get("mapped_table", "")
                if t and t not in tables:
                    tables.append(t)

            # 若所有实体均为筛选类型，仍需从 mapped_table 获取表
            if not tables:
                for e in ctx.entities:
                    t = e.get("mapped_table", "")
                    if t and t not in tables:
                        tables.append(t)

        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""
        dimensions: list[str] = list(intent.get("dimensions", []) or [])

        # ── 解析投影 ──────────────────────────────────────────
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

        # 安全：构建所选表的有效列集合
        valid_columns: set[str] = set()
        for t in tables:
            for col in (ctx.table_columns or {}).get(t, []):
                valid_columns.add(col.lower())

        # 意图感知回退：若无指标但意图为分析型，
        # 生成 COUNT(*) + 维度投影，而非 SELECT *

        # 仅保留有效列的维度
        safe_dimensions = [d for d in dimensions if d.lower() in valid_columns]

        if not projections and intent_type in _DEFAULT_PLAN_ANALYTICAL_INTENTS:
            # 默认：COUNT(*) + GROUP BY 维度
            projections.append({
                "expr": "*",
                "alias": "count",
                "agg_func": "COUNT",
            })
            # 添加维度列作为标签投影（无聚合）
            for dim in safe_dimensions:
                projections.append({
                    "expr": dim,
                    "alias": dim,
                    "agg_func": None,
                })
        elif not projections and safe_dimensions:
            # 有维度但非分析意图 — 仍添加 COUNT(*)
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

        # ── 解析 group_by ─────────────────────────────────────────────
        group_by: list[str] = list(safe_dimensions)

        # 若意图无维度但为分析型，尝试从 schema 中匹配查询词的列
        if not group_by and intent_type in _DEFAULT_PLAN_ANALYTICAL_INTENTS:
            group_by = self._infer_group_by_from_query(ctx)

        # ── 解析 order_by ─────────────────────────────────────────────
        order_by: list[dict] = []
        if intent_type in ("ranking", "aggregation", "distribution"):
            # 按第一个指标投影降序排列
            for p in projections:
                if p.get("agg_func"):
                    col = p.get("alias") or p.get("expr", "")
                    if col and col != "*":
                        order_by.append({"expr": col, "direction": "DESC"})
                        break
            if not order_by and projections:
                order_by.append({"expr": projections[0].get("alias", "count"), "direction": "DESC"})
        elif intent_type == "trend" and group_by:
            # 若有时间列按时间升序，否则按计数降序
            first_gb = group_by[0].lower()
            is_time_col = any(t in first_gb for t in ("time", "date", "day", "month", "year", "week"))
            if is_time_col:
                order_by.append({"expr": group_by[0], "direction": "ASC"})
            else:
                order_by.append({"expr": projections[0].get("alias", "count"), "direction": "DESC"})

        # ── 筛选条件 ──────────────────────────────────────────────────
        filters: list[dict] = []
        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            days = ctx.time_window.get("days", 0)
            if days > 0:
                filters.append({"expr": f"__TIME_FILTER__{days}__", "is_having": False})

        # 基于实体的分类筛选（如 "队长" → dim_user.role = 'captain'）
        if ctx.entities:
            for e in ctx.entities:
                col = e.get("mapped_column", "")
                val = e.get("mapped_value", "")
                tbl = e.get("mapped_table", "")
                if col and val:
                    alias = self._table_alias(tbl)
                    safe_val = val.replace("'", "''")  # SQL 标准转义
                    expr = f"{alias}.{col} = '{safe_val}'"
                    filters.append({"expr": expr, "is_having": False})

        # ── JOIN ────────────────────────────────────────────────────────
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
        """从查询关键词与 schema 列名推断 GROUP BY 列。"""
        import re
        all_columns: dict[str, str] = {}  # col_name → table_name
        for table, cols in (ctx.table_columns or {}).items():
            for col in cols:
                all_columns[col.lower()] = col

        query = ctx.query or ""
        group_by = []
        # 匹配查询中出现的列名
        for col_lower, col_name in all_columns.items():
            if col_lower in query.lower() and col_name not in group_by:
                group_by.append(col_name)
        # 同时尝试从 schema_hint 匹配列名
        schema_lower = (ctx.schema_hint or "").lower()
        for col_lower, col_name in all_columns.items():
            if col_lower in query.lower() and col_name not in group_by:
                group_by.append(col_name)

        return group_by

    def _build_prompt(self, ctx: CognitiveContext) -> str:
        """从所有上游 Agent 输出构建完整提示词。"""
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
                # 将每个维度解析到其所属表，使 LLM
                # 选择正确的表，而非其他表中同名列。
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
                # 若某维度仅存在于一个表中，告知 LLM 使用该表
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

        # 若匹配到分析技能模板则注入
        if ctx.matched_skills:
            skill = ctx.matched_skills[0]
            if skill.get("plan_template"):
                import json
                parts.append(f"Skill Template ({skill['name']}):\n{json.dumps(skill['plan_template'], ensure_ascii=False)}")
            if skill.get("sql_template"):
                parts.append(f"Reference SQL:\n{skill['sql_template']}")

        return "\n\n".join(parts)

    def _validate_plan(self, plan: dict, ctx: CognitiveContext) -> list[str]:
        """根据已知 schema 和意图语义校验计划。"""
        errors: list[str] = []
        valid_tables = set(ctx.table_names)

        for table in plan.get("tables", []):
            if table not in valid_tables:
                errors.append(f"Table '{table}' not found in schema. Valid tables: {', '.join(sorted(valid_tables))}")

        # 校验 JOIN 表是否存在
        for join in plan.get("joins", []):
            for part in (join.get("on_clause", "") or "").split():
                if "." in part:
                    t = part.split(".")[0]
                    if t not in valid_tables:
                        errors.append(f"Join references unknown table '{t}'")

        # 语义校验：意图与计划一致性
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
                # 有具体列但无聚合 — 某些意图下可接受
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
