"""Config Agent：配置策略、快照、冲突与 dry-run 的只读验证专家。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.production_agent import (
    _asset_observed_at,
    _asset_score,
    _bounded_projection,
    _operation_spec,
)
from connectors.contracts import ConnectorEvidence, ConnectorExecutionContext
from connectors.gateway import ConnectorGatewayError, GovernedConnectorGateway
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import ProductionAsset, User
from services.production_intelligence.asset_graph import ProductionScope, asset_to_dict
from services.production_intelligence.config_intelligence import (
    ConfigIntelligenceError,
    ConfigIntelligenceService,
    canonical_hash,
)
from services.production_intelligence.evidence_critic import (
    ProductionEvidenceCritic,
    render_evidence_answer,
)
from tenant.tenant_rls import set_session_scope


def _dry_run_arguments(
    schema: dict[str, Any],
    *,
    candidate: dict[str, Any],
    asset: ProductionAsset,
    environment: str,
    query: str,
) -> dict[str, Any] | None:
    properties = dict(schema.get("properties") or {})
    required = {str(item) for item in schema.get("required") or []}
    bindings: dict[str, Any] = {
        "candidate": candidate,
        "config": candidate,
        "content": candidate,
        "asset_id": asset.id,
        "config_key": asset.external_key,
        "environment": environment,
        "env": environment,
        "query": query,
    }
    arguments = {
        name: bindings[name]
        for name in properties
        if name in bindings and bindings[name] is not None
    }
    for name, property_schema in properties.items():
        if (
            name not in arguments
            and isinstance(property_schema, dict)
            and "default" in property_schema
        ):
            arguments[name] = property_schema["default"]
    return None if required - set(arguments) else arguments


def _verified_dry_run_evidence(
    evidence: ConnectorEvidence,
    *,
    candidate_hash: str,
    asset_id: str,
    environment: str,
) -> bool:
    payload = dict(evidence.payload or {})
    raw_verification = payload.get("verification")
    verification = dict(raw_verification) if isinstance(raw_verification, dict) else payload
    status = str(
        verification.get("status") or verification.get("verification_status") or ""
    ).lower()
    verified_asset = str(verification.get("asset_id") or evidence.asset_id or "")
    return bool(
        status in {"pass", "passed"}
        and str(verification.get("candidate_hash") or "") == candidate_hash
        and verified_asset == asset_id
        and evidence.environment == environment
    )


class ConfigAgent(BaseAgent):
    """仅验证候选或已记录快照，不发布配置、不修改配置中心。"""

    def __init__(self) -> None:
        super().__init__("config")

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
                error="trusted_config_scope_required",
            )

        evidence: list[dict[str, Any]] = []
        gaps: list[str] = []
        report_payload: dict[str, Any] = {}
        run_id: str | None = None
        selected_asset: ProductionAsset | None = None
        candidate_source = "recorded_snapshot"
        async with AsyncSessionLocal() as db:
            await set_session_scope(db, tenant_id=tenant_id, workspace_id=workspace_id)
            user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
            if user is None:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="config_user_not_authorized",
                )
            rows = await db.execute(
                select(ProductionAsset).where(
                    ProductionAsset.tenant_id == tenant_id,
                    ProductionAsset.workspace_id == workspace_id,
                    ProductionAsset.asset_type == "config",
                    ProductionAsset.status == "active",
                )
            )
            assets = list(rows.scalars().all())
            ranked = sorted(
                ((item, _asset_score(item, task.query)) for item in assets),
                key=lambda pair: (-pair[1], pair[0].name),
            )
            selected_asset = next((item for item, score in ranked if score > 0), None)
            if selected_asset is None:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="success",
                    content="没有唯一定位到待校验的配置资产，未执行校验。",
                    confidence=0.0,
                    metadata={
                        "mode": "governed_config_validation",
                        "read_only": True,
                        "needs_clarification": len(assets) > 1,
                        "candidates": [asset_to_dict(item) for item, _score in ranked[:10]],
                        "gaps": ["config_asset_selection_required"],
                    },
                )

            scope = ProductionScope(tenant_id, workspace_id, user_id)
            service = ConfigIntelligenceService(db, scope)
            policy = await service.latest_policy(selected_asset.id)
            if policy is None:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="success",
                    content="配置资产尚未发布确定性校验策略，不能执行可靠验证。",
                    confidence=0.0,
                    metadata={
                        "mode": "governed_config_validation",
                        "read_only": True,
                        "asset": asset_to_dict(selected_asset),
                        "gaps": ["published_config_policy_required"],
                    },
                )
            environment = selected_asset.environment or "shared"
            snapshots = await service.snapshots(selected_asset.id, environment=environment)
            proposed = task.params.get("candidate_config")
            if isinstance(proposed, dict):
                candidate = dict(proposed)
                candidate_source = "proposed_candidate"
            elif snapshots:
                candidate = dict(snapshots[0].content or {})
            else:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="success",
                    content="没有可校验的配置快照或候选配置。",
                    confidence=0.0,
                    metadata={
                        "mode": "governed_config_validation",
                        "read_only": True,
                        "asset": asset_to_dict(selected_asset),
                        "policy_id": policy.id,
                        "gaps": ["config_snapshot_or_candidate_required"],
                    },
                )
            candidate_hash = canonical_hash(candidate)

            asset_observed_at = _asset_observed_at(selected_asset)
            if asset_observed_at is None:
                gaps.append("配置资产缺少可核验的目录观测时间")
            else:
                evidence.append(
                    {
                        "evidence_type": "asset",
                        "source_kind": "asset_graph",
                        "source_ref": f"production-asset://{selected_asset.id}",
                        "asset_id": selected_asset.id,
                        "title": f"配置资产：{selected_asset.name}",
                        "summary": selected_asset.description or selected_asset.external_key,
                        "environment": environment,
                        "authority": "governed_asset_catalog",
                        "confidence": 0.9,
                        "observed_at": asset_observed_at.isoformat(),
                        "requirements": ["asset_context"],
                    }
                )
            if snapshots:
                snapshot_observed_at = snapshots[0].observed_at
                evidence.append(
                    {
                        "evidence_type": "config_snapshot",
                        "source_kind": "config_catalog",
                        "source_ref": snapshots[0].source_ref,
                        "asset_id": selected_asset.id,
                        "title": f"配置快照 {snapshots[0].version_ref}",
                        "summary": f"{environment} 环境的 {snapshots[0].status} 快照",
                        "environment": environment,
                        "authority": "governed_config_snapshot",
                        "confidence": 0.95,
                        "observed_at": snapshot_observed_at.isoformat(),
                        "payload": {"content_hash": snapshots[0].content_hash},
                    }
                )

            dry_run: dict[str, Any] = {}
            if policy.dry_run_operation:
                connector_id = selected_asset.connector_id
                connector = None
                if connector_id:
                    from infra.storage.models import EnterpriseConnector

                    connector = await db.scalar(
                        select(EnterpriseConnector).where(
                            EnterpriseConnector.id == connector_id,
                            EnterpriseConnector.tenant_id == tenant_id,
                            EnterpriseConnector.workspace_id == workspace_id,
                            EnterpriseConnector.status == "enabled",
                        )
                    )
                spec = (
                    _operation_spec(connector, policy.dry_run_operation)
                    if connector is not None
                    else None
                )
                arguments = (
                    _dry_run_arguments(
                        spec.input_schema,
                        candidate=candidate,
                        asset=selected_asset,
                        environment=environment,
                        query=task.query,
                    )
                    if spec is not None and spec.risk == "read" and spec.evidence_types
                    else None
                )
                if connector is None or spec is None or arguments is None:
                    dry_run = {"status": "failed", "reason": "config_dry_run_not_available"}
                else:
                    try:
                        result = await GovernedConnectorGateway().execute(
                            db,
                            connector_id=connector.id,
                            operation=policy.dry_run_operation,
                            arguments=arguments,
                            context=ConnectorExecutionContext(
                                tenant_id=tenant_id,
                                workspace_id=workspace_id,
                                user_id=user_id,
                                response_id=response_id,
                                role=str(user.role or "user"),
                                is_superuser=bool(user.is_superuser),
                                environment=environment,
                                trace_id=task.task_id,
                            ),
                        )
                        verified_dry_run_count = sum(
                            _verified_dry_run_evidence(
                                item,
                                candidate_hash=candidate_hash,
                                asset_id=selected_asset.id,
                                environment=environment,
                            )
                            for item in result.evidence
                        )
                        dry_run = {
                            "status": "passed" if verified_dry_run_count else "failed",
                            "operation": policy.dry_run_operation,
                            "candidate_hash": candidate_hash,
                            "verified_evidence_count": verified_dry_run_count,
                            "result": _bounded_projection(
                                dict(result.data or {}), max_bytes=32_768
                            ),
                        }
                        if not verified_dry_run_count:
                            gaps.append("dry-run 未返回与候选哈希、配置资产和环境一致的通过证据")
                        for item in result.evidence:
                            verified = _verified_dry_run_evidence(
                                item,
                                candidate_hash=candidate_hash,
                                asset_id=selected_asset.id,
                                environment=environment,
                            )
                            evidence.append(
                                {
                                    "evidence_type": (
                                        "config_dry_run" if verified else item.evidence_type
                                    ),
                                    "source_kind": item.source_kind,
                                    "source_ref": item.source_ref,
                                    "connector_id": connector.id,
                                    "asset_id": item.asset_id or selected_asset.id,
                                    "title": item.title,
                                    "summary": item.summary,
                                    "environment": item.environment or environment,
                                    "authority": item.authority,
                                    "confidence": item.confidence,
                                    "observed_at": item.observed_at.isoformat(),
                                    "payload": _bounded_projection(
                                        {
                                            **dict(item.payload or {}),
                                            "verification_status": (
                                                "passed" if verified else "failed"
                                            ),
                                            "candidate_hash": candidate_hash,
                                        },
                                        max_bytes=8_192,
                                    ),
                                    "requirements": ["config_dry_run"] if verified else [],
                                }
                            )
                    except ConnectorGatewayError as exc:
                        dry_run = {"status": "failed", "reason": str(exc)}
                        gaps.append(f"dry-run：{exc}")
            try:
                run, report = await service.validate_and_record(
                    asset_id=selected_asset.id,
                    candidate=candidate,
                    response_id=response_id,
                    environment=environment,
                    dry_run=dry_run,
                )
            except ConfigIntelligenceError as exc:
                await db.rollback()
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error=str(exc),
                )
            run_id = run.id
            report_payload = report.to_dict()
            evidence.append(
                {
                    "evidence_type": "config_validation",
                    "source_kind": "config_validator",
                    "source_ref": f"config-validation://{run.id}",
                    "asset_id": selected_asset.id,
                    "title": f"配置校验 {report.status}",
                    "summary": (
                        f"共 {report.summary['total']} 项检查，"
                        f"{report.summary['errors']} 项错误，"
                        f"{report.summary['warnings']} 项警告"
                    ),
                    "environment": environment,
                    "authority": "deterministic_policy_engine",
                    "confidence": report.summary["confidence"],
                    "observed_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "validation_run_id": run.id,
                        "policy_id": policy.id,
                        "policy_version": policy.version,
                        "candidate_hash": run.candidate_hash,
                        "candidate_source": candidate_source,
                        "status": report.status,
                        "risk_level": report.risk_level,
                    },
                    "requirements": [
                        "config_validation",
                        "config_schema",
                        "config_references",
                        "config_business_rules",
                        "config_history",
                        "config_capacity",
                        "config_conflicts",
                    ],
                }
            )
            await db.commit()

        required = {"asset_context", "config_validation"}
        if policy.dry_run_operation:
            required.add("config_dry_run")
        critic = ProductionEvidenceCritic().assess(
            evidence,
            required=required,
            expected_environment=selected_asset.environment if selected_asset else None,
        )
        gaps.extend(critic.gaps)
        validation_status = str(report_payload.get("status") or "unknown")
        conclusion = (
            f"配置校验结果为 {validation_status}，风险级别 "
            f"{report_payload.get('risk_level') or 'unknown'}。"
        )
        content = render_evidence_answer(
            conclusion=conclusion,
            evidence=evidence,
            critic=critic,
            impact="本次只验证候选或快照，未向配置中心写入、发布或回滚配置。",
            recommendation=(
                "先处理所有 error 和未通过的 dry-run，再通过独立写操作提交审批。"
                if validation_status != "pass"
                else "校验通过后仍需通过 Responses 持久审批发起配置写入，并保留回滚版本。"
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
                "mode": "governed_config_validation",
                "read_only": True,
                "asset": asset_to_dict(selected_asset) if selected_asset else None,
                "validation_run_id": run_id,
                "candidate_source": candidate_source,
                "report": report_payload,
                "critic": critic.to_dict(),
                "gaps": list(dict.fromkeys(gaps)),
            },
        )
