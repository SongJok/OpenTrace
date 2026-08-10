"""
EntityAgent — 将自然语言实体提及映射到表/列。

封装 SchemaLinker，并用知识层 schema_metadata、table_relationships  grounding；
优先规则匹配，必要时 LLM 回退。
"""

from __future__ import annotations

import json
import re

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
                evidence=[
                    self._make_evidence(
                        source="entity_resolver",
                        source_type="data_cognition",
                        payload={"entities": entities},
                        credibility=0.85,
                        relevance=0.95,
                    )
                ],
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

        # 人工审核的表级业务名、别名和说明优先于物理表名猜测。
        for table_meta in ctx.table_semantics or []:
            candidates = [
                table_meta.get("business_name"),
                *(table_meta.get("aliases") or []),
            ]
            description = str(table_meta.get("business_description") or "").lower()
            matched = next(
                (str(value) for value in candidates if value and str(value).lower() in query_lower),
                None,
            )
            if matched or (
                description
                and any(word in query_lower for word in description.split() if len(word) >= 2)
            ):
                entities.append(
                    {
                        "mention": matched or table_meta.get("business_name"),
                        "mapped_table": table_meta["table_name"],
                        "confidence": 0.95 if matched else 0.75,
                        "source": "schema_table_metadata",
                    }
                )

        # 第一轮：精确表名匹配
        for table in ctx.table_names:
            if table.lower() in query_lower:
                entities.append(
                    {
                        "mention": table,
                        "mapped_table": table,
                        "confidence": 1.0,
                        "source": "exact_match",
                    }
                )

        # 没有表注释时，历史 SQL 仍能提供“业务词 → 物理表/字段”的证据。
        # 只消费当前数据源已通过范围校验的资产摘要，不把资产 SQL 当作执行语句。
        if not entities and ctx.sql_asset_context:
            query_tokens = set(re.findall(r"[a-zA-Z0-9_]+", query_lower))
            query_tokens.update(
                part
                for segment in re.findall(r"[\u4e00-\u9fff]{2,}", query_lower)
                for part in (
                    segment,
                    *(segment[index : index + 2] for index in range(len(segment) - 1)),
                )
            )
            id_match = re.search(
                r"(?P<label>[\w\u4e00-\u9fff]{0,32})\s*id\s*(?:=|为|是|:)\s*(?P<value>\d+)",
                ctx.query,
                flags=re.IGNORECASE,
            )
            label = str(id_match.group("label") or "").lower() if id_match else ""
            label_hints = {
                "队长": "captain",
                "用户": "user",
                "主播": "anchor",
                "玩家": "player",
                "订单": "order",
            }
            label_hint = next((value for key, value in label_hints.items() if key in label), "")
            selected_asset = None
            for asset in ctx.sql_asset_context:
                searchable = " ".join(
                    [
                        str(asset.get("title") or ""),
                        str(asset.get("description") or ""),
                        json.dumps(asset.get("knowledge_metadata") or {}, ensure_ascii=False),
                        " ".join(str(value) for value in asset.get("tables") or []),
                        " ".join(str(value) for value in asset.get("columns") or []),
                        str(asset.get("sql") or ""),
                    ]
                ).lower()
                if query_tokens and any(token in searchable for token in query_tokens):
                    selected_asset = asset
                    break
            if selected_asset:
                available = {str(table).lower(): str(table) for table in ctx.table_names}
                asset_tables = []
                for raw_table in selected_asset.get("tables") or []:
                    table = str(raw_table or "").strip()
                    if not table:
                        continue
                    mapped = available.get(table.lower())
                    if mapped is None:
                        bare = table.rsplit(".", 1)[-1].lower()
                        matches = [
                            value
                            for key, value in available.items()
                            if key.rsplit(".", 1)[-1] == bare
                        ]
                        mapped = matches[0] if len(matches) == 1 else None
                    if mapped and mapped not in asset_tables:
                        asset_tables.append(mapped)
                if asset_tables:
                    mapped_table = asset_tables[0]
                    if id_match:
                        candidates = [
                            str(value).split(".")[-1]
                            for value in selected_asset.get("columns") or []
                            if re.search(r"(?:^|_)id$", str(value).split(".")[-1], re.I)
                        ]
                        candidates.extend(
                            column
                            for column in (ctx.table_columns or {}).get(mapped_table, [])
                            if re.search(r"(?:^|_)id$", str(column), re.I)
                        )
                        candidates = list(dict.fromkeys(candidates))
                        if label_hint:
                            candidates.sort(
                                key=lambda value: (label_hint not in value.lower(), -len(value))
                            )
                        if candidates:
                            entities.append(
                                {
                                    "mention": label or "id",
                                    "mapped_table": mapped_table,
                                    "mapped_column": candidates[0],
                                    "mapped_value": id_match.group("value"),
                                    "confidence": 0.86,
                                    "source": "sql_asset_reference",
                                }
                            )
                    if not entities:
                        entities.extend(
                            {
                                "mention": table,
                                "mapped_table": table,
                                "confidence": 0.82,
                                "source": "sql_asset_reference",
                            }
                            for table in asset_tables
                        )

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
                        entities.append(
                            {
                                "mention": label_str,
                                "mapped_table": table_name,
                                "mapped_column": col_name,
                                "mapped_value": str(db_value),
                                "mapped_value_label": label_str,
                                "confidence": 0.92,
                                "source": "value_map_match",
                            }
                        )

        # 第二轮：使用 schema_metadata 业务名称
        if ctx.column_semantics:
            seen_tables = {e["mapped_table"] for e in entities}
            for col_meta in ctx.column_semantics:
                if col_meta["table_name"] in seen_tables:
                    continue
                biz_name = (col_meta.get("business_name") or "").lower()
                biz_desc = (col_meta.get("business_description") or "").lower()
                if biz_name and biz_name in query_lower:
                    entities.append(
                        {
                            "mention": col_meta["business_name"],
                            "mapped_table": col_meta["table_name"],
                            "confidence": 0.9,
                            "source": "schema_metadata_business_name",
                        }
                    )
                elif biz_desc and any(w in query_lower for w in biz_desc.split() if len(w) >= 2):
                    entities.append(
                        {
                            "mention": col_meta["business_name"] or col_meta["table_name"],
                            "mapped_table": col_meta["table_name"],
                            "confidence": 0.7,
                            "source": "schema_metadata_description",
                        }
                    )

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
