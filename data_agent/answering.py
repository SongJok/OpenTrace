"""构造答案所需的最小证据集和机器可读说明。"""

from __future__ import annotations

import json
from typing import Any

from data_agent.contracts import AnswerCitation, CandidateSQL, EvidenceItem, EvidenceType, QueryRun


def _title(item: EvidenceItem) -> str:
    payload = item.payload
    return str(
        payload.get("name")
        or payload.get("title")
        or payload.get("business_name")
        or payload.get("asset_key")
        or payload.get("table")
        or item.source_name
        or item.source_id
    )


def _excerpt(item: EvidenceItem) -> str:
    payload = item.payload
    safe_keys = (
        "business_definition",
        "description",
        "formula",
        "aggregation",
        "required_filters",
        "time_field",
        "grain",
        "owner",
        "business_domain",
        "left_table",
        "left_column",
        "right_table",
        "right_column",
        "join_type",
        "verified",
        "question",
    )
    safe_payload = {
        key: payload.get(key) for key in safe_keys if payload.get(key) not in (None, "", [])
    }
    return json.dumps(safe_payload, ensure_ascii=False, default=str)[:1200]


class AnswerEvidenceBuilder:
    _priority = {
        EvidenceType.METRIC: 0,
        EvidenceType.BUSINESS_RULE: 1,
        EvidenceType.POLICY: 2,
        EvidenceType.RELATIONSHIP: 3,
        EvidenceType.LINEAGE: 4,
        EvidenceType.REPORT: 5,
        EvidenceType.DATA_QUALITY: 6,
        EvidenceType.SQL_ASSET: 7,
        EvidenceType.SOURCE_POLICY: 8,
        EvidenceType.EXECUTION_MEMORY: 9,
    }

    def build(
        self,
        run: QueryRun,
        candidate: CandidateSQL,
    ) -> tuple[list[AnswerCitation], dict[str, Any]]:
        if run.logical_plan is None or run.evidence is None or run.result is None:
            return [], {}
        plan = run.logical_plan
        evidence = run.evidence
        desired_ids = list(plan.evidence_ids)
        if run.request.source_decision and run.request.source_decision.candidates:
            selected = next(
                (
                    item
                    for item in run.request.source_decision.candidates
                    if item.data_source_id == run.request.scope.data_source_id
                ),
                None,
            )
            if selected is not None:
                desired_ids.extend(selected.evidence_ids)

        indexed = {item.source_id: item for item in evidence.items}
        selected_items = [indexed[item_id] for item_id in desired_ids if item_id in indexed]
        if not selected_items:
            selected_items = [
                item
                for item in evidence.items
                if item.type in self._priority
                and item.authority.value in {"live_system", "governed", "verified"}
            ]
        selected_items = sorted(
            {item.source_id: item for item in selected_items}.values(),
            key=lambda item: (
                self._priority.get(item.type, 99),
                -(item.authority.weight * item.confidence),
                item.source_id,
            ),
        )[:12]
        covered_plan_ids = {item_id for item_id in plan.evidence_ids if item_id in indexed}
        governed_metric_ids = {
            item.source_id
            for item in evidence.items
            if item.type == EvidenceType.METRIC and item.authority.value in {"governed", "verified"}
        }
        source_decision = run.request.source_decision
        trusted_source_selected = bool(
            source_decision
            and source_decision.status == "selected"
            and source_decision.selected_data_source_id == run.request.scope.data_source_id
        )

        result_citation = AnswerCitation(
            label="R1",
            evidence_id=run.result.snapshot_id or f"execution-result:{run.id}",
            evidence_type="execution_result",
            title="本次数据库只读执行结果",
            authority="live_system",
            version=evidence.schema_fingerprint,
            citation=run.result.snapshot_id or run.id,
            reason="答案中的数值必须来自本次经过预检和结果验证的真实执行",
            excerpt=json.dumps(
                {
                    "returned_rows": run.result.returned_rows,
                    "total_rows": run.result.total_rows,
                    "truncated": run.result.truncated,
                    "duration_ms": run.result.duration_ms,
                },
                ensure_ascii=False,
            ),
        )
        citations = [result_citation]
        for index, item in enumerate(selected_items, start=1):
            citations.append(
                AnswerCitation(
                    label=f"E{index}",
                    evidence_id=item.source_id,
                    evidence_type=item.type.value,
                    title=_title(item),
                    authority=item.authority.value,
                    version=item.version,
                    citation=item.citation,
                    reason="用于证明指标、规则、关系或数据来源选择",
                    excerpt=_excerpt(item),
                )
            )

        metadata: dict[str, Any] = {
            "data_source": {
                "id": run.request.scope.data_source_id,
                "name": (
                    run.request.source_decision.selected_data_source_name
                    if run.request.source_decision
                    else None
                ),
                "decision": (
                    run.request.source_decision.model_dump(mode="json")
                    if run.request.source_decision
                    else None
                ),
            },
            "metrics": [
                {
                    "name": metric.name,
                    "version": metric.version,
                    "owner": metric.owner,
                    "formula": metric.formula,
                    "required_filters": metric.required_filters,
                    "time_field": metric.time_field,
                    "evidence_id": metric.source_evidence_id,
                }
                for metric in plan.metrics
            ],
            "business_scenario": plan.business_scenario,
            "grain": plan.grain,
            "time_window": plan.time_window,
            "comparison": plan.comparison,
            "sql": candidate.sql,
            "sql_validation": candidate.validation.model_dump(mode="json"),
            "preflight": run.preflight.model_dump(mode="json") if run.preflight else {},
            "result_validation": (
                run.result_validation.model_dump(mode="json") if run.result_validation else {}
            ),
            "schema_fingerprint": evidence.schema_fingerprint,
            "semantic_version": evidence.semantic_version,
            "snapshot_id": run.result.snapshot_id,
            "citation_count": len(citations),
            "evidence_coverage": len(covered_plan_ids) / max(1, len(set(plan.evidence_ids))),
            "evidence_requirements": {
                "metric_definition": bool(plan.metrics)
                and all(
                    metric.source_evidence_id in governed_metric_ids for metric in plan.metrics
                ),
                "trusted_data_source": bool(evidence.schema_fingerprint)
                and bool(evidence.of_type(EvidenceType.SCHEMA))
                and trusted_source_selected,
                "business_rules": any(metric.required_filters for metric in plan.metrics)
                or any(
                    item.type
                    in {
                        EvidenceType.METRIC,
                        EvidenceType.BUSINESS_RULE,
                        EvidenceType.POLICY,
                        EvidenceType.SOURCE_POLICY,
                    }
                    and item.authority.value in {"governed", "verified"}
                    for item in selected_items
                ),
                "validated_sql": not candidate.validation.errors,
                "executed_result": bool(run.result.snapshot_id),
            },
        }
        return citations, metadata
