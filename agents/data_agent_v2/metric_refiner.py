"""
MetricRefinerAgent — 从用户反馈抽取修正后的指标公式。

用户纠正指标（如「GMV 应不含税与退款」）时：
1. LLM 抽取修正公式、列与业务定义
2. 与现有 metric_definitions 对比
3. 创建新版草稿（version++）
4. 记录与原始指标的谱系

默认安全：所有修正均为待管理员审批的草稿版本。
"""
from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class MetricRefinerAgent(BaseAgent):
    """从用户反馈中抽取并应用指标公式修正。

    基于 LLM（PLANNING 角色）进行公式抽取，
    配合确定性的比较和版本管理。
    """

    def __init__(self) -> None:
        super().__init__("data_metric_refiner")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        correction_detail = task.params.get("correction_detail", {})
        corrected_metric_id = task.params.get("corrected_metric_id", "")

        if not correction_detail and not corrected_metric_id:
            return self._skip(task, ctx, "no metric correction to process")

        db = task.params.get("_db_session")

        try:
            # 1. 使用 LLM 抽取修正公式
            extraction = await self._extract_correction(ctx, correction_detail)

            if not extraction.get("formula"):
                return self._skip(task, ctx, "could not extract formula from correction")

            # 2. 若有原始指标，进行对比和版本管理
            if corrected_metric_id and db:
                await self._create_draft_version(db, corrected_metric_id, extraction, ctx)
            elif db and extraction.get("metric_name"):
                await self._create_new_metric(db, extraction, ctx)

            ctx.refined_metrics = [extraction]

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"metric refined: {extraction.get('metric_name', 'unknown')}",
                confidence=0.80,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="metric_refiner",
                    source_type="learning",
                    payload={
                        "metric_name": extraction.get("metric_name"),
                        "formula": extraction.get("formula"),
                        "version": extraction.get("version"),
                    },
                    credibility=0.80,
                    relevance=0.95,
                )],
                agent_trace={"refined_metric": extraction},
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="metric refinement skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _extract_correction(
        self, ctx: CognitiveContext, detail: dict
    ) -> dict[str, Any]:
        """使用 LLM 从用户反馈文本中抽取修正公式。"""
        from model.model_gateway.gateway import LLMRole, get_model_gateway
        from model.llm_adapter.base import LLMMessage

        correction_text = detail.get("correction", "")
        existing_metrics = ctx.matched_metrics or []

        # 从现有指标定义构建上下文
        metric_context = ""
        if existing_metrics:
            metric_context = "Current metric definitions:\n"
            for m in existing_metrics[:5]:
                metric_context += (
                    f"- {m.get('name', '')}: formula={m.get('formula', '')}, "
                    f"columns={m.get('underlying_columns', [])}, "
                    f"agg={m.get('agg_function', '')}, "
                    f"definition={m.get('business_definition', '')}\n"
                )

        prompt = (
            "Extract the corrected metric definition from the user's feedback. "
            "Return a JSON object with:\n"
            "- metric_name: the business name of the metric\n"
            "- formula: corrected SQL expression (use SQL aggregate + FILTER/CASE WHEN as needed)\n"
            "- underlying_columns: list of table.column the formula references\n"
            "- agg_function: SUM/COUNT/AVG/MAX/MIN/COUNT_DISTINCT\n"
            "- business_definition: clear business description of what the metric measures\n"
            "- unit: measurement unit (元, 人, 次, %, etc.)\n"
            "- correction_reason: what was wrong and how the correction fixes it\n"
            "- confidence: 0.0-1.0 how confident you are in this extraction\n\n"
            "Only output JSON, no other text. If unclear, set confidence low.\n\n"
            f"Query: {ctx.query}\n"
            f"Original SQL: {ctx.compiled_sql}\n"
            f"{metric_context}\n"
            f"User correction: {correction_text}"
        )

        try:
            gw = get_model_gateway()
            response = await gw.chat(
                messages=[
                    LLMMessage(role="system", content=METRIC_REFINER_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=500,
            )

            import json
            return json.loads(response.content.strip())
        except Exception:
            # 回退：使用启发式抽取
            return self._heuristic_extraction(correction_text, existing_metrics)

    def _heuristic_extraction(
        self, correction_text: str, existing_metrics: list[dict]
    ) -> dict[str, Any]:
        """LLM 不可用时的启发式抽取。"""
        result: dict[str, Any] = {
            "metric_name": "",
            "formula": "",
            "underlying_columns": [],
            "agg_function": "",
            "business_definition": correction_text[:200],
            "unit": "",
            "correction_reason": correction_text[:200],
            "confidence": 0.3,
        }

        # 尝试从现有指标中查找指标名
        for m in existing_metrics:
            name = m.get("name", "")
            if name and name.lower() in correction_text.lower():
                result["metric_name"] = name
                result["agg_function"] = m.get("agg_function", "")
                result["unit"] = m.get("unit", "")
                break

        # 尝试检测聚合函数
        for agg in ("SUM", "COUNT", "AVG", "MAX", "MIN", "COUNT_DISTINCT"):
            if agg.lower() in correction_text.lower():
                result["agg_function"] = agg
                break

        return result

    async def _create_draft_version(
        self,
        db,
        metric_id: str,
        extraction: dict,
        ctx: CognitiveContext,
    ) -> None:
        """为现有指标创建新的草稿版本。"""
        from infra.storage.models import MetricDefinition, MetricLineage

        result = await db.execute(
            __import__("sqlalchemy").select(MetricDefinition).where(
                MetricDefinition.id == metric_id
            )
        )
        existing = result.scalar()
        if not existing:
            return

        new_version = (existing.version or 1) + 1

        refined = MetricDefinition(
            data_source_id=existing.data_source_id,
            name=extraction.get("metric_name") or existing.name,
            aliases=existing.aliases,
            formula=extraction.get("formula") or existing.formula,
            underlying_columns=extraction.get("underlying_columns") or existing.underlying_columns,
            agg_function=extraction.get("agg_function") or existing.agg_function,
            business_definition=extraction.get("business_definition") or existing.business_definition,
            unit=extraction.get("unit") or existing.unit,
            category=existing.category,
            tags=existing.tags,
            sensitivity=existing.sensitivity,
            version=new_version,
            status="draft",
            created_by=existing.created_by,
        )
        db.add(refined)
        await db.flush()

        # 记录谱系
        lineage = MetricLineage(
            metric_id=refined.id,
            depends_on_metric_id=metric_id,
            transformation=f"User-corrected from version {existing.version}: {extraction.get('correction_reason', '')}",
            lineage_type="derived",
        )
        db.add(lineage)
        await db.commit()

    async def _create_new_metric(
        self,
        db,
        extraction: dict,
        ctx: CognitiveContext,
    ) -> None:
        """从用户反馈创建新的指标定义。"""
        from infra.storage.models import MetricDefinition

        if not ctx.data_source_id:
            return

        metric = MetricDefinition(
            data_source_id=ctx.data_source_id,
            name=extraction.get("metric_name", "user_defined_metric"),
            formula=extraction.get("formula", ""),
            underlying_columns=extraction.get("underlying_columns", []),
            agg_function=extraction.get("agg_function"),
            business_definition=extraction.get("business_definition"),
            unit=extraction.get("unit"),
            status="draft",
            version=1,
        )
        db.add(metric)
        await db.commit()

    def _skip(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"metric refinement skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"skip_reason": reason},
        )


METRIC_REFINER_SYSTEM_PROMPT = """You are a metric definition analyst. Extract corrected metric definitions from user feedback.

Rules:
- formula must be a valid SQL expression using aggregate functions (SUM, COUNT, AVG, etc.)
- Use FILTER or CASE WHEN for conditional logic
- underlying_columns should use "table.column" format
- business_definition should be a clear, plain-language description
- If the user's correction is ambiguous, set confidence low (below 0.5)
- Only output JSON, no other text"""
