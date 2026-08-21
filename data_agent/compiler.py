"""SQL 编译、静态验证与候选排序。"""

from __future__ import annotations

from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from data_agent.contracts import (
    CandidateSQL,
    EvidenceBundle,
    EvidenceType,
    LogicalQueryPlan,
    QueryRequest,
    ValidationIssue,
    ValidationReport,
)
from data_agent.learning import plan_pattern_key, sql_structure_hash


class SQLCompilationError(ValueError):
    """没有候选 SQL 通过编译闸门。"""


def _dialect_name(value: str) -> str:
    normalized = str(value or "").lower()
    if normalized in {"postgresql", "postgres", "pg"}:
        return "postgres"
    if normalized in {"clickhouse", "doris", "mysql"}:
        return normalized
    return "mysql"


class SQLGuard:
    """独立于数据库驱动的 SQL AST 安全和语义覆盖校验器。"""

    def validate(
        self,
        sql: str,
        *,
        request: QueryRequest,
        plan: LogicalQueryPlan,
        evidence: EvidenceBundle,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        value = str(sql or "").strip()
        if not value:
            return ValidationReport(
                status="fail", issues=[ValidationIssue(code="empty_sql", message="SQL 为空")]
            )
        if self._contains_comment(value):
            issues.append(ValidationIssue(code="comment", message="SQL 不允许包含注释"))
        try:
            expression = parse_one(value, read=_dialect_name(evidence.dialect))
        except ParseError as exc:
            return ValidationReport(
                status="fail",
                issues=[ValidationIssue(code="syntax", message=f"SQL 解析失败：{exc}")],
            )
        if not isinstance(expression, exp.Query):
            issues.append(ValidationIssue(code="read_only", message="只允许 SELECT 或 WITH 查询"))
        if expression.args.get("into") or expression.args.get("locks"):
            issues.append(ValidationIssue(code="side_effect", message="查询包含写入或锁定行为"))
        forbidden = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Create,
            exp.Drop,
            exp.Alter,
            exp.Command,
        )
        if isinstance(expression, forbidden) or any(
            isinstance(node, forbidden) for node in expression.walk()
        ):
            issues.append(ValidationIssue(code="write_statement", message="禁止执行写操作或 DDL"))

        tables = self._tables(expression)
        columns = self._columns(expression)
        if not isinstance(expression, exp.Query):
            return ValidationReport(
                status="fail",
                issues=issues,
                normalized_sql=value,
                referenced_tables=tables,
                referenced_columns=columns,
            )
        issues.extend(self._validate_tables(tables, evidence, plan))
        issues.extend(self._validate_columns(columns, expression, evidence))
        issues.extend(self._validate_metrics(expression, plan))
        issues.extend(self._validate_joins(expression, evidence))
        issues.extend(self._validate_time(expression, plan))
        issues.extend(self._validate_aggregation(expression, plan))
        if any(
            isinstance(projection, exp.Star)
            or (isinstance(projection, exp.Column) and projection.name == "*")
            for select in expression.find_all(exp.Select)
            for projection in select.expressions
        ):
            issues.append(
                ValidationIssue(
                    code="select_star",
                    message="SELECT * 会使字段治理和结果完整性不可审计",
                    severity="warning",
                )
            )
        limit_node = expression.args.get("limit")
        if limit_node is None:
            expression = expression.limit(request.max_rows)
            issues.append(
                ValidationIssue(
                    code="limit_added",
                    message=f"已自动添加 LIMIT {request.max_rows}",
                    severity="info",
                )
            )
        else:
            literal = getattr(limit_node.args.get("expression"), "name", "")
            try:
                requested = int(literal)
            except (TypeError, ValueError):
                requested = request.max_rows + 1
            if requested > request.max_rows:
                expression = expression.limit(request.max_rows)
                issues.append(
                    ValidationIssue(
                        code="limit_clamped",
                        message=f"LIMIT 已限制为 {request.max_rows}",
                        severity="warning",
                    )
                )
        if plan.intent in {"trend", "ranking"} and not expression.args.get("order"):
            issues.append(
                ValidationIssue(
                    code="non_deterministic_order",
                    message="趋势或排名查询缺少 ORDER BY，结果顺序不确定",
                    severity="warning",
                )
            )
        if request.mode.value == "execute_and_answer" and any(
            item.sensitive for item in evidence.items
        ):
            issues.append(
                ValidationIssue(
                    code="sensitive_context",
                    message="证据包包含敏感字段，执行需要额外确认和脱敏策略",
                    severity="warning",
                )
            )
        errors = [issue for issue in issues if issue.severity == "error"]
        status = "fail" if errors else ("warn" if issues else "pass")
        return ValidationReport(
            status=status,
            issues=issues,
            normalized_sql=expression.sql(dialect=_dialect_name(evidence.dialect)),
            referenced_tables=tables,
            referenced_columns=columns,
            completeness={
                "max_rows": request.max_rows,
                "total_rows_known": False,
                "truncation_must_be_reported": True,
            },
        )

    @staticmethod
    def _tables(expression: Any) -> list[str]:
        result: list[str] = []
        ctes = {str(node.alias_or_name).lower() for node in expression.find_all(exp.CTE)}
        for node in expression.find_all(exp.Table):
            database = str(node.db or "").strip()
            name = str(node.name or "").strip()
            full = f"{database}.{name}" if database else name
            if (
                name
                and name.lower() not in ctes
                and full.lower() not in {item.lower() for item in result}
            ):
                result.append(full)
        return result

    @staticmethod
    def _columns(expression: Any) -> list[str]:
        result: list[str] = []
        for node in expression.find_all(exp.Column):
            name = str(node.name or "").strip()
            table = str(node.table or "").strip()
            value = f"{table}.{name}" if table else name
            if value and value.lower() not in {item.lower() for item in result}:
                result.append(value)
        return result

    def _validate_tables(
        self, tables: list[str], evidence: EvidenceBundle, plan: LogicalQueryPlan
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        known = {str(name).lower() for name in evidence.table_columns}
        bare: dict[str, set[str]] = {}
        for name in known:
            bare.setdefault(name.rsplit(".", 1)[-1], set()).add(name)
        for table in tables:
            lowered = table.lower()
            if lowered in known:
                continue
            if "." not in lowered and len(bare.get(lowered, set())) == 1:
                continue
            issues.append(
                ValidationIssue(
                    code="table_scope", message=f"表不在当前数据源 Schema 范围内：{table}"
                )
            )
        if plan.required_tables:
            used = {item.rsplit(".", 1)[-1].lower() for item in tables}
            for required in plan.required_tables:
                if required.rsplit(".", 1)[-1].lower() not in used:
                    issues.append(
                        ValidationIssue(
                            code="plan_table_missing", message=f"SQL 未覆盖计划中的表：{required}"
                        )
                    )
        return issues

    def _validate_columns(
        self, columns: list[str], expression: Any, evidence: EvidenceBundle
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        known = {
            str(table).lower(): {str(column).lower() for column in values}
            for table, values in evidence.table_columns.items()
        }
        sensitive: set[tuple[str, str]] = set()
        for item in evidence.of_type(EvidenceType.SCHEMA) + evidence.of_type(
            EvidenceType.COLUMN_PROFILE
        ):
            if item.sensitive or item.payload.get("sensitive") or item.payload.get("is_sensitive"):
                table = str(
                    item.payload.get("table") or item.payload.get("table_name") or ""
                ).lower()
                column = str(
                    item.payload.get("column") or item.payload.get("column_name") or ""
                ).lower()
                if column:
                    sensitive.add((table, column))

        # alias、Schema 限定名和裸表名必须归一到同一个目录键，否则
        # public.users.email 可能在 SQL 使用 u.email 时绕过敏感字段门禁。
        query_tables: list[dict[str, Any]] = []
        for table_node in expression.find_all(exp.Table):
            table_name = str(table_node.name or "").lower()
            database = str(table_node.db or "").lower()
            qualified = f"{database}.{table_name}" if database else table_name
            matching_keys = [
                key for key in known if key == qualified or key.rsplit(".", 1)[-1] == table_name
            ]
            actual = (
                qualified
                if qualified in known
                else (matching_keys[0] if len(matching_keys) == 1 else qualified)
            )
            table_columns = known.get(actual)
            if table_columns:
                query_tables.append(
                    {
                        "alias": str(table_node.alias_or_name).lower(),
                        "actual": actual,
                        "bare": table_name,
                        "columns": table_columns,
                    }
                )

        def sensitive_columns(table: dict[str, Any]) -> set[str]:
            identities = {str(table["actual"]), str(table["bare"]), ""}
            return {
                column
                for sensitive_table, column in sensitive
                if sensitive_table in identities
                or sensitive_table.rsplit(".", 1)[-1] == str(table["bare"])
            }

        def table_for_qualifier(qualifier: str) -> dict[str, Any] | None:
            normalized = qualifier.lower()
            return next(
                (
                    table
                    for table in query_tables
                    if normalized in {str(table["alias"]), str(table["actual"]), str(table["bare"])}
                ),
                None,
            )

        for value in columns:
            if value == "*" or value.endswith(".*"):
                continue
            if "." not in value:
                column_name = value.lower()
                if query_tables and not any(
                    column_name in table["columns"] for table in query_tables
                ):
                    issues.append(
                        ValidationIssue(
                            code="column_scope", message=f"字段不在当前 Schema：{value}"
                        )
                    )
                if any(
                    column_name in table["columns"] and column_name in sensitive_columns(table)
                    for table in query_tables
                ):
                    issues.append(
                        ValidationIssue(
                            code="sensitive_column",
                            message=f"SQL 引用了敏感字段：{value}",
                            severity="warning",
                        )
                    )
                continue
            table_qualifier, column = value.split(".", 1)
            resolved = table_for_qualifier(table_qualifier)
            matches = set(resolved["columns"]) if resolved is not None else set()
            if matches and column.lower() not in matches:
                issues.append(
                    ValidationIssue(code="column_scope", message=f"字段不在当前 Schema：{value}")
                )
            if resolved is not None and column.lower() in sensitive_columns(resolved):
                issues.append(
                    ValidationIssue(
                        code="sensitive_column",
                        message=f"SQL 引用了敏感字段：{value}",
                        severity="warning",
                    )
                )

        # SELECT * 与 alias.* 会真实读取对应表的全部字段；COUNT(*) 不会。
        # 只对投影星号做敏感字段展开，避免把聚合计数误判为数据泄露。
        for select in expression.find_all(exp.Select):
            for projection in select.expressions:
                if isinstance(projection, exp.Star):
                    selected_tables = query_tables
                elif isinstance(projection, exp.Column) and projection.name == "*":
                    resolved = table_for_qualifier(str(projection.table or ""))
                    selected_tables = [resolved] if resolved is not None else []
                else:
                    continue
                for query_table in selected_tables:
                    selected_sensitive = sorted(sensitive_columns(query_table))
                    if not selected_sensitive:
                        continue
                    preview = "、".join(selected_sensitive[:5])
                    suffix = " 等" if len(selected_sensitive) > 5 else ""
                    issues.append(
                        ValidationIssue(
                            code="sensitive_column",
                            message=(
                                f"SELECT * 会读取表 {query_table['actual']} 的敏感字段："
                                f"{preview}{suffix}"
                            ),
                            severity="warning",
                        )
                    )
        return issues

    @staticmethod
    def _validate_metrics(expression: Any, plan: LogicalQueryPlan) -> list[ValidationIssue]:
        lowered = expression.sql().lower()
        issues: list[ValidationIssue] = []
        for metric in plan.metrics:
            for column in metric.underlying_columns:
                if column and column.lower() not in lowered:
                    issues.append(
                        ValidationIssue(
                            code="metric_column_missing",
                            message=f"指标 {metric.name} 缺少底层字段：{column}",
                            evidence_id=metric.source_evidence_id,
                        )
                    )
            for required_filter in metric.required_filters:
                if required_filter and required_filter.lower() not in lowered:
                    issues.append(
                        ValidationIssue(
                            code="metric_filter_missing",
                            message=f"指标 {metric.name} 缺少固有过滤条件：{required_filter}",
                            evidence_id=metric.source_evidence_id,
                        )
                    )
        return issues

    @staticmethod
    def _validate_joins(expression: Any, evidence: EvidenceBundle) -> list[ValidationIssue]:
        relationships = evidence.payloads(EvidenceType.RELATIONSHIP)
        verified_pairs = {
            (
                str(item.get("left_table") or "").lower(),
                str(item.get("left_column") or "").lower(),
                str(item.get("right_table") or "").lower(),
                str(item.get("right_column") or "").lower(),
            )
            for item in relationships
            if item.get("verified") or item.get("is_verified")
        }
        aliases = {
            str(table.alias_or_name).lower(): str(table.name).lower()
            for table in expression.find_all(exp.Table)
        }
        issues: list[ValidationIssue] = []
        for join in expression.find_all(exp.Join):
            on = join.args.get("on")
            if on is None:
                issues.append(
                    ValidationIssue(code="join_without_on", message="JOIN 缺少显式 ON 条件")
                )
                continue
            pairs = list(on.find_all(exp.EQ))
            if not pairs:
                issues.append(
                    ValidationIssue(
                        code="join_non_equality",
                        message="JOIN 不是已验证的等值关系",
                        severity="warning",
                    )
                )
            for pair in pairs:
                left, right = pair.left, pair.right
                if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                    continue
                left_table = aliases.get(str(left.table).lower(), str(left.table).lower())
                right_table = aliases.get(str(right.table).lower(), str(right.table).lower())
                key = (
                    left_table,
                    str(left.name).lower(),
                    right_table,
                    str(right.name).lower(),
                )
                reverse = (key[2], key[3], key[0], key[1])
                if key not in verified_pairs and reverse not in verified_pairs:
                    issues.append(
                        ValidationIssue(
                            code="unverified_join",
                            message=f"JOIN 关系未被数据目录验证：{left.sql()} = {right.sql()}",
                            severity="warning",
                        )
                    )
        return issues

    @staticmethod
    def _validate_time(expression: Any, plan: LogicalQueryPlan) -> list[ValidationIssue]:
        if not plan.time_window:
            return []
        lowered = expression.sql().lower()
        issues: list[ValidationIssue] = []
        time_fields = {str(metric.time_field or "").lower() for metric in plan.metrics}
        time_fields.discard("")
        if len(time_fields) != 1:
            issues.append(
                ValidationIssue(
                    code="time_field_unresolved",
                    message="逻辑计划没有唯一的治理时间字段",
                )
            )
            return issues
        time_field = next(iter(time_fields))
        if time_field not in lowered and time_field.rsplit(".", 1)[-1] not in lowered:
            issues.append(
                ValidationIssue(
                    code="time_field_missing",
                    message=f"SQL 未使用计划中的统计时间字段：{time_field}",
                )
            )
        for key in ("start", "end", "baseline_start", "baseline_end"):
            value = str(plan.time_window.get(key) or "")
            if value and value[:10] not in lowered:
                issues.append(
                    ValidationIssue(
                        code=f"time_{key}_missing",
                        message=f"SQL 未覆盖已解析的绝对时间边界 {key}={value}",
                    )
                )
        return issues

    @staticmethod
    def _validate_aggregation(expression: Any, plan: LogicalQueryPlan) -> list[ValidationIssue]:
        lowered = expression.sql().lower()
        issues: list[ValidationIssue] = []
        for metric in plan.metrics:
            aggregation = str(metric.aggregation or "").strip().lower()
            formula = str(metric.formula or "").strip().lower()
            expected = aggregation or next(
                (name for name in ("count", "sum", "avg", "min", "max") if f"{name}(" in formula),
                "",
            )
            if expected and f"{expected}(" not in lowered:
                issues.append(
                    ValidationIssue(
                        code="metric_aggregation_mismatch",
                        message=f"指标 {metric.name} 应使用聚合 {expected.upper()}",
                        evidence_id=metric.source_evidence_id,
                    )
                )
            if "count(distinct" in formula.replace(
                " ", ""
            ) and "count(distinct" not in lowered.replace(" ", ""):
                issues.append(
                    ValidationIssue(
                        code="metric_distinct_missing",
                        message=f"指标 {metric.name} 必须使用 COUNT(DISTINCT ...)",
                        evidence_id=metric.source_evidence_id,
                    )
                )
        if plan.dimensions and plan.metrics and expression.args.get("group") is None:
            issues.append(
                ValidationIssue(
                    code="group_by_missing",
                    message="查询包含维度和指标，但 SQL 缺少 GROUP BY",
                )
            )
        return issues

    @staticmethod
    def _contains_comment(value: str) -> bool:
        quote: str | None = None
        index = 0
        while index < len(value):
            char = value[index]
            nxt = value[index + 1] if index + 1 < len(value) else ""
            if quote:
                if char == quote:
                    if nxt == quote:
                        index += 2
                        continue
                    quote = None
                elif char == "\\":
                    index += 2
                    continue
            elif char in {"'", '"', "`"}:
                quote = char
            elif (char == "-" and nxt == "-") or (char == "/" and nxt == "*"):
                return True
            index += 1
        return False


class CandidateRanker:
    def rank(
        self,
        candidates: list[CandidateSQL],
        plan: LogicalQueryPlan,
        evidence: EvidenceBundle | None = None,
    ) -> list[CandidateSQL]:
        memory_support: dict[str, tuple[float, list[str]]] = {}
        failure_penalties: dict[str, tuple[float, list[str]]] = {}
        if evidence is not None:
            pattern_key = plan_pattern_key(plan)
            for item in evidence.of_type(EvidenceType.EXECUTION_MEMORY):
                payload = item.payload
                if payload.get("status") != "trusted":
                    continue
                if payload.get("pattern_key") != pattern_key:
                    continue
                structure = str(payload.get("sql_structure_hash") or "")
                if not structure:
                    continue
                bonus = 2.0
                current_bonus, ids = memory_support.get(structure, (0.0, []))
                memory_support[structure] = (
                    max(current_bonus, bonus),
                    [*ids, item.source_id],
                )
            for item in evidence.of_type(EvidenceType.FAILURE_MEMORY):
                payload = item.payload
                if payload.get("status") != "open" or payload.get("pattern_key") != pattern_key:
                    continue
                structure = str(payload.get("sql_structure_hash") or "")
                if not structure:
                    continue
                failure_count = max(1, int(payload.get("failure_count") or 1))
                penalty = min(8.0, 2.5 + failure_count * 1.25)
                current_penalty, ids = failure_penalties.get(structure, (0.0, []))
                failure_penalties[structure] = (
                    max(current_penalty, penalty),
                    [*ids, item.source_id],
                )
        for candidate in candidates:
            report = candidate.validation
            error_penalty = len(report.errors) * 10
            warning_penalty = len(report.issues) * 0.25
            source_bonus = {
                "semantic_compiler": 1.5,
                "user_supplied": 0.5,
                "model": 0.0,
            }.get(candidate.source, 0.0)
            memory_bonus = 0.0
            failure_penalty = 0.0
            if evidence is not None:
                structure = sql_structure_hash(candidate.sql, dialect=evidence.dialect)
                memory_bonus, memory_ids = memory_support.get(structure, (0.0, []))
                failure_penalty, failure_ids = failure_penalties.get(structure, (0.0, []))
                candidate.supporting_memory_ids = list(dict.fromkeys([*memory_ids, *failure_ids]))
                if failure_ids:
                    failure_assumption = "相同 SQL 结构存在未处置失败模式，已降低候选优先级"
                    if failure_assumption not in candidate.assumptions:
                        candidate.assumptions.append(failure_assumption)
            candidate.score = max(
                0.0,
                (
                    plan.confidence * 10
                    + source_bonus
                    + memory_bonus
                    - error_penalty
                    - warning_penalty
                    - failure_penalty
                ),
            )
        ranked = sorted(candidates, key=lambda item: (-item.score, item.id))
        for index, candidate in enumerate(ranked, start=1):
            candidate.rank = index
        return ranked
