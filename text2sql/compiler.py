"""SQL 编译、静态验证与候选排序。"""

from __future__ import annotations

from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from text2sql.contracts import (
    CandidateSQL,
    EvidenceBundle,
    EvidenceType,
    LogicalQueryPlan,
    QueryRequest,
    ValidationIssue,
    ValidationReport,
)


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
        if expression.find(exp.Star):
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
        aliases = {
            str(table.alias_or_name).lower(): str(table.name).lower()
            for table in expression.find_all(exp.Table)
        }
        sensitive: set[str] = set()
        for item in evidence.of_type(EvidenceType.SCHEMA) + evidence.of_type(
            EvidenceType.COLUMN_PROFILE
        ):
            if item.payload.get("sensitive") or item.payload.get("is_sensitive"):
                table = str(
                    item.payload.get("table") or item.payload.get("table_name") or ""
                ).lower()
                column = str(
                    item.payload.get("column") or item.payload.get("column_name") or ""
                ).lower()
                sensitive.add(f"{table}.{column}")
        query_tables: list[tuple[str, str, set[str]]] = []
        for table_node in expression.find_all(exp.Table):
            table_name = str(table_node.name or "").lower()
            actual = aliases.get(str(table_node.alias_or_name).lower(), table_name)
            table_columns = known.get(actual) or known.get(
                next((key for key in known if key.rsplit(".", 1)[-1] == actual), ""),
            )
            if table_columns:
                query_tables.append((str(table_node.alias_or_name).lower(), actual, table_columns))
        for value in columns:
            if "." not in value:
                column_name = value.lower()
                if query_tables and not any(column_name in values for _, _, values in query_tables):
                    issues.append(
                        ValidationIssue(
                            code="column_scope", message=f"字段不在当前 Schema：{value}"
                        )
                    )
                matching_sensitive = {
                    f"{actual}.{column_name}"
                    for _, actual, values in query_tables
                    if column_name in values
                }
                if matching_sensitive & sensitive:
                    issues.append(
                        ValidationIssue(
                            code="sensitive_column",
                            message=f"SQL 引用了敏感字段：{value}",
                            severity="warning",
                        )
                    )
                continue
            table, column = value.split(".", 1)
            actual = aliases.get(table.lower(), table.lower())
            matches = known.get(actual) or known.get(
                next((key for key in known if key.rsplit(".", 1)[-1] == actual), ""), set()
            )
            if matches and column.lower() not in matches:
                issues.append(
                    ValidationIssue(code="column_scope", message=f"字段不在当前 Schema：{value}")
                )
            if (
                f"{actual}.{column.lower()}" in sensitive
                or f"{table.lower()}.{column.lower()}" in sensitive
            ):
                issues.append(
                    ValidationIssue(
                        code="sensitive_column",
                        message=f"SQL 引用了敏感字段：{value}",
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
    def rank(self, candidates: list[CandidateSQL], plan: LogicalQueryPlan) -> list[CandidateSQL]:
        for candidate in candidates:
            report = candidate.validation
            error_penalty = len(report.errors) * 10
            warning_penalty = len(report.issues) * 0.25
            candidate.score = max(0.0, plan.confidence * 10 - error_penalty - warning_penalty)
        ranked = sorted(candidates, key=lambda item: (-item.score, item.id))
        for index, candidate in enumerate(ranked, start=1):
            candidate.rank = index
        return ranked
