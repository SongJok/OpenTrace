"""从版本化证据构造可审计的企业问数逻辑计划。"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from data_agent.contracts import (
    DimensionSpec,
    EvidenceBundle,
    EvidenceItem,
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


def _contains_term(question: str, *values: Any) -> bool:
    lowered = question.lower()
    for value in values:
        if isinstance(value, list):
            if _contains_term(question, *value):
                return True
            continue
        term = str(value or "").strip().lower()
        if term and term in lowered:
            return True
    return False


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


class LogicalPlanner:
    """先解析业务场景和粒度，再解析指标、实体、时间、关系与过滤条件。"""

    _metric_terms = re.compile(
        r"收入|流水|销售|金额|数量|人数|用户数|订单数|占比|率|均值|平均|总计|gmv|revenue|count|sum|avg",
        re.I,
    )

    def plan(self, request: QueryRequest, evidence: EvidenceBundle) -> LogicalQueryPlan:
        question = request.question
        tokens = _question_tokens(question)
        time_window = self._extract_time(request)
        metric_items = self._effective_metric_items(evidence, time_window, request)
        metrics, ambiguous_metrics = self._resolve_metrics(question, tokens, metric_items)
        metrics, rule_evidence_ids = self._apply_business_rules(
            metrics, question, tokens, evidence, time_window
        )

        dimensions = self._resolve_dimensions(question, tokens, evidence)
        required_tables = self._resolve_tables(request, tokens, evidence, metrics, dimensions)
        joins = self._resolve_joins(required_tables, evidence)
        metrics = self._fill_metric_time_fields(metrics, required_tables, evidence)
        filters = self._extract_filters(question, evidence)
        intent = self._intent(question, metrics, dimensions)
        comparison = self._comparison(question)
        if comparison:
            time_window = self._attach_baseline(time_window, comparison)

        missing: list[str] = []
        if not evidence.table_columns:
            missing.append("当前数据源没有可用 Schema 快照")
        if self._needs_metric(question) and not metrics:
            missing.append("未找到当前统计周期有效的已发布指标定义")
        if time_window and metrics and any(not metric.time_field for metric in metrics):
            missing.append("指标缺少唯一且已治理的统计时间字段")
        if len(required_tables) > 1 and not self._has_verified_join_path(required_tables, joins):
            missing.append("未找到覆盖所需表的已验证 JOIN 路径")

        authority_conflicts = list(evidence.authority_conflicts)
        clarification = self._clarification(
            missing=missing,
            ambiguous_metrics=ambiguous_metrics,
            authority_conflicts=authority_conflicts,
        )
        evidence_ids = [
            item.source_evidence_id
            for item in [*metrics, *dimensions, *joins]
            if item.source_evidence_id
        ]
        evidence_ids.extend(rule_evidence_ids)
        business_scenario = self._business_scenario(question, tokens, evidence)
        grain = [
            value
            for value in [
                *(dimension.name for dimension in dimensions),
                str(time_window.get("grain") or "") if time_window else "",
            ]
            if value
        ]

        confidence = 0.20
        confidence += 0.25 if evidence.table_columns else 0
        confidence += 0.25 if metrics or not self._needs_metric(question) else 0
        confidence += (
            0.15
            if len(required_tables) < 2 or self._has_verified_join_path(required_tables, joins)
            else 0
        )
        confidence += 0.08 if not time_window or all(metric.time_field for metric in metrics) else 0
        confidence += min(0.07, evidence.highest_authority * 0.07)
        confidence -= min(0.20, len(authority_conflicts) * 0.10)
        confidence = max(0.0, min(1.0, confidence))
        if not clarification and confidence < request.minimum_confidence:
            missing.append(
                f"证据置信度 {confidence:.2f} 低于请求阈值 {request.minimum_confidence:.2f}"
            )
            clarification = "当前证据不足以稳定确认口径，请补充指标、业务场景或统计粒度。"

        return LogicalQueryPlan(
            question=question,
            intent=intent,
            entities=required_tables,
            required_tables=required_tables,
            metrics=metrics,
            dimensions=dimensions,
            joins=joins,
            filters=filters,
            time_window=time_window,
            business_scenario=business_scenario,
            grain=grain,
            comparison=comparison,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            authority_conflicts=authority_conflicts,
            output_shape="scalar" if intent == "lookup" and not dimensions else "table",
            assumptions=[
                "只使用当前请求 Scope 内的数据源和已收集证据",
                "历史 SQL 只用于证明业务口径和结构模式，不复用固定日期或具体 ID",
                f"时间按 {request.timezone} 解析，并固化为绝对起止时间",
            ],
            missing_information=missing,
            needs_clarification=bool(clarification),
            clarification_question=clarification,
            confidence=confidence,
        )

    @staticmethod
    def _effective_metric_items(
        evidence: EvidenceBundle,
        time_window: dict[str, Any],
        request: QueryRequest,
    ) -> list[EvidenceItem]:
        reference = request.as_of or datetime.now(UTC)
        if time_window.get("start"):
            try:
                reference = datetime.fromisoformat(str(time_window["start"]))
            except ValueError:
                pass
        grouped: dict[str, list[EvidenceItem]] = {}
        for item in evidence.of_type(EvidenceType.METRIC):
            name = str(item.payload.get("name") or item.source_id).strip().lower()
            valid_from = item.valid_from
            valid_to = item.valid_to
            if valid_from is not None and valid_from.tzinfo is None:
                valid_from = valid_from.replace(tzinfo=UTC)
            if valid_to is not None and valid_to.tzinfo is None:
                valid_to = valid_to.replace(tzinfo=UTC)
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=UTC)
            if valid_from and reference < valid_from:
                continue
            if valid_to and reference >= valid_to:
                continue
            grouped.setdefault(name, []).append(item)
        selected: list[EvidenceItem] = []
        for items in grouped.values():
            items.sort(
                key=lambda item: (
                    int(item.payload.get("version") or item.version or 0),
                    item.authority.weight * item.confidence,
                ),
                reverse=True,
            )
            selected.append(items[0])
        return selected

    @staticmethod
    def _resolve_metrics(
        question: str,
        tokens: set[str],
        items: list[EvidenceItem],
    ) -> tuple[list[MetricSpec], list[str]]:
        ranked: list[tuple[int, bool, EvidenceItem]] = []
        for item in items:
            payload = item.payload
            score = _matches(
                tokens,
                payload.get("name"),
                payload.get("aliases"),
                payload.get("business_definition"),
                payload.get("business_domain"),
            )
            explicit = _contains_term(question, payload.get("name"), payload.get("aliases"))
            if score or explicit:
                ranked.append((score, explicit, item))
        ranked.sort(
            key=lambda value: (
                value[1],
                value[0],
                value[2].authority.weight * value[2].confidence,
            ),
            reverse=True,
        )
        explicit_items = [item for _, explicit, item in ranked if explicit]
        selected = explicit_items or ([ranked[0][2]] if ranked else [])
        ambiguous: list[str] = []
        if not explicit_items and len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            ambiguous = [str(value[2].payload.get("name") or "") for value in ranked[:6]]
            selected = []

        metrics: list[MetricSpec] = []
        seen: set[str] = set()
        for item in selected:
            payload = item.payload
            name = str(payload.get("name") or "")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            metrics.append(
                MetricSpec(
                    name=name,
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
                    time_field=payload.get("time_field"),
                    unit=payload.get("unit"),
                    owner=payload.get("owner"),
                    business_domain=payload.get("business_domain"),
                    version=int(payload.get("version") or item.version or 0) or None,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                    source_evidence_id=item.source_id,
                )
            )
        return metrics, ambiguous

    @staticmethod
    def _apply_business_rules(
        metrics: list[MetricSpec],
        question: str,
        tokens: set[str],
        evidence: EvidenceBundle,
        time_window: dict[str, Any],
    ) -> tuple[list[MetricSpec], list[str]]:
        if not metrics:
            return metrics, []
        updated = list(metrics)
        used_evidence: list[str] = []
        reference = datetime.now(UTC)
        if time_window.get("start"):
            reference = datetime.fromisoformat(str(time_window["start"]))
        for item in evidence.of_type(EvidenceType.BUSINESS_RULE):
            valid_from = item.valid_from
            valid_to = item.valid_to
            if valid_from is not None and valid_from.tzinfo is None:
                valid_from = valid_from.replace(tzinfo=UTC)
            if valid_to is not None and valid_to.tzinfo is None:
                valid_to = valid_to.replace(tzinfo=UTC)
            if (valid_from and reference < valid_from) or (valid_to and reference >= valid_to):
                continue
            payload = item.payload
            target_names = [
                str(value).lower()
                for value in (
                    payload.get("metrics")
                    or ([payload.get("metric")] if payload.get("metric") else [])
                )
                if str(value or "").strip()
            ]
            relevant = (
                _contains_term(
                    question,
                    payload.get("title"),
                    payload.get("aliases"),
                    payload.get("description"),
                )
                or _matches(tokens, payload) > 0
            )
            for index, metric in enumerate(updated):
                metric_names = {metric.name.lower(), *(alias.lower() for alias in metric.aliases)}
                targeted = not target_names or bool(metric_names.intersection(target_names))
                if not targeted or (not relevant and target_names):
                    continue
                required_filters = list(metric.required_filters)
                for value in payload.get("required_filters") or []:
                    normalized = str(value).strip()
                    if normalized and normalized not in required_filters:
                        required_filters.append(normalized)
                if required_filters != metric.required_filters:
                    updated[index] = metric.model_copy(
                        update={"required_filters": required_filters}
                    )
                    used_evidence.append(item.source_id)
        return updated, list(dict.fromkeys(used_evidence))

    @staticmethod
    def _resolve_dimensions(
        question: str,
        tokens: set[str],
        evidence: EvidenceBundle,
    ) -> list[DimensionSpec]:
        result: list[DimensionSpec] = []
        seen: set[str] = set()
        for item in evidence.of_type(EvidenceType.ENTITY) + evidence.of_type(
            EvidenceType.COLUMN_PROFILE
        ):
            payload = item.payload
            column = str(payload.get("column") or payload.get("column_name") or "").strip()
            if not column or not payload.get("is_dimension"):
                continue
            if not (
                _contains_term(
                    question, payload.get("business_name"), payload.get("aliases"), column
                )
                or _matches(tokens, payload.get("business_name"), payload.get("aliases"), column)
                >= 2
            ):
                continue
            table = str(payload.get("table") or payload.get("table_name") or "").strip()
            key = f"{table}.{column}".lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(
                DimensionSpec(
                    name=str(payload.get("business_name") or column),
                    column=column,
                    table=table or None,
                    hierarchy=[str(value) for value in payload.get("hierarchy") or []],
                    source_evidence_id=item.source_id,
                )
            )
        return result

    @staticmethod
    def _resolve_tables(
        request: QueryRequest,
        tokens: set[str],
        evidence: EvidenceBundle,
        metrics: list[MetricSpec],
        dimensions: list[DimensionSpec],
    ) -> list[str]:
        result = list(dict.fromkeys(request.requested_tables))
        for metric in metrics:
            for column in metric.underlying_columns:
                if "." in column:
                    table = column.rsplit(".", 1)[0]
                    if table not in result:
                        result.append(table)
            if metric.time_field and "." in metric.time_field:
                table = metric.time_field.rsplit(".", 1)[0]
                if table not in result:
                    result.append(table)
        for dimension in dimensions:
            if dimension.table and dimension.table not in result:
                result.append(dimension.table)

        ranked: list[tuple[int, str]] = []
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
                ranked.append((score, table))
        for _, table in sorted(ranked, key=lambda value: (-value[0], value[1]))[:6]:
            if table not in result:
                result.append(table)
        return result

    @staticmethod
    def _resolve_joins(required_tables: list[str], evidence: EvidenceBundle) -> list[JoinSpec]:
        result: list[JoinSpec] = []
        for item in evidence.of_type(EvidenceType.RELATIONSHIP):
            payload = item.payload
            left = str(payload.get("left_table") or payload.get("left") or "")
            right = str(payload.get("right_table") or payload.get("right") or "")
            if not left or not right:
                continue
            if required_tables and left not in required_tables and right not in required_tables:
                continue
            result.append(
                JoinSpec(
                    left_table=left,
                    left_column=str(payload.get("left_column") or payload.get("left_key") or ""),
                    right_table=right,
                    right_column=str(payload.get("right_column") or payload.get("right_key") or ""),
                    join_type=str(payload.get("join_type") or "LEFT").upper(),
                    cardinality=payload.get("cardinality"),
                    amplification_risk=payload.get("amplification_risk"),
                    verified=bool(payload.get("verified") or payload.get("is_verified")),
                    source_evidence_id=item.source_id,
                )
            )
        return result

    @staticmethod
    def _fill_metric_time_fields(
        metrics: list[MetricSpec],
        required_tables: list[str],
        evidence: EvidenceBundle,
    ) -> list[MetricSpec]:
        candidates: list[str] = []
        for item in evidence.of_type(EvidenceType.COLUMN_PROFILE):
            payload = item.payload
            table = str(payload.get("table") or payload.get("table_name") or "")
            column = str(payload.get("column") or payload.get("column_name") or "")
            if payload.get("is_time") and table in required_tables and column:
                candidates.append(f"{table}.{column}")
        unique = list(dict.fromkeys(candidates))
        if len(unique) != 1:
            return metrics
        return [
            metric if metric.time_field else metric.model_copy(update={"time_field": unique[0]})
            for metric in metrics
        ]

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
        if metrics:
            return "aggregation"
        if dimensions:
            return "lookup"
        return "lookup"

    @staticmethod
    def _comparison(question: str) -> str | None:
        if "同比" in question:
            return "year_over_year"
        if "环比" in question or "相比上月" in question or "和上月比较" in question:
            return "period_over_period"
        return None

    @classmethod
    def _extract_time(cls, request: QueryRequest) -> dict[str, Any]:
        zone = _timezone(request.timezone)
        anchor = request.as_of or datetime.now(UTC)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        local = anchor.astimezone(zone)
        question = request.question

        explicit = re.search(r"(20\d{2})[年\-/](\d{1,2})(?:月)?", question)
        if explicit:
            year, month = int(explicit.group(1)), int(explicit.group(2))
            start = datetime(year, month, 1, tzinfo=zone)
            end = cls._add_months(start, 1)
            return cls._window("calendar_month", explicit.group(0), start, end, "month")

        recent = re.search(r"最近\s*(\d+)\s*(天|日|周|月|年)", question)
        if recent:
            count = int(recent.group(1))
            unit = recent.group(2)
            end = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            if unit in {"天", "日"}:
                start = end - timedelta(days=count)
                grain = "day"
            elif unit == "周":
                start = end - timedelta(weeks=count)
                grain = "day"
            elif unit == "月":
                start = cls._add_months(end, -count)
                grain = "month"
            else:
                start = end.replace(year=end.year - count)
                grain = "month"
            return cls._window("relative", recent.group(0), start, end, grain)

        today = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if "昨天" in question or "昨日" in question:
            return cls._window("calendar_day", "昨日", today - timedelta(days=1), today, "day")
        if "今天" in question:
            return cls._window("calendar_day", "今天", today, today + timedelta(days=1), "day")
        if "上周" in question:
            current = today - timedelta(days=today.weekday())
            return cls._window("calendar_week", "上周", current - timedelta(days=7), current, "day")
        if "本周" in question:
            start = today - timedelta(days=today.weekday())
            return cls._window("calendar_week", "本周", start, start + timedelta(days=7), "day")
        if "上个月" in question or "上月" in question:
            end = today.replace(day=1)
            return cls._window("calendar_month", "上月", cls._add_months(end, -1), end, "day")
        if "本月" in question:
            start = today.replace(day=1)
            return cls._window("calendar_month", "本月", start, cls._add_months(start, 1), "day")
        if "去年" in question:
            start = datetime(today.year - 1, 1, 1, tzinfo=zone)
            return cls._window(
                "calendar_year", "去年", start, start.replace(year=start.year + 1), "month"
            )
        if "今年" in question:
            start = datetime(today.year, 1, 1, tzinfo=zone)
            return cls._window(
                "calendar_year", "今年", start, start.replace(year=start.year + 1), "month"
            )
        return {}

    @staticmethod
    def _window(
        kind: str,
        label: str,
        start: datetime,
        end: datetime,
        grain: str,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "label": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "grain": grain,
            "timezone": str(start.tzinfo),
        }

    @staticmethod
    def _add_months(value: datetime, months: int) -> datetime:
        total = value.year * 12 + (value.month - 1) + months
        year, month_index = divmod(total, 12)
        day = min(value.day, calendar.monthrange(year, month_index + 1)[1])
        return value.replace(year=year, month=month_index + 1, day=day)

    @classmethod
    def _attach_baseline(cls, window: dict[str, Any], comparison: str) -> dict[str, Any]:
        if not window.get("start") or not window.get("end"):
            return window
        start = datetime.fromisoformat(str(window["start"]))
        end = datetime.fromisoformat(str(window["end"]))
        if comparison == "year_over_year":
            baseline_start = cls._add_months(start, -12)
            baseline_end = cls._add_months(end, -12)
        else:
            duration = end - start
            baseline_start = start - duration
            baseline_end = start
        return {
            **window,
            "baseline_start": baseline_start.isoformat(),
            "baseline_end": baseline_end.isoformat(),
        }

    @staticmethod
    def _extract_filters(question: str, evidence: EvidenceBundle) -> list[FilterSpec]:
        aliases: dict[str, str] = {}
        for item in evidence.of_type(EvidenceType.COLUMN_PROFILE):
            payload = item.payload
            table = str(payload.get("table") or payload.get("table_name") or "")
            column = str(payload.get("column") or payload.get("column_name") or "")
            if not table or not column:
                continue
            physical = f"{table}.{column}"
            for value in [column, payload.get("business_name"), *(payload.get("aliases") or [])]:
                if str(value or "").strip():
                    aliases[str(value).strip().lower()] = physical
        result: list[FilterSpec] = []
        pattern = r"([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,})\s*(=|!=|>=|<=|>|<|是|为)\s*([\w\-\u4e00-\u9fff]+)"
        operator_map = {"是": "=", "为": "="}
        for match in re.finditer(pattern, question):
            field = aliases.get(match.group(1).lower(), match.group(1))
            result.append(
                FilterSpec(
                    field=field,
                    operator=operator_map.get(match.group(2), match.group(2)),
                    value=match.group(3),
                    source="user",
                )
            )
        return result

    @staticmethod
    def _has_verified_join_path(tables: list[str], joins: list[JoinSpec]) -> bool:
        if len(tables) <= 1:
            return True
        adjacency: dict[str, set[str]] = {}
        for join in joins:
            if not join.verified:
                continue
            adjacency.setdefault(join.left_table, set()).add(join.right_table)
            adjacency.setdefault(join.right_table, set()).add(join.left_table)
        visited = {tables[0]}
        queue = [tables[0]]
        while queue:
            current = queue.pop(0)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return set(tables).issubset(visited)

    @staticmethod
    def _clarification(
        *,
        missing: list[str],
        ambiguous_metrics: list[str],
        authority_conflicts: list[dict[str, Any]],
    ) -> str | None:
        if "当前数据源没有可用 Schema 快照" in missing:
            return "当前数据源尚未完成 Schema 同步，请先同步后再生成 SQL。"
        if authority_conflicts:
            names = [
                str(item.get("key") or item.get("name") or "业务口径")
                for item in authority_conflicts
            ]
            return "发现相互冲突的有效业务证据，请先由 Owner 确认口径：" + "、".join(names[:6])
        if ambiguous_metrics:
            return "问题可能对应多个指标，请明确选择：" + "、".join(ambiguous_metrics)
        if "未找到当前统计周期有效的已发布指标定义" in missing:
            return "请补充指标口径，或先发布该指标的公式、时间字段、粒度和固有过滤条件。"
        if "指标缺少唯一且已治理的统计时间字段" in missing:
            return "请明确统计使用哪个业务时间字段，例如支付时间、创建时间或完成时间。"
        if "未找到覆盖所需表的已验证 JOIN 路径" in missing:
            return "当前问题需要多表关联，但缺少已验证关系，请先确认 JOIN 键和基数。"
        return None

    @staticmethod
    def _business_scenario(
        question: str,
        tokens: set[str],
        evidence: EvidenceBundle,
    ) -> str:
        ranked: list[tuple[int, str]] = []
        for item in evidence.of_type(EvidenceType.BUSINESS_PROCESS) + evidence.of_type(
            EvidenceType.BUSINESS_RULE
        ):
            payload = item.payload
            score = _matches(tokens, payload.get("title"), payload.get("description"), payload)
            if score:
                ranked.append(
                    (
                        score,
                        str(payload.get("business_domain") or payload.get("title") or "general"),
                    )
                )
        return (
            sorted(ranked, key=lambda value: (-value[0], value[1]))[0][1] if ranked else "general"
        )
