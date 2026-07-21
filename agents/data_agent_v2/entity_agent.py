"""
EntityAgent — 将自然语言实体提及映射到表/列。

封装 SchemaLinker，并用知识层 schema_metadata、table_relationships  grounding；
优先规则匹配，必要时 LLM 回退。
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    CognitiveContext,
    pack_cognitive_result,
    unpack_cognitive_context,
)


class EntityAgent(BaseAgent):
    """识别用户查询中引用的实体（表）。

    利用知识层 column_semantics 进行精确匹配，
    对模糊提及回退到 SchemaLinker 启发式 + LLM。
    """

    def __init__(self) -> None:
        super().__init__("data_entity")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            entities = await self._resolve_entities(ctx)
            ctx.entities = entities

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"resolved {len(entities)} entities",
                confidence=self._entity_confidence(entities),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="entity_resolver",
                    source_type="data_cognition",
                    payload={"entities": entities},
                    credibility=0.85,
                    relevance=0.95,
                )],
            )
        except Exception as exc:
            # 非关键错误 — 返回空实体，下游仍可规划
            ctx.entities = []
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="entity resolution failed, continuing with empty entities",
                confidence=0.3,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _resolve_entities(self, ctx: CognitiveContext) -> list[dict]:
        """使用基于规则的匹配 + schema_metadata 提示解析实体。"""
        entities: list[dict] = []
        query_lower = ctx.query.lower()

        # 第一轮：精确表名匹配
        for table in ctx.table_names:
            if table.lower() in query_lower:
                entities.append({
                    "mention": table,
                    "mapped_table": table,
                    "confidence": 1.0,
                    "source": "exact_match",
                })

        # 第 1.5 轮：value_map 分类筛选匹配
        # 例如查询包含"队长" → dim_user.role 有 value_map {"captain": "队长"}
        # → 生成 mapped_column="role", mapped_value="captain" 的实体
        if ctx.column_semantics:
            seen_filter_tables = set()
            for col_meta in ctx.column_semantics:
                value_map = col_meta.get("value_map") or {}
                if not value_map:
                    continue
                for db_value, label in value_map.items():
                    if not label:
                        continue
                    label_str = str(label)
                    if label_str in ctx.query:
                        table_name = col_meta["table_name"]
                        col_name = col_meta["column_name"]
                        # 去重：相同 table+column+value → 跳过
                        dedup_key = f"{table_name}:{col_name}:{db_value}"
                        if dedup_key in seen_filter_tables:
                            continue
                        seen_filter_tables.add(dedup_key)
                        entities.append({
                            "mention": label_str,
                            "mapped_table": table_name,
                            "mapped_column": col_name,
                            "mapped_value": str(db_value),
                            "mapped_value_label": label_str,
                            "confidence": 0.92,
                            "source": "value_map_match",
                        })

        # 第二轮：使用 schema_metadata 业务名称
        if ctx.column_semantics:
            seen_tables = {e["mapped_table"] for e in entities}
            for col_meta in ctx.column_semantics:
                if col_meta["table_name"] in seen_tables:
                    continue
                biz_name = (col_meta.get("business_name") or "").lower()
                biz_desc = (col_meta.get("business_description") or "").lower()
                if biz_name and biz_name in query_lower:
                    entities.append({
                        "mention": col_meta["business_name"],
                        "mapped_table": col_meta["table_name"],
                        "confidence": 0.9,
                        "source": "schema_metadata_business_name",
                    })
                elif biz_desc and any(w in query_lower for w in biz_desc.split() if len(w) >= 2):
                    entities.append({
                        "mention": col_meta["business_name"] or col_meta["table_name"],
                        "mapped_table": col_meta["table_name"],
                        "confidence": 0.7,
                        "source": "schema_metadata_description",
                    })

        # 第三轮：若仍无匹配，尝试通过 SchemaLinker 启发式匹配
        if not entities and len(ctx.table_names) > 0:
            entities = await self._fallback_schema_linker(ctx)

        return entities

    async def _fallback_schema_linker(self, ctx: CognitiveContext) -> list[dict]:
        """基于 LLM 的回退方案，使用 SchemaLinker 处理复杂实体提及。"""
        from kernel.data_cognition.schema_linker import SchemaLinker

        linker = SchemaLinker(
            schema_summary=ctx.schema_hint,
            table_names=ctx.table_names,
            table_columns=ctx.table_columns,
        )
        mappings = await linker.link_entities(ctx.query, ctx.table_columns)
        return [
            {
                "mention": m.mention,
                "mapped_table": m.mapped_table,
                "confidence": m.confidence,
                "source": "schema_linker_llm",
            }
            for m in mappings
        ]

    def _entity_confidence(self, entities: list[dict]) -> float:
        if not entities:
            return 0.3
        avg = sum(e.get("confidence", 0.5) for e in entities) / len(entities)
        return min(avg, 0.98)
