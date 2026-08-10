"""
IntentAgent — 自然语言 → 结构化分析意图。

将用户查询细分为分析意图类型（聚合、过滤、排名、趋势、对比等），
并抽取目标实体、指标、维度、时间窗、输出格式等参数。

使用 LLM（PLANNING 角色）输出结构化 JSON。
"""

from __future__ import annotations

import json
import re

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    INTENT_TYPES,
    CognitiveContext,
    pack_cognitive_result,
    unpack_cognitive_context,
)

# 使用 GROUP BY + 聚合的意图类型
_ANALYTICAL_INTENTS = frozenset(
    {
        "aggregation",
        "ranking",
        "distribution",
        "composition",
        "comparison",
        "trend",
        "anomaly_detection",
    }
)


def _is_likely_non_dimension(col_name: str) -> bool:
    """判断某列是否不太可能作为语义 GROUP BY 维度。

    过滤掉：
    - ID 列（以 _id 结尾或名为 'id'）
    - 实体名称列（唯一标识符，非共享分类）
    - 指标/数值列（名为 'nums'、'count'、'amount' 等）
    - 时间戳列（以 _time、_at、_date 结尾）
    """
    lower = col_name.lower()
    # ID 列
    if lower == "id" or lower.endswith("_id") or lower.endswith("_Id"):
        return True
    # 实体名称列 — 这些是唯一标识符（每行一个），
    # 而非共享的分类维度。例如 GROUP BY user_name
    # 在聚合查询中几乎总是错误的。
    if lower in (
        "user_name",
        "product_name",
        "item_name",
        "person_name",
        "username",
        "customer_name",
        "client_name",
        "member_name",
        "player_name",
        "student_name",
        "teacher_name",
    ):
        return True
    # 类指标列
    if lower in (
        "nums",
        "num",
        "count",
        "amount",
        "total",
        "sum",
        "value",
        "quantity",
        "price",
        "cost",
        "score",
        "rate",
        "ratio",
        "avg",
    ):
        return True
    # 时间戳列
    if lower.endswith(("_time", "_at", "_date", "_ts", "_timestamp")):
        return True
    return False


INTENT_SYSTEM_PROMPT = """You are an analytical intent classifier. Analyze the user query and output a JSON object with:

{
  "intent_type": "<one of: aggregation, filtering, ranking, trend, comparison, distribution, raw_lookup, metadata, anomaly_detection, funnel, cohort, composition>",
  "target_entity": "<main entity/table the user is asking about>",
  "metric": "<what metric is being queried, if any>",
  "dimensions": ["<list of group-by dimension column names from the schema>"],
  "filters": ["<list of filter conditions expressed in natural language>"],
  "time_window": "<brief description of time constraint, or null>",
  "output_format": "table|chart|summary|raw",
  "confidence": <0.0-1.0>
}

Rules:
- intent_type "metadata" for queries about table list, table schema, table count
- intent_type "aggregation" for queries with SUM/COUNT/AVG/total by group (e.g. "统计每种XX的YY数量")
- intent_type "distribution" for queries asking about distribution/spread of values across categories
- intent_type "trend" for queries about changes over time
- intent_type "ranking" for queries asking for top/bottom N
- intent_type "comparison" for queries comparing periods or groups
- intent_type "raw_lookup" for simple lookups without aggregation

CRITICAL — dimensions extraction:
- dimensions MUST be populated for aggregation/distribution/ranking/comparison/trend intents
- Extract dimension column names from the query — look for words like "每种/各/按/每个" followed by a category name
- Match dimension names against actual column names from the available tables/schema
- Common patterns: "每种等级" → dimension=["grade_name"], "按地区" → dimension=["region"], "各月" → dimension=["month"]
- If a dimension is mentioned in parentheses like "等级名称(grade_name)" — use "grade_name"
- Leave dimensions as empty array ONLY for metadata and raw_lookup intents

Only output the JSON object, no other text."""


class IntentAgent(BaseAgent):
    """将用户查询分类为结构化分析意图。"""

    def __init__(self) -> None:
        super().__init__("data_intent")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            # 快路径：元数据查询（table_count、table_list、table_schema）
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
                ctx.compiled_sql = metadata_sql  # 跳过整个推理流水线
                ctx.verification_report = {"status": "pass", "issues": []}

                return pack_cognitive_result(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="success",
                    content="metadata query — bypassing reasoning pipeline",
                    confidence=1.0,
                    ctx=ctx,
                    evidence=[
                        self._make_evidence(
                            source="intent_agent",
                            source_type="data_cognition",
                            payload={"intent": ctx.intent, "fast_path": "metadata"},
                            credibility=1.0,
                            relevance=1.0,
                        )
                    ],
                )

            # LLM 分类
            intent = await self._classify_intent(ctx)
            ctx.intent = intent

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=json.dumps(intent, ensure_ascii=False),
                confidence=intent.get("confidence", 0.7),
                ctx=ctx,
                evidence=[
                    self._make_evidence(
                        source="intent_agent",
                        source_type="data_cognition",
                        payload={"intent": intent},
                        credibility=0.85,
                        relevance=1.0,
                    )
                ],
            )
        except Exception as exc:
            # 回退：基于启发式的意图识别（含 Schema 感知的维度提取）
            fallback = await self._heuristic_intent(ctx)
            ctx.intent = fallback
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
        """检测元数据查询并返回直接 SQL。

        复用 SemanticParser 的结构化意图检测。
        """
        try:
            from kernel.data_cognition.semantic_parser import SemanticParser
            from kernel.data_cognition.sql_dialect import detect_sql_dialect

            parser = SemanticParser()
            return parser.check_structured_intent(
                ctx.query,
                ctx.table_names,
                ctx.database_name,
                detect_sql_dialect(ctx.dialect),
            )
        except Exception:
            return None

    async def _classify_intent(self, ctx: CognitiveContext) -> dict:
        """基于 LLM 的意图分类。"""
        from model.llm_adapter.base import LLMMessage
        from model.model_gateway.gateway import LLMRole, get_model_gateway

        gw = get_model_gateway()

        # 构建 Schema 上下文的用户提示
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

            # 验证必填字段
            intent.setdefault("intent_type", "aggregation")
            intent.setdefault("target_entity", "")
            intent.setdefault("metric", "")
            intent.setdefault("dimensions", [])
            intent.setdefault("filters", [])
            intent.setdefault("time_window", None)
            intent.setdefault("output_format", "table")
            intent.setdefault("confidence", 0.7)

            # 验证 intent_type 是否合法
            if intent["intent_type"] not in INTENT_TYPES:
                intent["intent_type"] = "aggregation"

            # 对于分析型意图，始终使用 Schema 感知的维度提取。
            # LLM 在选取精确列名方面不可靠 — 它可能根据数据值
            # 而非 Schema 将 "grade_name" 与 "task_name" 混淆。
            # Schema 感知提取使用实际列名和注释。
            if intent["intent_type"] in _ANALYTICAL_INTENTS:
                schema_dims = self._extract_dimensions_from_query(ctx)
                if schema_dims:
                    intent["dimensions"] = schema_dims

            return intent

        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            return await self._heuristic_intent(ctx)

    async def _heuristic_intent(self, ctx: CognitiveContext) -> dict:
        """基于关键词的启发式回退，含 Schema 感知的维度提取。"""
        q = ctx.query.lower()
        dimensions = self._extract_dimensions_from_query(ctx)

        base_intent = {
            "target_entity": "",
            "metric": "",
            "dimensions": dimensions,
            "filters": [],
            "time_window": None,
        }

        # metadata — 仅当查询关于表/Schema 时，而非"表"作为
        # 位置限定词如"用户表中"或"订单表里"
        meta_structure = any(
            w in q
            for w in (
                "表结构",
                "schema",
                "字段",
                "列",
                "有哪些表",
                "多少张表",
                "几个表",
                "哪些表",
                "所有表",
            )
        )
        meta_question = any(w in q for w in ("多少", "几个", "哪些")) and any(
            w in q for w in ("表", "table")
        )
        if meta_structure or meta_question:
            return {
                **base_intent,
                "intent_type": "metadata",
                "output_format": "table",
                "confidence": 0.8,
            }

        if any(w in q for w in ("趋势", "趋势图", "变化", "走势")):
            return {
                **base_intent,
                "intent_type": "trend",
                "output_format": "chart",
                "confidence": 0.55,
            }

        if any(w in q for w in ("排名", "top", "前", "最高", "最低", "最大", "最小")):
            return {
                **base_intent,
                "intent_type": "ranking",
                "output_format": "table",
                "confidence": 0.55,
            }

        if any(w in q for w in ("对比", "比较", "vs", "环比", "同比")):
            return {
                **base_intent,
                "intent_type": "comparison",
                "output_format": "table",
                "confidence": 0.55,
            }

        if any(w in q for w in ("分布", "占比", "组成", "构成", "比例")):
            return {
                **base_intent,
                "intent_type": "distribution",
                "output_format": "table",
                "confidence": 0.55,
            }

        if any(w in q for w in ("汇总", "统计", "各", "每个", "按", "每", "合计")):
            return {
                **base_intent,
                "intent_type": "aggregation",
                "output_format": "table",
                "confidence": 0.55,
            }

        return {
            **base_intent,
            "intent_type": "raw_lookup",
            "output_format": "table",
            "confidence": 0.3,
        }

    def _extract_dimensions_from_query(self, ctx: CognitiveContext) -> list[str]:
        """通过匹配查询文本与 Schema 列名和注释，提取可能的 GROUP BY 列。

        仅返回列名或注释与查询匹配的表中的列，
        以避免跨表维度污染。
        """
        query_lower = (ctx.query or "").lower()
        query_text = ctx.query or ""
        dimensions = []

        # 从 schema_hint 构建列名 → (注释, 表名) 映射
        col_meta: dict[str, tuple[str, str]] = {}  # col_name → (comment, table_name)
        try:
            import json

            schema = json.loads(ctx.schema_hint) if ctx.schema_hint else {}
            tables = schema.get("tables", []) if isinstance(schema, dict) else []
            for t in tables:
                if not isinstance(t, dict):
                    continue
                tname = str(t.get("name", "")).strip()
                for c in t.get("columns", []) or []:
                    if not isinstance(c, dict):
                        continue
                    cname = str(c.get("name", "")).strip()
                    ccomment = str(c.get("comment", "")).strip()
                    if cname:
                        col_meta[cname] = (ccomment, tname)
        except (json.JSONDecodeError, TypeError):
            pass

        # 根据列名/注释匹配确定相关表
        matched_tables: set[str] = set()

        for col_name, (comment, table_name) in col_meta.items():
            col_lower = col_name.lower()
            # 直接列名匹配
            if col_lower in query_lower:
                dimensions.append(col_name)
                matched_tables.add(table_name)
                continue
            parts = col_lower.replace("_", " ")
            if parts in query_lower:
                dimensions.append(col_name)
                matched_tables.add(table_name)
                continue
            # 注释精确匹配
            if comment and comment in query_text:
                dimensions.append(col_name)
                matched_tables.add(table_name)
                continue
            # 通过中文词提取的注释部分匹配
            if comment:
                for word in self._extract_cn_words(query_text):
                    if len(word) >= 2 and word in comment:
                        dimensions.append(col_name)
                        matched_tables.add(table_name)
                        break

        # 从括号提示中提取列名
        paren_matches = re.findall(r"\((\w+)\)", query_text)
        for match in paren_matches:
            match_lower = match.lower()
            for col_name in col_meta:
                if col_name.lower() == match_lower and col_name not in dimensions:
                    dimensions.append(col_name)
                elif col_name.lower().startswith(match_lower) and col_name not in dimensions:
                    dimensions.append(col_name)

        # 优先移除非维度列，避免它们干扰表评分。
        # 例如 task_id（以 _id 结尾）和 nums（指标）会虚高
        # dwd_work_record_detail 的评分，导致选错表。
        dimensions = [d for d in dimensions if not _is_likely_non_dimension(d)]

        # 过滤：仅保留最相关表的维度
        if len(matched_tables) > 1:
            table_scores: dict[str, int] = {}
            for d in dimensions:
                t = col_meta.get(d, ("", ""))[1]
                if t:
                    table_scores[t] = table_scores.get(t, 0) + 1
            if table_scores:
                best_table = max(table_scores, key=table_scores.get)
                dimensions = [d for d in dimensions if col_meta.get(d, ("", ""))[1] == best_table]
        elif matched_tables:
            best_table = next(iter(matched_tables))
            dimensions = [d for d in dimensions if col_meta.get(d, ("", ""))[1] == best_table]

        return dimensions

    @staticmethod
    def _extract_cn_words(text: str) -> list[str]:
        """从文本中提取中文词片段（2-4 字符序列）。"""
        words = []
        cn_chars = [c for c in text if "一" <= c <= "鿿"]
        for size in (2, 3, 4):
            for i in range(len(cn_chars) - size + 1):
                words.append("".join(cn_chars[i : i + size]))
        return words
