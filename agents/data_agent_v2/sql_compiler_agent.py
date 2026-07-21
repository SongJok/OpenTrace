"""
SQLCompilerAgent — 确定性 LogicalPlan → SQL 编译。

封装 SQLBuilder，含方言转义与时间过滤渲染。
无 LLM — 相同 LogicalPlan 与方言下 100% 确定性。
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class SQLCompilerAgent(BaseAgent):
    """将 LogicalPlan 编译为目标方言的可执行 SQL。

    纯确定性 — 在 SQLBuilder.build() 上增加校验与方言转义。
    """

    def __init__(self) -> None:
        super().__init__("data_compiler")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            plan_dict = ctx.logical_plan
            if not plan_dict:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="no logical_plan in cognitive context",
                    metadata={"cognitive_context": ctx.to_dict()},
                )

            sql = await self._compile(plan_dict, ctx)

            ctx.compiled_sql = sql

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=sql,
                confidence=0.98,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="sql_compiler",
                    source_type="data_cognition",
                    payload={"sql": sql, "dialect": str(ctx.dialect)},
                    credibility=0.98,
                    relevance=1.0,
                )],
                agent_trace={
                    "dialect": str(ctx.dialect),
                    "compilation": "deterministic",
                },
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=str(exc),
                metadata={"cognitive_context": ctx.to_dict()},
            )

    async def _compile(self, plan_dict: dict, ctx: CognitiveContext) -> str:
        """将计划字典转换为 LogicalPlan 再编译为 SQL。"""
        from kernel.data_cognition.logical_plan import LogicalPlan
        from kernel.data_cognition.sql_builder import SQLBuilder
        from kernel.data_cognition.sql_dialect import SQLDialectSpec

        plan = LogicalPlan.from_dict(plan_dict)

        dialect = SQLDialectSpec(
            name=ctx.dialect if ctx.dialect else "postgresql",
            schema_name="information_schema",
            supports_interval_days=ctx.dialect not in ("clickhouse", "doris"),
        )

        # 若 time_window 存在则注入时间过滤
        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            self._inject_time_filter(plan, ctx.time_window, dialect)

        builder = SQLBuilder(default_limit=100)
        return builder.build(plan, dialect)

    def _inject_time_filter(
        self, plan, time_window: dict, dialect
    ) -> None:
        """根据已解析的 time_window 向计划添加时间过滤。"""
        col_hint = time_window.get("column_hint", "")
        days = time_window.get("days", 0)
        start = time_window.get("start", "")
        end = time_window.get("end", "")
        comparison = time_window.get("comparison", "")

        if comparison:
            # 处理对比型时间窗口（环比/同比）— 使用标记
            from kernel.data_cognition.logical_plan import FilterSpec
            plan.filters.append(FilterSpec(
                expr=f"__TIME_COMPARISON__{comparison}__{col_hint}__",
                is_having=False,
            ))
        elif start and end:
            from kernel.data_cognition.logical_plan import FilterSpec
            if col_hint:
                plan.filters.append(FilterSpec(
                    expr=f"{col_hint} >= '{start}' AND {col_hint} <= '{end}'",
                    is_having=False,
                ))
            else:
                plan.filters.append(FilterSpec(
                    expr=f"__TIME_FILTER__{days}__",
                    is_having=False,
                ))
        elif days > 0:
            from kernel.data_cognition.logical_plan import FilterSpec
            plan.filters.append(FilterSpec(
                expr=f"__TIME_FILTER__{days}__",
                is_having=False,
            ))
