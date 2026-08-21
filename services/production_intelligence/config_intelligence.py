"""配置策略目录与确定性多层校验引擎。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, SchemaError
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.observability.metrics import CONFIG_VALIDATION_TOTAL
from infra.storage.models import (
    EnterpriseConnector,
    ProductionAsset,
    ProductionConfigPolicy,
    ProductionConfigSnapshot,
    ProductionConfigValidationRun,
    ResponseRecord,
)
from services.production_intelligence.asset_graph import ProductionScope
from services.production_intelligence.audit import append_audit, mask_sensitive

_POLICY_STATUSES = frozenset({"draft", "published", "retired"})
_SNAPSHOT_STATUSES = frozenset({"current", "historical", "candidate", "applied", "rejected"})
_RULE_SEVERITIES = frozenset({"error", "warning"})
_RULE_OPERATORS = frozenset(
    {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "regex", "exists"}
)
_CAPACITY_OPERATIONS = frozenset({"product", "sum", "min", "max"})


class ConfigIntelligenceError(ValueError):
    """配置策略、快照或校验输入不合法。"""


def policy_to_dict(row: ProductionConfigPolicy) -> dict[str, Any]:
    return {
        "id": row.id,
        "asset_id": row.asset_id,
        "version": row.version,
        "status": row.status,
        "schema": dict(row.schema or {}),
        "reference_rules": list(row.reference_rules or []),
        "business_rules": list(row.business_rules or []),
        "history_rules": list(row.history_rules or []),
        "capacity_rules": list(row.capacity_rules or []),
        "conflict_rules": list(row.conflict_rules or []),
        "dry_run_operation": row.dry_run_operation,
        "created_by": row.created_by,
        "published_by": row.published_by,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def snapshot_to_dict(
    row: ProductionConfigSnapshot, *, include_content: bool = False
) -> dict[str, Any]:
    result = {
        "id": row.id,
        "response_id": row.response_id,
        "asset_id": row.asset_id,
        "policy_id": row.policy_id,
        "environment": row.environment,
        "version_ref": row.version_ref,
        "source_ref": row.source_ref,
        "status": row.status,
        "content_hash": row.content_hash,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_content:
        result["content"] = mask_sensitive(dict(row.content or {}))
    return result


def validation_run_to_dict(row: ProductionConfigValidationRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "response_id": row.response_id,
        "asset_id": row.asset_id,
        "policy_id": row.policy_id,
        "snapshot_id": row.snapshot_id,
        "candidate_hash": row.candidate_hash,
        "status": row.status,
        "risk_level": row.risk_level,
        "checks": list(row.checks or []),
        "dry_run": mask_sensitive(dict(row.dry_run or {})),
        "summary": dict(row.summary or {}),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _bounded_json(value: Any, *, limit: int = 262_144) -> None:
    encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > limit:
        raise ConfigIntelligenceError("config_payload_too_large")
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 10_000:
            raise ConfigIntelligenceError("config_payload_structure_too_complex")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _validate_safe_regex(value: Any) -> str:
    pattern = str(value or "")
    if (
        not pattern
        or len(pattern) > 256
        or "(?" in pattern
        or re.search(r"\\[1-9]", pattern)
        or re.search(r"\([^)]*[*+]\)[*+{]", pattern)
    ):
        raise ConfigIntelligenceError("config_regex_unsafe")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigIntelligenceError("config_regex_invalid") from exc
    return pattern


def _validate_config_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ConfigIntelligenceError("config_policy_schema_invalid") from exc
    _bounded_json(schema)
    if schema.get("type") != "object":
        raise ConfigIntelligenceError("config_policy_root_object_required")
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        reference = node.get("$ref")
        if reference is not None and not str(reference).startswith("#/"):
            raise ConfigIntelligenceError("config_policy_external_reference_forbidden")
        if node.get("type") == "object":
            if node.get("additionalProperties") is not False:
                raise ConfigIntelligenceError("config_policy_closed_object_required")
            if not isinstance(node.get("properties"), dict):
                raise ConfigIntelligenceError("config_policy_properties_required")
            if node.get("patternProperties"):
                raise ConfigIntelligenceError("config_policy_pattern_properties_forbidden")
        if "pattern" in node:
            _validate_safe_regex(node["pattern"])
        stack.extend(node.values())


def _safe_source_ref(value: str) -> str:
    normalized = value.strip()
    lowered = normalized.lower()
    if (
        not normalized
        or len(normalized) > 2048
        or any(ord(char) < 32 for char in normalized)
        or any(marker in lowered for marker in ("token=", "password=", "secret=", "api_key="))
    ):
        raise ConfigIntelligenceError("config_snapshot_source_ref_invalid")
    parsed = urlsplit(normalized)
    if parsed.username or parsed.password:
        raise ConfigIntelligenceError("config_snapshot_source_ref_invalid")
    return normalized


def _path_parts(path: str) -> list[str]:
    normalized = str(path or "").strip()
    if not normalized or normalized == "/":
        return []
    if normalized.startswith("/"):
        return [part.replace("~1", "/").replace("~0", "~") for part in normalized[1:].split("/")]
    return [part for part in normalized.split(".") if part]


_MISSING = object()


def value_at(document: Any, path: str) -> Any:
    current = document
    for part in _path_parts(path):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        return _MISSING
    return current


def _validate_rule(rule: dict[str, Any], *, category: str) -> dict[str, Any]:
    normalized = dict(rule)
    rule_id = str(rule.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", rule_id):
        raise ConfigIntelligenceError("config_rule_id_required")
    normalized["id"] = rule_id
    normalized["path"] = str(rule.get("path") or "")[:512]
    if category != "conflict" and not normalized["path"]:
        raise ConfigIntelligenceError("config_rule_path_required")
    normalized["severity"] = str(rule.get("severity") or "error")
    if normalized["severity"] not in _RULE_SEVERITIES:
        raise ConfigIntelligenceError("config_rule_severity_invalid")
    if category in {"business", "capacity"}:
        operator = str(rule.get("operator") or "")
        if operator not in _RULE_OPERATORS:
            raise ConfigIntelligenceError("config_rule_operator_invalid")
        normalized["operator"] = operator
        if operator == "regex":
            normalized["value"] = _validate_safe_regex(rule.get("value"))
    if category == "reference":
        allowed_values = rule.get("allowed_values")
        catalog = rule.get("catalog")
        if not (
            (isinstance(allowed_values, list) and bool(allowed_values))
            or (isinstance(catalog, dict) and bool(catalog))
        ):
            raise ConfigIntelligenceError("config_reference_rule_values_required")
    if category == "history":
        thresholds = ("max_change_ratio", "max_multiplier", "min_multiplier")
        if not any(rule.get(name) is not None for name in thresholds):
            raise ConfigIntelligenceError("config_history_rule_threshold_required")
        try:
            percentile = float(rule.get("baseline_percentile", 50.0))
            min_samples = int(rule.get("min_samples", 5))
            threshold_values = [
                float(rule[name]) for name in thresholds if rule.get(name) is not None
            ]
        except (TypeError, ValueError) as exc:
            raise ConfigIntelligenceError("config_history_rule_invalid") from exc
        if (
            not 0.0 <= percentile <= 100.0
            or not 3 <= min_samples <= 100
            or any(not math.isfinite(value) or value < 0.0 for value in threshold_values)
        ):
            raise ConfigIntelligenceError("config_history_rule_invalid")
        normalized["baseline_percentile"] = percentile
        normalized["min_samples"] = min_samples
    if category == "capacity" and rule.get("estimate") is not None:
        estimate = rule.get("estimate")
        if not isinstance(estimate, dict):
            raise ConfigIntelligenceError("config_capacity_estimate_invalid")
        operation = str(estimate.get("operation") or "product")
        terms = estimate.get("terms")
        if operation not in _CAPACITY_OPERATIONS or not isinstance(terms, list) or not terms:
            raise ConfigIntelligenceError("config_capacity_estimate_invalid")
        if len(terms) > 20:
            raise ConfigIntelligenceError("config_capacity_estimate_too_many_terms")
        try:
            multiplier = float(estimate.get("multiplier", 1.0))
        except (TypeError, ValueError) as exc:
            raise ConfigIntelligenceError("config_capacity_estimate_invalid") from exc
        if not math.isfinite(multiplier):
            raise ConfigIntelligenceError("config_capacity_estimate_invalid")
        for term in terms:
            if not isinstance(term, dict) or ("path" in term) == ("value" in term):
                raise ConfigIntelligenceError("config_capacity_estimate_term_invalid")
            if "path" in term and not str(term.get("path") or ""):
                raise ConfigIntelligenceError("config_capacity_estimate_term_invalid")
            try:
                factor = float(term.get("factor", 1.0))
                if "value" in term:
                    value = float(term["value"])
                    if not math.isfinite(value):
                        raise ValueError
            except (TypeError, ValueError) as exc:
                raise ConfigIntelligenceError("config_capacity_estimate_term_invalid") from exc
            if not math.isfinite(factor):
                raise ConfigIntelligenceError("config_capacity_estimate_term_invalid")
    if category == "conflict":
        paths = rule.get("paths")
        if (
            not isinstance(paths, list)
            or not 2 <= len(paths) <= 100
            or any(not str(item or "").strip() for item in paths)
            or len({str(item) for item in paths}) != len(paths)
        ):
            raise ConfigIntelligenceError("config_conflict_rule_paths_required")
        try:
            max_present = int(rule.get("max_present", 1))
        except (TypeError, ValueError) as exc:
            raise ConfigIntelligenceError("config_conflict_rule_invalid") from exc
        if not 0 <= max_present < len(paths):
            raise ConfigIntelligenceError("config_conflict_rule_invalid")
        normalized["max_present"] = max_present
    return normalized


def _comparison(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return (actual is not _MISSING) is bool(expected)
    if actual is _MISSING:
        return False
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return actual in (expected if isinstance(expected, list) else [])
    if operator == "not_in":
        return actual not in (expected if isinstance(expected, list) else [])
    if operator == "regex":
        try:
            return bool(re.fullmatch(str(expected), str(actual)[:4096]))
        except re.error:
            return False
    if not isinstance(actual, int | float) or isinstance(actual, bool):
        return False
    if not isinstance(expected, int | float) or isinstance(expected, bool):
        return False
    return {
        "gt": actual > expected,
        "gte": actual >= expected,
        "lt": actual < expected,
        "lte": actual <= expected,
    }.get(operator, False)


def _percentile(values: list[float], percentile: float) -> float:
    """使用线性插值计算确定性分位值。"""

    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile_values_required")
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _history_statistics(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "latest": values[0],
        "min": min(values),
        "p05": _percentile(values, 5.0),
        "p25": _percentile(values, 25.0),
        "p50": _percentile(values, 50.0),
        "p75": _percentile(values, 75.0),
        "p95": _percentile(values, 95.0),
        "max": max(values),
    }


def _capacity_estimate(
    candidate: dict[str, Any], estimate: dict[str, Any]
) -> tuple[float | object, list[dict[str, Any]]]:
    resolved: list[dict[str, Any]] = []
    values: list[float] = []
    for term in estimate.get("terms") or []:
        path = str(term.get("path") or "")
        raw = value_at(candidate, path) if path else term.get("value", _MISSING)
        if not isinstance(raw, int | float) or isinstance(raw, bool):
            return _MISSING, resolved
        factor = float(term.get("factor", 1.0))
        value = float(raw) * factor
        if not math.isfinite(value):
            return _MISSING, resolved
        values.append(value)
        resolved.append({"path": path or None, "value": raw, "factor": factor})
    if not values:
        return _MISSING, resolved
    operation = str(estimate.get("operation") or "product")
    if operation == "product":
        result = math.prod(values)
    elif operation == "sum":
        result = sum(values)
    elif operation == "min":
        result = min(values)
    else:
        result = max(values)
    multiplier = float(estimate.get("multiplier", 1.0))
    result *= multiplier
    return (result if math.isfinite(result) else _MISSING), resolved


@dataclass(frozen=True, slots=True)
class ConfigCheck:
    check_id: str
    category: str
    status: str
    severity: str
    path: str = ""
    message: str = ""
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "category": self.category,
            "status": self.status,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "expected": mask_sensitive(self.expected),
            "actual": mask_sensitive(self.actual if self.actual is not _MISSING else None),
        }


@dataclass(frozen=True, slots=True)
class ConfigValidationReport:
    status: str
    risk_level: str
    checks: tuple[ConfigCheck, ...]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "risk_level": self.risk_level,
            "checks": [item.to_dict() for item in self.checks],
            "summary": dict(self.summary),
        }


class DeterministicConfigValidator:
    """不执行任意代码、不依赖模型的配置多层校验。"""

    @staticmethod
    def _check(
        *,
        rule: dict[str, Any],
        category: str,
        passed: bool,
        actual: Any,
        expected: Any,
        default_message: str,
    ) -> ConfigCheck:
        return ConfigCheck(
            check_id=str(rule.get("id") or category),
            category=category,
            status="pass" if passed else "fail",
            severity=str(rule.get("severity") or "error"),
            path=str(rule.get("path") or ""),
            message=str(rule.get("message") or default_message),
            expected=expected,
            actual=actual,
        )

    def validate(
        self,
        *,
        candidate: dict[str, Any],
        policy: ProductionConfigPolicy,
        history: list[dict[str, Any]] | None = None,
        dry_run: dict[str, Any] | None = None,
    ) -> ConfigValidationReport:
        checks: list[ConfigCheck] = []
        validator = Draft202012Validator(dict(policy.schema or {}))
        schema_errors = sorted(validator.iter_errors(candidate), key=lambda item: list(item.path))
        if not schema_errors:
            checks.append(
                ConfigCheck("schema", "schema", "pass", "error", message="Schema 校验通过")
            )
        else:
            for index, error in enumerate(schema_errors[:100], start=1):
                path = "/" + "/".join(str(item) for item in error.absolute_path)
                checks.append(
                    ConfigCheck(
                        f"schema-{index}",
                        "schema",
                        "fail",
                        "error",
                        path=path,
                        message=error.message,
                    )
                )

        for rule in policy.reference_rules or []:
            actual = value_at(candidate, str(rule.get("path") or ""))
            allowed = list(rule.get("allowed_values") or dict(rule.get("catalog") or {}).keys())
            checks.append(
                self._check(
                    rule=rule,
                    category="reference",
                    passed=actual in allowed,
                    actual=actual,
                    expected=allowed,
                    default_message="引用值必须来自已发布目录",
                )
            )

        for rule in policy.business_rules or []:
            actual = value_at(candidate, str(rule.get("path") or ""))
            expected = rule.get("value")
            checks.append(
                self._check(
                    rule=rule,
                    category="business_rule",
                    passed=_comparison(actual, str(rule.get("operator") or ""), expected),
                    actual=actual,
                    expected=expected,
                    default_message="业务规则不满足",
                )
            )

        history_rows = list(history or [])[:100]
        for rule in policy.history_rules or []:
            path = str(rule.get("path") or "")
            actual = value_at(candidate, path)
            historical_values = [
                float(value)
                for value in (value_at(item, path) for item in history_rows)
                if isinstance(value, int | float) and not isinstance(value, bool)
            ]
            min_samples = int(rule.get("min_samples", 5))
            percentile = float(rule.get("baseline_percentile", 50.0))
            statistics = _history_statistics(historical_values) if historical_values else {}
            baseline = (
                _percentile(historical_values, percentile)
                if len(historical_values) >= min_samples
                else _MISSING
            )
            max_change_ratio = rule.get("max_change_ratio")
            max_multiplier = rule.get("max_multiplier")
            min_multiplier = rule.get("min_multiplier")
            if (
                isinstance(actual, int | float)
                and not isinstance(actual, bool)
                and isinstance(baseline, int | float)
                and not isinstance(baseline, bool)
            ):
                denominator = max(abs(float(baseline)), 1e-9)
                change_ratio = abs(float(actual) - float(baseline)) / denominator
                multiplier = float(actual) / denominator
                passed = True
                if max_change_ratio is not None:
                    passed = passed and change_ratio <= float(max_change_ratio)
                if max_multiplier is not None:
                    passed = passed and multiplier <= float(max_multiplier)
                if min_multiplier is not None:
                    passed = passed and multiplier >= float(min_multiplier)
            else:
                change_ratio = None
                multiplier = None
                passed = False
            checks.append(
                self._check(
                    rule=rule,
                    category="history",
                    passed=passed,
                    actual={
                        "value": actual,
                        "change_ratio": change_ratio,
                        "multiplier": multiplier,
                    },
                    expected={
                        "baseline": baseline,
                        "baseline_percentile": percentile,
                        "max_change_ratio": max_change_ratio,
                        "max_multiplier": max_multiplier,
                        "min_multiplier": min_multiplier,
                        "statistics": statistics,
                    },
                    default_message="配置变更超过历史波动阈值",
                )
            )

        for rule in policy.capacity_rules or []:
            estimate = rule.get("estimate")
            if isinstance(estimate, dict):
                estimate_value, resolved_terms = _capacity_estimate(candidate, estimate)
                actual = estimate_value
                actual_projection = {
                    "estimate": estimate_value,
                    "operation": estimate.get("operation", "product"),
                    "terms": resolved_terms,
                }
            else:
                actual = value_at(candidate, str(rule.get("path") or ""))
                actual_projection = actual
            expected = rule.get("value")
            checks.append(
                self._check(
                    rule=rule,
                    category="capacity",
                    passed=_comparison(actual, str(rule.get("operator") or ""), expected),
                    actual=actual_projection,
                    expected=expected,
                    default_message="容量约束不满足",
                )
            )

        for rule in policy.conflict_rules or []:
            paths = [str(item) for item in rule.get("paths") or [] if str(item)]
            present = []
            for path in paths:
                value = value_at(candidate, path)
                if value is not _MISSING and value is not None and value is not False:
                    present.append(path)
            max_present = max(0, int(rule.get("max_present", 1)))
            checks.append(
                self._check(
                    rule=rule,
                    category="conflict",
                    passed=len(present) <= max_present,
                    actual=present,
                    expected={"max_present": max_present, "paths": paths},
                    default_message="检测到互斥配置冲突",
                )
            )

        if policy.dry_run_operation:
            dry_run_payload = dict(dry_run or {})
            passed = str(dry_run_payload.get("status") or "") in {"pass", "passed"}
            checks.append(
                ConfigCheck(
                    "dry-run",
                    "dry_run",
                    "pass" if passed else "fail",
                    "error",
                    message="dry-run 通过" if passed else "dry-run 未执行或失败",
                    expected={"operation": policy.dry_run_operation, "status": "passed"},
                    actual=dry_run_payload,
                )
            )
        else:
            checks.append(
                ConfigCheck(
                    "dry-run",
                    "dry_run",
                    "skipped",
                    "warning",
                    message="策略未声明 dry-run 操作",
                )
            )

        errors = [item for item in checks if item.status == "fail" and item.severity == "error"]
        warnings = [
            item
            for item in checks
            if item.status in {"fail", "skipped"} and item.severity == "warning"
        ]
        status = "fail" if errors else ("warn" if warnings else "pass")
        categories_failed = sorted({item.category for item in errors})
        risk_level = (
            "critical"
            if {"schema", "capacity", "conflict", "dry_run"}.intersection(categories_failed)
            else ("high" if errors else ("medium" if warnings else "low"))
        )
        score = max(0.0, min(1.0, 1.0 - len(errors) * 0.18 - len(warnings) * 0.06))
        if not math.isfinite(score):
            score = 0.0
        return ConfigValidationReport(
            status=status,
            risk_level=risk_level,
            checks=tuple(checks),
            summary={
                "total": len(checks),
                "passed": sum(item.status == "pass" for item in checks),
                "errors": len(errors),
                "warnings": len(warnings),
                "failed_categories": categories_failed,
                "confidence": round(score, 4),
            },
        )


class ConfigIntelligenceService:
    """配置策略、快照和校验运行均绑定 tenant/workspace。"""

    def __init__(self, db: AsyncSession, scope: ProductionScope) -> None:
        self.db = db
        self.scope = scope

    def _scope_filter(self, model: Any) -> tuple[Any, Any]:
        return (
            model.tenant_id == self.scope.tenant_id,
            model.workspace_id == self.scope.workspace_id,
        )

    async def _asset_lock(self, asset_id: str) -> None:
        try:
            dialect = self.db.get_bind().dialect.name
        except (AttributeError, RuntimeError):
            return
        if dialect == "postgresql":
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
                {
                    "scope_key": (
                        f"production_config:{self.scope.tenant_id}:"
                        f"{self.scope.workspace_id}:{asset_id}"
                    )
                },
            )

    async def _validate_response(self, response_id: str | None) -> None:
        if not response_id:
            return
        response = await self.db.scalar(
            select(ResponseRecord.id).where(
                ResponseRecord.id == response_id,
                ResponseRecord.tenant_id == self.scope.tenant_id,
                ResponseRecord.workspace_id == self.scope.workspace_id,
            )
        )
        if response is None:
            raise ConfigIntelligenceError("config_response_scope_mismatch")

    async def require_config_asset(self, asset_id: str) -> ProductionAsset:
        asset = await self.db.scalar(
            select(ProductionAsset).where(
                ProductionAsset.id == asset_id,
                *self._scope_filter(ProductionAsset),
                ProductionAsset.asset_type == "config",
                ProductionAsset.status == "active",
            )
        )
        if asset is None:
            raise ConfigIntelligenceError("config_asset_not_found")
        return asset

    async def latest_policy(
        self, asset_id: str, *, status: str = "published"
    ) -> ProductionConfigPolicy | None:
        if status not in _POLICY_STATUSES:
            raise ConfigIntelligenceError("config_policy_status_invalid")
        return await self.db.scalar(
            select(ProductionConfigPolicy)
            .where(
                *self._scope_filter(ProductionConfigPolicy),
                ProductionConfigPolicy.asset_id == asset_id,
                ProductionConfigPolicy.status == status,
            )
            .order_by(ProductionConfigPolicy.version.desc())
            .limit(1)
        )

    async def policies(self, asset_id: str, *, limit: int = 50) -> list[ProductionConfigPolicy]:
        await self.require_config_asset(asset_id)
        result = await self.db.execute(
            select(ProductionConfigPolicy)
            .where(
                *self._scope_filter(ProductionConfigPolicy),
                ProductionConfigPolicy.asset_id == asset_id,
            )
            .order_by(ProductionConfigPolicy.version.desc())
            .limit(max(1, min(limit, 100)))
        )
        return list(result.scalars().all())

    async def create_policy(
        self,
        *,
        asset_id: str,
        schema: dict[str, Any],
        reference_rules: list[dict[str, Any]] | None = None,
        business_rules: list[dict[str, Any]] | None = None,
        history_rules: list[dict[str, Any]] | None = None,
        capacity_rules: list[dict[str, Any]] | None = None,
        conflict_rules: list[dict[str, Any]] | None = None,
        dry_run_operation: str | None = None,
    ) -> ProductionConfigPolicy:
        await self.require_config_asset(asset_id)
        await self._asset_lock(asset_id)
        _validate_config_schema(schema)
        if dry_run_operation and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", str(dry_run_operation)
        ):
            raise ConfigIntelligenceError("config_dry_run_operation_invalid")
        rules = {
            "reference_rules": [
                _validate_rule(item, category="reference") for item in reference_rules or []
            ],
            "business_rules": [
                _validate_rule(item, category="business") for item in business_rules or []
            ],
            "history_rules": [
                _validate_rule(item, category="history") for item in history_rules or []
            ],
            "capacity_rules": [
                _validate_rule(item, category="capacity") for item in capacity_rules or []
            ],
            "conflict_rules": [
                _validate_rule(item, category="conflict") for item in conflict_rules or []
            ],
        }
        _bounded_json({"schema": schema, **rules})
        latest_version = await self.db.scalar(
            select(ProductionConfigPolicy.version)
            .where(
                *self._scope_filter(ProductionConfigPolicy),
                ProductionConfigPolicy.asset_id == asset_id,
            )
            .order_by(ProductionConfigPolicy.version.desc())
            .limit(1)
        )
        row = ProductionConfigPolicy(
            id=str(uuid.uuid4()),
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            asset_id=asset_id,
            version=int(latest_version or 0) + 1,
            status="draft",
            schema=dict(schema),
            dry_run_operation=str(dry_run_operation or "").strip() or None,
            created_by=self.scope.user_id,
            **rules,
        )
        self.db.add(row)
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_config_policy.created",
            resource_type="production_config_policy",
            resource_id=row.id,
            payload={"asset_id": asset_id, "version": row.version},
        )
        return row

    async def publish_policy(self, policy_id: str) -> ProductionConfigPolicy:
        row = await self.db.scalar(
            select(ProductionConfigPolicy)
            .where(
                ProductionConfigPolicy.id == policy_id,
                *self._scope_filter(ProductionConfigPolicy),
            )
            .with_for_update()
        )
        if row is None:
            raise ConfigIntelligenceError("config_policy_not_found")
        if row.status != "draft":
            raise ConfigIntelligenceError("config_policy_not_draft")
        await self._asset_lock(row.asset_id)
        if row.dry_run_operation:
            asset = await self.require_config_asset(row.asset_id)
            connector = (
                await self.db.scalar(
                    select(EnterpriseConnector).where(
                        EnterpriseConnector.id == asset.connector_id,
                        EnterpriseConnector.tenant_id == self.scope.tenant_id,
                        EnterpriseConnector.workspace_id == self.scope.workspace_id,
                        EnterpriseConnector.status == "enabled",
                    )
                )
                if asset.connector_id
                else None
            )
            if connector is None:
                raise ConfigIntelligenceError("config_dry_run_connector_not_ready")
            from services.production_intelligence.actions import operation_spec

            spec = operation_spec(connector, row.dry_run_operation)
            if spec is None or spec.risk != "read" or not spec.evidence_types:
                raise ConfigIntelligenceError("config_dry_run_operation_not_ready")
        previous = await self.latest_policy(row.asset_id)
        if previous is not None:
            previous.status = "retired"
        row.status = "published"
        row.published_by = self.scope.user_id
        row.published_at = datetime.now(UTC)
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_config_policy.published",
            resource_type="production_config_policy",
            resource_id=row.id,
            payload={"asset_id": row.asset_id, "version": row.version},
        )
        await self.db.flush()
        return row

    async def record_snapshot(
        self,
        *,
        asset_id: str,
        environment: str,
        version_ref: str,
        source_ref: str,
        content: dict[str, Any],
        status: str = "current",
        policy_id: str | None = None,
        response_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> ProductionConfigSnapshot:
        await self.require_config_asset(asset_id)
        await self._asset_lock(asset_id)
        await self._validate_response(response_id)
        if status not in _SNAPSHOT_STATUSES:
            raise ConfigIntelligenceError("config_snapshot_status_invalid")
        _bounded_json(content)
        if not version_ref.strip() or not source_ref.strip():
            raise ConfigIntelligenceError("config_snapshot_provenance_required")
        if policy_id:
            policy = await self.db.scalar(
                select(ProductionConfigPolicy.id).where(
                    ProductionConfigPolicy.id == policy_id,
                    ProductionConfigPolicy.tenant_id == self.scope.tenant_id,
                    ProductionConfigPolicy.workspace_id == self.scope.workspace_id,
                    ProductionConfigPolicy.asset_id == asset_id,
                )
            )
            if policy is None:
                raise ConfigIntelligenceError("config_snapshot_policy_scope_mismatch")
        normalized_environment = environment.strip() or "shared"
        if status == "current":
            await self.db.execute(
                update(ProductionConfigSnapshot)
                .where(
                    ProductionConfigSnapshot.tenant_id == self.scope.tenant_id,
                    ProductionConfigSnapshot.workspace_id == self.scope.workspace_id,
                    ProductionConfigSnapshot.asset_id == asset_id,
                    ProductionConfigSnapshot.environment == normalized_environment,
                    ProductionConfigSnapshot.status == "current",
                )
                .values(status="historical")
            )
        row = ProductionConfigSnapshot(
            id=str(uuid.uuid4()),
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            response_id=response_id,
            asset_id=asset_id,
            policy_id=policy_id,
            environment=normalized_environment,
            version_ref=version_ref.strip(),
            source_ref=_safe_source_ref(source_ref),
            status=status,
            content=mask_sensitive(dict(content)),
            content_hash=canonical_hash(content),
            observed_at=observed_at or datetime.now(UTC),
            created_by=self.scope.user_id,
        )
        self.db.add(row)
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_config_snapshot.recorded",
            resource_type="production_config_snapshot",
            resource_id=row.id,
            payload={
                "asset_id": asset_id,
                "environment": row.environment,
                "status": status,
                "content_hash": row.content_hash,
            },
        )
        return row

    async def snapshots(
        self, asset_id: str, *, environment: str, limit: int = 20
    ) -> list[ProductionConfigSnapshot]:
        result = await self.db.execute(
            select(ProductionConfigSnapshot)
            .where(
                *self._scope_filter(ProductionConfigSnapshot),
                ProductionConfigSnapshot.asset_id == asset_id,
                ProductionConfigSnapshot.environment == environment,
            )
            .order_by(ProductionConfigSnapshot.observed_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return list(result.scalars().all())

    async def validate_and_record(
        self,
        *,
        asset_id: str,
        candidate: dict[str, Any],
        response_id: str | None,
        environment: str,
        dry_run: dict[str, Any] | None = None,
    ) -> tuple[ProductionConfigValidationRun, ConfigValidationReport]:
        await self.require_config_asset(asset_id)
        await self._validate_response(response_id)
        _bounded_json(candidate)
        policy = await self.latest_policy(asset_id)
        if policy is None:
            raise ConfigIntelligenceError("published_config_policy_required")
        snapshots = await self.snapshots(asset_id, environment=environment)
        history = [dict(item.content or {}) for item in snapshots]
        report = DeterministicConfigValidator().validate(
            candidate=candidate,
            policy=policy,
            history=history,
            dry_run=dry_run,
        )
        CONFIG_VALIDATION_TOTAL.labels(status=report.status, risk_level=report.risk_level).inc()
        row = ProductionConfigValidationRun(
            id=str(uuid.uuid4()),
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            response_id=response_id,
            asset_id=asset_id,
            policy_id=policy.id,
            snapshot_id=snapshots[0].id if snapshots else None,
            candidate_hash=canonical_hash(candidate),
            status=report.status,
            risk_level=report.risk_level,
            checks=[item.to_dict() for item in report.checks],
            dry_run=mask_sensitive(dict(dry_run or {})),
            summary=dict(report.summary),
            created_by=self.scope.user_id,
        )
        self.db.add(row)
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_config.validated",
            resource_type="production_config_validation_run",
            resource_id=row.id,
            payload={
                "asset_id": asset_id,
                "policy_id": policy.id,
                "status": report.status,
                "risk_level": report.risk_level,
                "candidate_hash": row.candidate_hash,
                "response_id": response_id,
            },
        )
        return row, report

    async def validation_runs(
        self, asset_id: str, *, limit: int = 50
    ) -> list[ProductionConfigValidationRun]:
        await self.require_config_asset(asset_id)
        result = await self.db.execute(
            select(ProductionConfigValidationRun)
            .where(
                *self._scope_filter(ProductionConfigValidationRun),
                ProductionConfigValidationRun.asset_id == asset_id,
            )
            .order_by(ProductionConfigValidationRun.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return list(result.scalars().all())
