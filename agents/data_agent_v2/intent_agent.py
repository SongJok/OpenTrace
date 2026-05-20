"""
IntentAgent — NL → Structured Analytical Intent.

Classifies the user query into a fine-grained analytical intent type
(aggregation, filtering, ranking, trend, comparison, etc.) and extracts
parameters like target entity, metric, dimensions, time window, output format.

Uses LLM (PLANNING role) for classification with a structured JSON output.
"""
from __future__ import annotations

import json

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    INTENT_TYPES,
    pack_cognitive_result,
    unpack_cognitive_context,
)


INTENT_SYSTEM_PROMPT = """You are an analytical intent classifier. Analyze the user query and output a JSON object with:

{
  "intent_type": "<one of: aggregation, filtering, ranking, trend, comparison, distribution, raw_lookup, metadata, anomaly_detection, funnel, cohort, composition>",
  "target_entity": "<main entity/table the user is asking about>",
  "metric": "<what metric is being queried, if any>",
  "dimensions": ["<list of group-by dimensions>"],
  "filters": ["<list of filter conditions expressed in natural language>"],
  "time_window": "<brief description of time constraint, or null>",
  "output_format": "table|chart|summary|raw",
  "confidence": <0.0-1.0>
}

Rules:
- intent_type "metadata" for queries about table list, table schema, table count
- intent_type "aggregation" for queries with SUM/COUNT/AVG/total by group
- intent_type "trend" for queries about changes over time
- intent_type "ranking" for queries asking for top/bottom N
- intent_type "comparison" for queries comparing periods or groups
- intent_type "raw_lookup" for simple lookups without aggregation
- Only output the JSON object, no other text."""


class IntentAgent(BaseAgent):
    """Classify user query into structured analytical intent."""

    def __init__(self) -> None:
        super().__init__("data_intent")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            # Fast path: metadata queries (table_count, table_list, table_schema)
            metadata_sql = self._check_structured_intent(ctx)
            if metadata_sql:
                ctx.intent = {
                    "intent_type": "metadata",
                    "target_entity": "",
                    "metric": "",
                    "dimensions": [],
                    "filters": [],
                    "time_window": None,
                    "output_format": "table",
                    "confidence": 1.0,
                }
                ctx.compiled_sql = metadata_sql  # Bypass entire pipeline
                ctx.verification_report = {"status": "pass", "issues": []}

                return pack_cognitive_result(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="success",
                    content="metadata query — bypassing reasoning pipeline",
                    confidence=1.0,
                    ctx=ctx,
                    evidence=[self._make_evidence(
                        source="intent_agent",
                        source_type="data_cognition",
                        payload={"intent": ctx.intent, "fast_path": "metadata"},
                        credibility=1.0,
                        relevance=1.0,
                    )],
                )

            # LLM classification
            intent = await self._classify_intent(ctx)
            ctx.intent = intent

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=json.dumps(intent, ensure_ascii=False),
                confidence=intent.get("confidence", 0.7),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="intent_agent",
                    source_type="data_cognition",
                    payload={"intent": intent},
                    credibility=0.85,
                    relevance=1.0,
                )],
            )
        except Exception as exc:
            # Fallback: generic intent
            ctx.intent = {
                "intent_type": "aggregation",
                "target_entity": "",
                "metric": "",
                "dimensions": [],
                "filters": [],
                "time_window": None,
                "output_format": "table",
                "confidence": 0.3,
            }
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="intent classification fallback",
                confidence=0.3,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    def _check_structured_intent(self, ctx: CognitiveContext) -> str | None:
        """Detect metadata queries and return direct SQL.

        Reuses the structured intent detection from SemanticParser.
        """
        try:
            from kernel.data_cognition.semantic_parser import SemanticParser

            parser = SemanticParser()
            return parser.check_structured_intent(
                ctx.query,
                ctx.table_names,
                "",  # database_name
                ctx.dialect,
            )
        except Exception:
            return None

    async def _classify_intent(self, ctx: CognitiveContext) -> dict:
        """LLM-based intent classification."""
        from model.model_gateway.gateway import LLMRole, get_model_gateway
        from model.llm_adapter.base import LLMMessage

        gw = get_model_gateway()

        # Build user prompt with schema context
        schema_summary = ctx.schema_hint or ", ".join(ctx.table_names)
        user_msg = f"Query: {ctx.query}\nAvailable tables: {schema_summary}"

        try:
            response = await gw.chat(
                messages=[
                    LLMMessage(role="system", content=INTENT_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=user_msg),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=256,
            )

            intent = json.loads(response.content.strip())

            # Validate required fields
            intent.setdefault("intent_type", "aggregation")
            intent.setdefault("target_entity", "")
            intent.setdefault("metric", "")
            intent.setdefault("dimensions", [])
            intent.setdefault("filters", [])
            intent.setdefault("time_window", None)
            intent.setdefault("output_format", "table")
            intent.setdefault("confidence", 0.7)

            # Validate intent_type is valid
            if intent["intent_type"] not in INTENT_TYPES:
                intent["intent_type"] = "aggregation"

            return intent

        except json.JSONDecodeError:
            # Try to extract JSON from text
            return await self._heuristic_intent(ctx)

    async def _heuristic_intent(self, ctx: CognitiveContext) -> dict:
        """Keyword-based heuristic fallback."""
        q = ctx.query.lower()

        if any(w in q for w in ("表", "table", "schema", "字段", "列", "结构")):
            if any(w in q for w in ("多少", "几个", "哪些")):
                return {"intent_type": "metadata", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "table", "confidence": 0.8}
            return {"intent_type": "metadata", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "table", "confidence": 0.6}

        if any(w in q for w in ("趋势", "趋势图", "变化", "走势")):
            return {"intent_type": "trend", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "chart", "confidence": 0.55}

        if any(w in q for w in ("排名", "top", "前", "最高", "最低", "最大", "最小")):
            return {"intent_type": "ranking", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "table", "confidence": 0.55}

        if any(w in q for w in ("对比", "比较", "vs", "环比", "同比")):
            return {"intent_type": "comparison", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "table", "confidence": 0.55}

        if any(w in q for w in ("汇总", "统计", "各", "每个", "按", "每", "合计")):
            return {"intent_type": "aggregation", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "table", "confidence": 0.55}

        return {"intent_type": "raw_lookup", "target_entity": "", "metric": "", "dimensions": [], "filters": [], "time_window": None, "output_format": "table", "confidence": 0.3}
