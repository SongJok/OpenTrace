"""Production Agent：资产图与外部生产系统的只读证据采集专家。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from agents.base import AgentResult, BaseAgent, TaskMessage
from connectors.contracts import ConnectorExecutionContext, ConnectorOperationSpec
from connectors.gateway import ConnectorGatewayError, GovernedConnectorGateway
from connectors.registry import connector_registry
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import EnterpriseConnector, ProductionAsset, User
from services.production_intelligence.actions import discover_production_actions
from services.production_intelligence.asset_graph import (
    AssetGraphService,
    ProductionScope,
    asset_to_dict,
)
from services.production_intelligence.audit import mask_sensitive
from services.production_intelligence.evidence_critic import (
    ProductionEvidenceCritic,
    render_evidence_answer,
)
from tenant.tenant_rls import set_session_scope

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.:/-]{1,63}|[\u4e00-\u9fff]{2,12}")
_PROD_RE = re.compile(r"生产|线上|prod|production", re.IGNORECASE)
_DOMAIN_PATTERNS: dict[str, re.Pattern[str]] = {
    "observability": re.compile(
        r"故障|异常|错误|超时|延迟|告警|日志|指标|调用链|trace|metric|log|apm|alert",
        re.IGNORECASE,
    ),
    "code": re.compile(r"代码|提交|分支|仓库|合并|pull request|commit|git|sonar", re.IGNORECASE),
    "cicd": re.compile(r"发布|部署|流水线|构建|回滚|ci/?cd|deploy|release", re.IGNORECASE),
    "business": re.compile(r"订单|活动|客户|业务|工单|交易|库存|campaign|order", re.IGNORECASE),
    "cmdb": re.compile(r"资产|服务|负责人|归属|拓扑|依赖|cmdb|owner", re.IGNORECASE),
    "kubernetes": re.compile(r"pod|容器|节点|集群|k8s|kubernetes", re.IGNORECASE),
}


def _query_tokens(query: str) -> list[str]:
    stop = {"什么", "怎么", "如何", "为什么", "是否", "当前", "一下", "请问", "帮我"}
    return [item.lower() for item in _TOKEN_RE.findall(query or "") if item.lower() not in stop][
        :32
    ]


def _bounded_projection(value: Any, *, max_bytes: int) -> Any:
    sanitized = mask_sensitive(value)
    encoded = json.dumps(sanitized, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= max_bytes:
        return sanitized
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "truncated": True,
        "original_bytes": len(encoded),
        "sha256": digest,
        "top_level_keys": (
            sorted(str(key) for key in value)[:100] if isinstance(value, dict) else []
        ),
    }


def _asset_score(asset: ProductionAsset, query: str) -> float:
    tokens = _query_tokens(query)
    haystack = "\n".join(
        (
            str(asset.name or ""),
            str(asset.external_key or ""),
            str(asset.description or ""),
            str(asset.asset_type or ""),
        )
    ).lower()
    score = sum(
        2.0 if token in str(asset.name or "").lower() else 1.0
        for token in tokens
        if token in haystack
    )
    if str(asset.environment or "") == "prod" and _PROD_RE.search(query or ""):
        score += 1.0
    return score


def _target_domains(query: str) -> set[str]:
    domains = {
        domain for domain, pattern in _DOMAIN_PATTERNS.items() if pattern.search(query or "")
    }
    if not domains:
        domains.add("cmdb")
    domains.add("asset")
    return domains


def _normalized_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _asset_observed_at(asset: ProductionAsset) -> datetime | None:
    for value in (asset.last_seen_at, asset.updated_at, asset.created_at):
        observed_at = _normalized_timestamp(value)
        if observed_at is not None:
            return observed_at
    return None


def _graph_observed_at(projection: dict[str, Any]) -> datetime | None:
    """聚合图证据使用最旧组成事实的时间，避免新节点掩盖陈旧关系。"""

    timestamps: list[datetime] = []
    for item in [*(projection.get("nodes") or []), *(projection.get("edges") or [])]:
        if not isinstance(item, dict):
            continue
        for key in ("last_seen_at", "updated_at", "created_at"):
            observed_at = _normalized_timestamp(item.get(key))
            if observed_at is not None:
                timestamps.append(observed_at)
                break
    return min(timestamps) if timestamps else None


def _operation_spec(
    connector: EnterpriseConnector, operation: str
) -> ConnectorOperationSpec | None:
    adapter_key = str((connector.config or {}).get("adapter_key") or connector.connector_kind)
    adapter = connector_registry.get(adapter_key)
    if adapter is None:
        return None
    dynamic = getattr(adapter, "operation_spec", None)
    if callable(dynamic):
        spec = dynamic(operation, dict(connector.config or {}))
        if spec is not None:
            return spec
    return next((item for item in adapter.operations() if item.name == operation), None)


def _operation_score(
    connector: EnterpriseConnector,
    spec: ConnectorOperationSpec,
    query: str,
    domains: set[str],
) -> float:
    if spec.risk != "read" or spec.domain not in domains:
        return -1.0
    text = f"{spec.name} {spec.description} {spec.domain}".lower()
    overlap = sum(1.0 for token in _query_tokens(query) if token in text)
    kind_bonus = 2.0 if connector.connector_kind in domains else 0.0
    return 1.0 + overlap + kind_bonus


def _build_arguments(
    schema: dict[str, Any],
    *,
    query: str,
    environment: str,
    asset: ProductionAsset | None,
) -> dict[str, Any] | None:
    """只绑定平台可信值；无法满足必填字段时跳过操作，不让模型猜参数。"""

    properties = dict(schema.get("properties") or {})
    required = {str(item) for item in schema.get("required") or []}
    bindings = {
        "query": query,
        "question": query,
        "search": query,
        "environment": environment,
        "env": environment,
        "asset_id": getattr(asset, "id", None),
        "service": getattr(asset, "external_key", None) or getattr(asset, "name", None),
        "service_name": getattr(asset, "name", None),
        "repository": getattr(asset, "external_key", None) or getattr(asset, "name", None),
        "resource": getattr(asset, "external_key", None) or getattr(asset, "name", None),
    }
    arguments: dict[str, Any] = {}
    for name, property_schema in properties.items():
        value = bindings.get(name)
        if value is None and isinstance(property_schema, dict) and "default" in property_schema:
            value = property_schema["default"]
        if value is not None:
            arguments[name] = value
    if required - set(arguments):
        return None
    return arguments


def _environment(query: str, assets: list[ProductionAsset], connector: EnterpriseConnector) -> str:
    allowed = [str(item) for item in connector.allowed_environments or [] if str(item)]
    asset_environments = [str(item.environment) for item in assets if str(item.environment)]
    for candidate in asset_environments:
        if not allowed or candidate in allowed:
            return candidate
    if _PROD_RE.search(query or "") and (not allowed or "prod" in allowed):
        return "prod"
    return allowed[0] if allowed else "shared"


class ProductionAgent(BaseAgent):
    """只读采集生产证据；不生成最终事实、不执行任何生产写入。"""

    def __init__(self) -> None:
        super().__init__("production")

    async def execute(self, task: TaskMessage) -> AgentResult:
        tenant_id = str(task.params.get("tenant_id") or "").strip()
        workspace_id = str(task.params.get("workspace_id") or "").strip()
        response_id = str(task.params.get("response_id") or "").strip() or None
        user_id = str(task.user_id or "").strip()
        if not all((tenant_id, workspace_id, user_id)):
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error="trusted_production_scope_required",
            )

        evidence: list[dict[str, Any]] = []
        gaps: list[str] = []
        connector_results: list[dict[str, Any]] = []
        action_catalog: list[dict[str, Any]] = []
        async with AsyncSessionLocal() as db:
            await set_session_scope(db, tenant_id=tenant_id, workspace_id=workspace_id)
            user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
            if user is None:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="production_user_not_authorized",
                )
            scope = ProductionScope(tenant_id, workspace_id, user_id)
            graph = AssetGraphService(db, scope)
            all_assets = await graph.list_assets(status="active", limit=300)
            ranked = sorted(
                ((item, _asset_score(item, task.query)) for item in all_assets),
                key=lambda pair: (-pair[1], pair[0].name),
            )
            matched_assets = [item for item, score in ranked if score > 0][:8]
            if not matched_assets:
                gaps.append("未可靠定位生产资产；未将任意工作区资产静默绑定到本次请求")

            for asset in matched_assets:
                observed_at = _asset_observed_at(asset)
                if observed_at is None:
                    gaps.append(f"资产 {asset.name} 缺少可核验的目录观测时间")
                    continue
                evidence.append(
                    {
                        "evidence_type": "asset",
                        "source_kind": "asset_graph",
                        "source_ref": f"production-asset://{asset.id}",
                        "asset_id": asset.id,
                        "title": f"{asset.asset_type}：{asset.name}",
                        "summary": asset.description
                        or f"{asset.external_key}（{asset.environment}）",
                        "environment": asset.environment,
                        "authority": "governed_asset_catalog",
                        "confidence": 0.9,
                        "observed_at": observed_at.isoformat(),
                        "payload": {
                            "external_key": asset.external_key,
                            "criticality": asset.criticality,
                            "classification": asset.classification,
                        },
                        "requirements": ["asset_context"],
                    }
                )

            graph_projection: dict[str, Any] = {"nodes": [], "edges": [], "truncated": False}
            if matched_assets:
                graph_projection = await graph.neighborhood(
                    matched_assets[0].id, depth=2, max_nodes=80, max_edges=160
                )
                if graph_projection.get("edges"):
                    graph_observed_at = _graph_observed_at(graph_projection)
                    if graph_observed_at is None:
                        gaps.append("生产资产关系缺少可核验的来源观测时间")
                    else:
                        evidence.append(
                            {
                                "evidence_type": "asset_graph",
                                "source_kind": "asset_graph",
                                "source_ref": f"production-graph://{matched_assets[0].id}",
                                "asset_id": matched_assets[0].id,
                                "title": f"{matched_assets[0].name} 生产资产关系",
                                "summary": (
                                    f"包含 {len(graph_projection.get('nodes') or [])} 个节点和 "
                                    f"{len(graph_projection.get('edges') or [])} 条关系"
                                ),
                                "environment": matched_assets[0].environment,
                                "authority": "governed_asset_catalog",
                                "confidence": 0.9,
                                "observed_at": graph_observed_at.isoformat(),
                                "payload": {
                                    "relations": [
                                        dict(item)
                                        for item in (graph_projection.get("edges") or [])[:40]
                                        if isinstance(item, dict)
                                    ]
                                },
                                "requirements": ["asset_context"],
                            }
                        )

            rows = await db.execute(
                select(EnterpriseConnector).where(
                    EnterpriseConnector.tenant_id == tenant_id,
                    EnterpriseConnector.workspace_id == workspace_id,
                    EnterpriseConnector.status == "enabled",
                )
            )
            connectors = list(rows.scalars().all())
            domains = _target_domains(task.query)
            candidates: list[
                tuple[float, EnterpriseConnector, ConnectorOperationSpec, dict[str, Any], str]
            ] = []
            primary_asset = matched_assets[0] if matched_assets else None
            for connector in connectors:
                environment = _environment(task.query, matched_assets, connector)
                for operation in connector.allowed_operations or []:
                    spec = _operation_spec(connector, str(operation))
                    if spec is None:
                        continue
                    score = _operation_score(connector, spec, task.query, domains)
                    arguments = _build_arguments(
                        spec.input_schema,
                        query=task.query,
                        environment=environment,
                        asset=primary_asset,
                    )
                    if score < 0 or arguments is None:
                        continue
                    candidates.append((score, connector, spec, arguments, environment))
            candidates.sort(key=lambda item: (-item[0], item[1].name, item[2].name))

            gateway = GovernedConnectorGateway()
            used_connectors: set[str] = set()
            for _score, connector, spec, arguments, environment in candidates:
                if len(used_connectors) >= 6 or connector.id in used_connectors:
                    continue
                used_connectors.add(connector.id)
                context = ConnectorExecutionContext(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    response_id=response_id,
                    role=str(user.role or "user"),
                    is_superuser=bool(user.is_superuser),
                    environment=environment,
                    trace_id=task.task_id,
                )
                try:
                    result = await gateway.execute(
                        db,
                        connector_id=connector.id,
                        operation=spec.name,
                        arguments=arguments,
                        context=context,
                    )
                except ConnectorGatewayError as exc:
                    gaps.append(f"{connector.name}/{spec.name}：{exc}")
                    continue
                connector_results.append(
                    {
                        "connector_id": connector.id,
                        "connector_name": connector.name,
                        "operation": spec.name,
                        "environment": environment,
                        "data": _bounded_projection(dict(result.data or {}), max_bytes=32_768),
                    }
                )
                for item in result.evidence[:30]:
                    if len(evidence) >= 120:
                        gaps.append("生产证据达到单次 Response 的 120 条安全上限")
                        break
                    evidence.append(
                        {
                            "evidence_type": item.evidence_type,
                            "source_kind": item.source_kind or connector.connector_kind,
                            "source_ref": item.source_ref,
                            "connector_id": connector.id,
                            "asset_id": item.asset_id,
                            "title": item.title,
                            "summary": item.summary,
                            "environment": item.environment or environment,
                            "authority": item.authority,
                            "permission_class": item.permission_class,
                            "confidence": item.confidence,
                            "observed_at": item.observed_at.isoformat(),
                            "payload": _bounded_projection(
                                dict(item.payload or {}), max_bytes=8_192
                            ),
                            "requirements": ["live_observation"],
                        }
                    )
            if matched_assets:
                action_catalog = await discover_production_actions(
                    db,
                    scope=scope,
                    user=user,
                    query=task.query,
                    assets=matched_assets,
                )
            await db.commit()

        if not connector_results:
            gaps.append("没有可执行且满足最小权限的生产只读 Connector 操作")
        requires_live = bool(_target_domains(task.query) - {"asset", "cmdb"})
        requirements = {"asset_context"}
        if requires_live:
            requirements.update({"live_observation", "cross_source_corroboration"})
        expected_environment = "prod" if _PROD_RE.search(task.query or "") else None
        critic = ProductionEvidenceCritic().assess(
            evidence,
            required=requirements,
            expected_environment=expected_environment,
        )
        gaps.extend(critic.gaps)
        asset_names = "、".join(item.name for item in matched_assets[:5]) or "未定位"
        conclusion = (
            f"已定位资产：{asset_names}；采集到 {len(connector_results)} 个受治理生产来源结果。"
            if evidence
            else "未取得可用于生产判断的受治理证据。"
        )
        content = render_evidence_answer(
            conclusion=conclusion,
            evidence=evidence,
            critic=critic,
            impact="仅完成只读分析，未修改生产系统、配置、代码或业务数据。",
            recommendation=(
                "优先补齐 Critic 指出的证据缺口，再决定是否创建需要审批的处置操作。"
                if critic.status != "pass"
                else "由 Manager 结合全部证据形成结论；涉及变更时必须另行发起持久审批。"
            ),
        )
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=content,
            confidence=critic.confidence,
            evidence=evidence,
            metadata={
                "mode": "governed_production_read",
                "read_only": True,
                "needs_clarification": not matched_assets and bool(all_assets),
                "asset_candidates": [asset_to_dict(item) for item, _score in ranked[:10]],
                "assets": [asset_to_dict(item) for item in matched_assets],
                "asset_graph": {
                    "nodes": list(graph_projection.get("nodes") or []),
                    "edges": list(graph_projection.get("edges") or []),
                    "truncated": bool(graph_projection.get("truncated")),
                },
                "connector_results": connector_results,
                "action_catalog": action_catalog,
                "critic": critic.to_dict(),
                "gaps": list(dict.fromkeys(gaps)),
            },
        )
