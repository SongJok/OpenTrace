"""生产证据归一、交叉验证与确定性 Critic。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from infra.observability.metrics import PRODUCTION_EVIDENCE_CRITIC_TOTAL

_LIVE_TYPES = frozenset(
    {
        "metric",
        "log",
        "trace",
        "alert",
        "deployment",
        "business_record",
        "config_snapshot",
        "code_change",
    }
)
_ASSET_TYPES = frozenset({"asset", "asset_graph", "ownership", "dependency"})
_CONFIG_TYPES = frozenset({"config_validation", "config_snapshot", "config_dry_run"})
_CAUSAL_TYPES = frozenset({"trace", "config_change", "deployment", "code_change", "audit_event"})

_FRESHNESS_WINDOWS: dict[str, timedelta] = {
    "metric": timedelta(minutes=15),
    "log": timedelta(minutes=30),
    "trace": timedelta(minutes=30),
    "alert": timedelta(hours=2),
    "deployment": timedelta(days=2),
    "config_snapshot": timedelta(days=1),
    "config_validation": timedelta(hours=1),
    "config_dry_run": timedelta(hours=1),
    "code_change": timedelta(days=7),
    "business_record": timedelta(days=1),
    "asset": timedelta(days=30),
    "asset_graph": timedelta(days=30),
    "ownership": timedelta(days=30),
    "dependency": timedelta(days=30),
}


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _evidence_type(item: dict[str, Any]) -> str:
    return str(item.get("evidence_type") or item.get("type") or "").strip().lower()


def _source_identity(item: dict[str, Any]) -> str:
    connector_id = str(item.get("connector_id") or "").strip()
    if connector_id:
        return f"connector:{connector_id}"
    source_kind = str(item.get("source_kind") or item.get("authority") or "unknown")
    return f"source-kind:{source_kind}"


@dataclass(frozen=True, slots=True)
class CriticAssessment:
    status: str
    confidence: float
    requirements_satisfied: tuple[str, ...]
    requirements_missing: tuple[str, ...]
    gaps: tuple[str, ...]
    conflicts: tuple[dict[str, Any], ...]
    source_count: int
    evidence_count: int
    causal_strength: str
    environment_aligned: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "production_evidence_critic.v1",
            "status": self.status,
            "confidence": self.confidence,
            "requirements_satisfied": list(self.requirements_satisfied),
            "requirements_missing": list(self.requirements_missing),
            "gaps": list(self.gaps),
            "conflicts": [dict(item) for item in self.conflicts],
            "source_count": self.source_count,
            "evidence_count": self.evidence_count,
            "causal_strength": self.causal_strength,
            "environment_aligned": self.environment_aligned,
        }


class ProductionEvidenceCritic:
    """检查证据时效、环境、独立来源、冲突和因果强度。"""

    @staticmethod
    def _requirements(evidence: list[dict[str, Any]], source_count: int) -> set[str]:
        types = {_evidence_type(item) for item in evidence}
        satisfied: set[str] = set()
        if types.intersection(_ASSET_TYPES):
            satisfied.add("asset_context")
        if types.intersection(_LIVE_TYPES):
            satisfied.add("live_observation")
        if source_count >= 2:
            satisfied.add("cross_source_corroboration")
        if any(
            _evidence_type(item) == "config_validation"
            and str(dict(item.get("payload") or {}).get("status") or "") == "pass"
            for item in evidence
        ):
            satisfied.add("config_validation")
        if any(
            _evidence_type(item) == "config_dry_run"
            and str(dict(item.get("payload") or {}).get("verification_status") or "")
            in {"pass", "passed"}
            for item in evidence
        ):
            satisfied.add("config_dry_run")
        return satisfied

    @staticmethod
    def _conflicts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        claims: dict[str, dict[str, set[str]]] = {}
        for item in evidence:
            payload = dict(item.get("payload") or {})
            claim_key = str(payload.get("claim_key") or "").strip()
            if not claim_key or "claim_value" not in payload:
                continue
            source = _source_identity(item)
            value = str(payload.get("claim_value"))[:500]
            claims.setdefault(claim_key, {}).setdefault(value, set()).add(source)
        return [
            {
                "claim_key": key,
                "values": [
                    {"value": value, "sources": sorted(sources)}
                    for value, sources in sorted(values.items())
                ],
            }
            for key, values in claims.items()
            if len(values) > 1
        ]

    def assess(
        self,
        evidence: list[dict[str, Any]],
        *,
        required: set[str] | None = None,
        expected_environment: str | None = None,
        now: datetime | None = None,
    ) -> CriticAssessment:
        evaluated_at = now or datetime.now(UTC)
        normalized = [dict(item) for item in evidence if isinstance(item, dict)]
        sources = {_source_identity(item) for item in normalized if _source_identity(item)}
        gaps: list[str] = []
        stale = 0
        confidence_values: list[float] = []
        environments: set[str] = set()
        causal_count = 0
        correlation_count = 0
        for item in normalized:
            evidence_type = _evidence_type(item)
            observed_at = _timestamp(item.get("observed_at"))
            expires_at = _timestamp(item.get("expires_at"))
            environment = str(item.get("environment") or "shared")
            environments.add(environment)
            if evidence_type in _CAUSAL_TYPES:
                causal_count += 1
            if evidence_type in {"metric", "alert", "business_record"}:
                correlation_count += 1
            window = _FRESHNESS_WINDOWS.get(evidence_type, timedelta(days=7))
            is_stale = expires_at is not None and expires_at < evaluated_at
            if observed_at is None:
                is_stale = True
            elif observed_at > evaluated_at + timedelta(minutes=5):
                is_stale = True
            elif evaluated_at - observed_at > window:
                is_stale = True
            if is_stale:
                stale += 1
            try:
                confidence_values.append(max(0.0, min(1.0, float(item.get("confidence", 0.5)))))
            except (TypeError, ValueError):
                confidence_values.append(0.0)
        if stale:
            gaps.append(f"{stale} 条证据已过期、缺少时间戳或时间异常")

        environment_aligned = not expected_environment or all(
            item in {expected_environment, "shared"} for item in environments
        )
        if not environment_aligned:
            gaps.append("证据环境与目标环境不一致")
        conflicts = self._conflicts(normalized)
        if conflicts:
            gaps.append(f"发现 {len(conflicts)} 组来源冲突")

        satisfied = self._requirements(normalized, len(sources))
        requested = set(required or set())
        missing = sorted(requested - satisfied)
        if missing:
            gaps.append("缺少证据要求：" + "、".join(missing))
        if len(sources) < 2 and "cross_source_corroboration" in requested:
            gaps.append("缺少第二个独立来源，不能完成交叉验证")

        causal_strength = (
            "strong" if causal_count >= 2 else ("moderate" if causal_count else "weak")
        )
        if causal_count == 0 and correlation_count:
            gaps.append("当前只有相关性观测，没有因果链证据")

        base = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        coverage = 1.0 if not requested else len(requested.intersection(satisfied)) / len(requested)
        confidence = base * 0.6 + coverage * 0.4
        confidence -= min(0.35, stale * 0.08)
        confidence -= min(0.3, len(conflicts) * 0.15)
        if not environment_aligned:
            confidence -= 0.2
        confidence = round(max(0.0, min(1.0, confidence)), 4)
        blocking = bool(missing or conflicts or not environment_aligned)
        status = "blocked" if blocking else ("incomplete" if gaps else "pass")
        assessment = CriticAssessment(
            status=status,
            confidence=confidence,
            requirements_satisfied=tuple(sorted(satisfied)),
            requirements_missing=tuple(missing),
            gaps=tuple(dict.fromkeys(gaps)),
            conflicts=tuple(conflicts),
            source_count=len(sources),
            evidence_count=len(normalized),
            causal_strength=causal_strength,
            environment_aligned=environment_aligned,
        )
        PRODUCTION_EVIDENCE_CRITIC_TOTAL.labels(
            status=assessment.status, causal_strength=assessment.causal_strength
        ).inc()
        return assessment


def render_evidence_answer(
    *,
    conclusion: str,
    evidence: list[dict[str, Any]],
    critic: CriticAssessment,
    impact: str,
    recommendation: str,
) -> str:
    """受控 Agent 的统一输出格式；最终措辞仍由 Manager 合成。"""

    evidence_lines = [
        f"- [{index}] {item.get('title') or item.get('evidence_type') or '证据'}："
        f"{item.get('summary') or item.get('source_ref') or '无摘要'}"
        for index, item in enumerate(evidence[:12], start=1)
    ]
    if not evidence_lines:
        evidence_lines = ["- 未取得可核验的生产证据。"]
    gap_text = "；".join(critic.gaps) if critic.gaps else "无阻断缺口"
    return "\n".join(
        (
            "## 结论",
            conclusion,
            "",
            "## 证据",
            *evidence_lines,
            "",
            "## 置信度",
            f"{critic.confidence:.2f}（{critic.status}；{gap_text}）",
            "",
            "## 影响",
            impact,
            "",
            "## 建议",
            recommendation,
        )
    )
