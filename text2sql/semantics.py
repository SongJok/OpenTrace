"""从证据包构造可审计的逻辑查询计划。"""

from __future__ import annotations

import re
from typing import Any

from text2sql.contracts import (
    DimensionSpec,
    EvidenceBundle,
    EvidenceType,
    FilterSpec,
    JoinSpec,
    LogicalQueryPlan,
    MetricSpec,
    QueryRequest,
)


def _question_tokens(question: str) -> set[str]:
    tokens = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        tokens.add(segment)
        tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return {item for item in tokens if item}


def _matches(question_tokens: set[str], *values: Any) -> int:
    text = " ".join(str(value or "") for value in values).lower()
    return sum(1 for token in question_tokens if token and token in text)


class LogicalPlanner:
    """把自然语言映射到实体、指标、维度、关系和时间约束。"""

    _metric_terms = re.compile(
        r"收入|销售|金额|数量|人数|占比|率|均值|平均|总计|gmv|revenue|count|sum|avg", re.I
    )

    def plan(self, request: QueryRequest, evidence: EvidenceBundle) -> LogicalQueryPlan:
        question = request.question
        tokens = _question_tokens(question)
        metrics: list[MetricSpec] = []
        for item in evidence.of_type(EvidenceType.METRIC):
            payload = item.payload
            if _matches(
                tokens,
                payload.get("name"),
                payload.get("aliases"),
                payload.get("business_definition"),
            ):
                metrics.append(
                    MetricSpec(
                        name=str(payload.get("name") or ""),
                        aliases=[str(value) for value in payload.get("aliases") or []],
                        formula=str(payload.get("formula") or ""),
                        aggregation=payload.get("aggregation") or payload.get("agg_function"),
                        underlying_columns=[
                            str(value) for value in payload.get("underlying_columns") or []
                        ],
                        required_filters=[
                            str(value) for value in payload.get("required_filters") or []
                        ],
                        grain=payload.get("grain"),
                        unit=payload.get("unit"),
                        source_evidence_id=item.id,
                    )
                )

        table_scores: dict[str, int] = {}
        for item in evidence.of_type(EvidenceType.SCHEMA) + evidence.of_type(EvidenceType.ENTITY):
            payload = item.payload
            table = str(payload.get("table") or payload.get("table_name") or "").strip()
            if not table:
                continue
            score = _matches(
                tokens,
                table,
                payload.get("business_name"),
                payload.get("aliases"),
                payload.get("description"),
            )
            if score:
                table_scores[table] = max(score, table_scores.get(table, 0))

        required_tables = list(request.requested_tables)
        required_tables.extend(
            table
            for table, _ in sorted(table_scores.items(), key=lambda value: (-value[1], value[0]))
        )
        for metric in metrics:
            for column in metric.underlying_columns:
                table = column.rsplit(".", 1)[0] if "." in column else ""
                if table:
                    required_tables.append(table)
        required_tables = list(dict.fromkeys(required_tables))

        dimensions: list[DimensionSpec] = []
        for item in evidence.of_type(EvidenceType.ENTITY) + evidence.of_type(EvidenceType.SCHEMA):
            payload = item.payload
            column = str(payload.get("column") or payload.get("column_name") or "").strip()
            if not column or not payload.get("is_dimension"):
                continue
            if _matches(tokens, payload.get("business_name"), payload.get("aliases"), column):
                dimensions.append(
                    DimensionSpec(
                        name=str(payload.get("business_name") or column),
                        column=column,
                        table=str(payload.get("table") or payload.get("table_name") or "") or None,
                        source_evidence_id=item.id,
                    )
                )

        joins: list[JoinSpec] = []
        for item in evidence.of_type(EvidenceType.RELATIONSHIP):
            payload = item.payload
            left = str(payload.get("left_table") or payload.get("left") or "")
            right = str(payload.get("right_table") or payload.get("right") or "")
            if not left or not right:
                continue
            if not required_tables or left in required_tables or right in required_tables:
                joins.append(
                    JoinSpec(
                        left_table=left,
                        left_column=str(
                            payload.get("left_column") or payload.get("left_key") or ""
                        ).strip(),
                        right_table=right,
                        right_column=str(
                            payload.get("right_column") or payload.get("right_key") or ""
                        ).strip(),
                        join_type=str(payload.get("join_type") or "LEFT").upper(),
                        cardinality=payload.get("cardinality"),
                        amplification_risk=payload.get("amplification_risk"),
                        verified=bool(payload.get("verified") or payload.get("is_verified")),
                        source_evidence_id=item.id,
                    )
                )

        intent = self._intent(question, metrics, dimensions)
        missing: list[str] = []
        if not evidence.table_columns:
            missing.append("当前数据源没有可用 Schema 快照")
        if self._needs_metric(question) and not metrics:
            missing.append("未找到已审批的指标定义")
        if len(required_tables) > 1 and not joins:
            missing.append("未找到已验证的多表关系")

        clarification: str | None = None
        if "当前数据源没有可用 Schema 快照" in missing:
            clarification = (
                "当前数据源尚未完成 Schema 同步，无法安全生成或执行 SQL。请先同步 Schema。"
            )
        elif len(metrics) > 1 and self._needs_metric(question):
            clarification = "问题匹配到多个指标，请明确要使用哪个指标：" + "、".join(
                item.name for item in metrics[:6]
            )
        elif "未找到已审批的指标定义" in missing:
            clarification = (
                "请补充指标口径，或先在指标目录中发布该指标的公式、时间字段和固有过滤条件。"
            )

        confidence = 0.25
        confidence += 0.25 if evidence.table_columns else 0
        confidence += 0.25 if metrics or not self._needs_metric(question) else 0
        confidence += 0.15 if joins or len(required_tables) < 2 else 0
        confidence += min(0.10, evidence.highest_authority * 0.10)
        return LogicalQueryPlan(
            question=question,
            intent=intent,
            entities=required_tables,
            required_tables=required_tables,
            metrics=metrics,
            dimensions=dimensions,
            joins=joins,
            filters=self._extract_filters(question),
            time_window=self._extract_time(question),
            output_shape="scalar" if intent == "lookup" and not dimensions else "table",
            assumptions=[
                "只使用当前请求 Scope 内的数据源和已收集证据",
                "历史 SQL 只作为参考，不直接执行",
            ],
            missing_information=missing,
            needs_clarification=bool(clarification),
            clarification_question=clarification,
            confidence=min(1.0, confidence),
        )

    @classmethod
    def _needs_metric(cls, question: str) -> bool:
        return bool(cls._metric_terms.search(question))

    @staticmethod
    def _intent(question: str, metrics: list[MetricSpec], dimensions: list[DimensionSpec]) -> str:
        if re.search(r"趋势|走势|同比|环比", question, re.I):
            return "trend"
        if re.search(r"漏斗|转化", question):
            return "funnel"
        if re.search(r"留存|cohort", question, re.I):
            return "cohort"
        if re.search(r"最高|最多|top|排名", question, re.I):
            return "ranking"
        if metrics and dimensions:
            return "aggregation"
        if metrics:
            return "aggregation"
        return "lookup"

    @staticmethod
    def _extract_time(question: str) -> dict[str, Any]:
        match = re.search(r"最近\s*(\d+)\s*(天|日|周|月|年)", question)
        if match:
            count = int(match.group(1))
            days = count * {"天": 1, "日": 1, "周": 7, "月": 30, "年": 365}[match.group(2)]
            return {"kind": "relative", "days": days, "label": match.group(0)}
        labels = {"今天": 1, "昨日": 1, "本周": 7, "本月": 30, "今年": 365, "去年": 365}
        for label, days in labels.items():
            if label in question:
                return {"kind": "calendar", "label": label, "days": days}
        return {}

    @staticmethod
    def _extract_filters(question: str) -> list[FilterSpec]:
        filters: list[FilterSpec] = []
        pattern = (
            r"([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,})\s*(?:=|是|为)\s*([\w\-\u4e00-\u9fff]+)"
        )
        for match in re.finditer(pattern, question):
            filters.append(FilterSpec(field=match.group(1), value=match.group(2)))
        return filters
