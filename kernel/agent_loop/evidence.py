"""Response 级受治理证据账本与确定性答案门禁。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from kernel.agent_loop.contracts import (
    DataIntentStage,
    EvidenceRequirement,
    InformationSource,
    IntentPlan,
)

_REQUIREMENT_SOURCE = {
    EvidenceRequirement.PERSONAL_CONTEXT: InformationSource.PERSONAL_MEMORY,
    EvidenceRequirement.ENTERPRISE_CONTEXT: InformationSource.COMPANY_BRAIN,
    EvidenceRequirement.COMPANY_SKILL_CONTEXT: InformationSource.COMPANY_SKILL,
    EvidenceRequirement.PUBLISHED_CITATIONS: InformationSource.RAG,
    EvidenceRequirement.METRIC_DEFINITION: InformationSource.DATA,
    EvidenceRequirement.TRUSTED_DATA_SOURCE: InformationSource.DATA,
    EvidenceRequirement.BUSINESS_RULES: InformationSource.DATA,
    EvidenceRequirement.VALIDATED_SQL: InformationSource.DATA,
    EvidenceRequirement.EXECUTED_RESULT: InformationSource.DATA,
    EvidenceRequirement.ASSET_CONTEXT: InformationSource.PRODUCTION,
    EvidenceRequirement.LIVE_OBSERVATION: InformationSource.PRODUCTION,
    EvidenceRequirement.CROSS_SOURCE_CORROBORATION: InformationSource.PRODUCTION,
    EvidenceRequirement.CONFIG_VALIDATION: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_SCHEMA: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_REFERENCES: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_BUSINESS_RULES: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_HISTORY: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_CAPACITY: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_CONFLICTS: InformationSource.CONFIG,
    EvidenceRequirement.CONFIG_DRY_RUN: InformationSource.CONFIG,
}


@dataclass(slots=True)
class EvidenceLedgerEntry:
    source: InformationSource
    evidence_id: str
    evidence_type: str
    title: str
    authority: str
    version: str | None = None
    citation: str | None = None
    requirements: set[EvidenceRequirement] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "title": self.title,
            "authority": self.authority,
            "version": self.version,
            "citation": self.citation,
            "requirements": sorted(item.value for item in self.requirements),
            "metadata": dict(self.metadata),
        }


class ResponseEvidenceLedger:
    """聚合上下文与工具证据，并在最终回答前执行不可绕过的完整性判断。"""

    schema_version = "response_evidence_ledger.v1"

    def __init__(self, intent: IntentPlan) -> None:
        self.intent = intent
        self.entries: dict[str, EvidenceLedgerEntry] = {}
        self.failures: list[dict[str, Any]] = []
        self.gate: dict[str, Any] = {}
        self.satisfied_overrides: set[EvidenceRequirement] = set()

    @classmethod
    def from_context(
        cls,
        intent: IntentPlan,
        *,
        context_manifest: dict[str, Any],
        memory_ids: list[str],
    ) -> ResponseEvidenceLedger:
        ledger = cls(intent)
        if memory_ids:
            ledger.add(
                EvidenceLedgerEntry(
                    source=InformationSource.PERSONAL_MEMORY,
                    evidence_id=f"personal-memory:{len(memory_ids)}",
                    evidence_type="personal_memory_recall",
                    title="当前用户范围内的已确认个人记忆",
                    authority="user_confirmed",
                    citation="memory://current-scope",
                    requirements={EvidenceRequirement.PERSONAL_CONTEXT},
                    metadata={"memory_ids": list(memory_ids), "count": len(memory_ids)},
                )
            )

        company_brain = dict(context_manifest.get("company_brain") or {})
        if company_brain.get("answer_context_available"):
            version = company_brain.get("version")
            ledger.add(
                EvidenceLedgerEntry(
                    source=InformationSource.COMPANY_BRAIN,
                    evidence_id=f"company-brain:{company_brain.get('company_id') or 'primary'}:{version}",
                    evidence_type="company_brain_recall",
                    title=str(company_brain.get("brand_name") or "企业大脑已发布内容"),
                    authority="enterprise_published",
                    version=str(version) if version is not None else None,
                    citation=(
                        f"company-brain://version/{version}" if version is not None else None
                    ),
                    requirements={EvidenceRequirement.ENTERPRISE_CONTEXT},
                    metadata={
                        "entry_count": int(company_brain.get("entry_count") or 0),
                        "top_score": float(company_brain.get("top_score") or 0.0),
                        "match_strategy": company_brain.get("match_strategy"),
                    },
                )
            )

        company_skills = dict(context_manifest.get("company_skills") or {})
        for skill in company_skills.get("skills") or []:
            if not isinstance(skill, dict):
                continue
            skill_id = str(skill.get("id") or "").strip()
            source_digest = str(skill.get("source_digest") or "").strip()
            if not skill_id or not source_digest:
                continue
            ledger.add(
                EvidenceLedgerEntry(
                    source=InformationSource.COMPANY_SKILL,
                    evidence_id=f"company-skill:{skill_id}:{source_digest}",
                    evidence_type="company_uploaded_distilled_skill",
                    title=str(skill.get("name") or skill_id),
                    authority="enterprise_published",
                    version=str(skill.get("version") or "") or None,
                    citation=f"company-skill://{skill_id}@{source_digest[:12]}",
                    requirements={EvidenceRequirement.COMPANY_SKILL_CONTEXT},
                    metadata={
                        "runtime_id": skill.get("runtime_id"),
                        "classification": skill.get("classification"),
                        "top_score": float(skill.get("top_score") or 0.0),
                        "matched_paths": list(skill.get("matched_paths") or []),
                    },
                )
            )

        enterprise = dict(context_manifest.get("enterprise_context") or {})
        for entity in enterprise.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("entity_id") or "").strip()
            version_id = str(entity.get("version_id") or "").strip()
            if not entity_id or not version_id:
                continue
            ledger.add(
                EvidenceLedgerEntry(
                    source=InformationSource.COMPANY_BRAIN,
                    evidence_id=f"enterprise-context:{entity_id}:{version_id}",
                    evidence_type="enterprise_cognitive_entity",
                    title=str(entity.get("entity_key") or entity_id),
                    authority="enterprise_published",
                    version=str(entity.get("version") or "") or None,
                    citation=f"enterprise-context://version/{version_id}",
                    requirements={EvidenceRequirement.ENTERPRISE_CONTEXT},
                    metadata={
                        "classification": entity.get("classification"),
                        "knowledge_space_id": entity.get("knowledge_space_id"),
                    },
                )
            )
        return ledger

    def add(self, entry: EvidenceLedgerEntry) -> None:
        existing = self.entries.get(entry.evidence_id)
        if existing is None:
            self.entries[entry.evidence_id] = entry
            return
        existing.requirements.update(entry.requirements)
        existing.metadata.update(entry.metadata)

    @staticmethod
    def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
        nested = result.get("result")
        return nested if isinstance(nested, dict) else result

    def observe_tool(self, tool_name: str, result: dict[str, Any]) -> None:
        payload = self._tool_payload(result)
        status = str(payload.get("status") or result.get("status") or "").lower()
        if status in {"error", "failed", "rejected", "timeout", "incomplete"}:
            self.failures.append(
                {
                    "source": tool_name,
                    "status": status,
                    "reason": "governed_source_unavailable",
                }
            )
            return
        if tool_name == "rag":
            self._observe_rag(payload)
        elif tool_name == "data":
            self._observe_data_draft(payload)
        elif tool_name == "execute_sql_draft":
            self._observe_data_execution(payload)
        elif tool_name in {"production", "config"}:
            self._observe_production_intelligence(tool_name, payload)

    def _observe_production_intelligence(self, tool_name: str, payload: dict[str, Any]) -> None:
        source = InformationSource.CONFIG if tool_name == "config" else InformationSource.PRODUCTION
        metadata = dict(payload.get("metadata") or {})
        critic = dict(metadata.get("critic") or {})
        critic_passed = critic.get("status") == "pass"
        if critic_passed:
            for raw_requirement in critic.get("requirements_satisfied") or []:
                try:
                    self.satisfied_overrides.add(EvidenceRequirement(str(raw_requirement)))
                except ValueError:
                    continue
        elif critic.get("status") in {"blocked", "incomplete"}:
            self.failures.append(
                {
                    "source": tool_name,
                    "status": "evidence_critic_blocked",
                    "reason": f"production_evidence_{critic.get('status')}",
                    "gaps": list(critic.get("gaps") or []),
                    "conflicts": list(critic.get("conflicts") or []),
                }
            )

        raw_evidence = payload.get("evidence") or []
        for index, raw in enumerate(raw_evidence[:100], start=1):
            if not isinstance(raw, dict):
                continue
            evidence_type = str(raw.get("evidence_type") or "").strip()
            source_ref = str(raw.get("source_ref") or "").strip()
            if not evidence_type or not source_ref:
                continue
            requirements: set[EvidenceRequirement] = set()
            if critic_passed:
                for value in raw.get("requirements") or []:
                    try:
                        requirements.add(EvidenceRequirement(str(value)))
                    except ValueError:
                        continue
                if evidence_type in {"asset", "asset_graph", "ownership", "dependency"}:
                    requirements.add(EvidenceRequirement.ASSET_CONTEXT)
                if (
                    evidence_type
                    in {
                        "metric",
                        "log",
                        "trace",
                        "alert",
                        "deployment",
                        "business_record",
                        "config_snapshot",
                        "code_change",
                    }
                    and source == InformationSource.PRODUCTION
                ):
                    requirements.add(EvidenceRequirement.LIVE_OBSERVATION)
                if evidence_type == "config_validation":
                    requirements.add(EvidenceRequirement.CONFIG_VALIDATION)
                if evidence_type == "config_dry_run":
                    requirements.add(EvidenceRequirement.CONFIG_DRY_RUN)
            payload_metadata = dict(raw.get("payload") or {})
            evidence_id = str(raw.get("evidence_id") or source_ref or f"{tool_name}:{index}")
            self.add(
                EvidenceLedgerEntry(
                    source=source,
                    evidence_id=evidence_id,
                    evidence_type=evidence_type,
                    title=str(raw.get("title") or f"{tool_name} 证据 {index}"),
                    authority=str(raw.get("authority") or "governed_production_source"),
                    version=(
                        str(payload_metadata.get("policy_version"))
                        if payload_metadata.get("policy_version") is not None
                        else None
                    ),
                    citation=source_ref,
                    requirements=requirements,
                    metadata={
                        "source_kind": raw.get("source_kind"),
                        "connector_id": raw.get("connector_id"),
                        "asset_id": raw.get("asset_id"),
                        "environment": raw.get("environment"),
                        "observed_at": raw.get("observed_at"),
                        "confidence": raw.get("confidence"),
                        "critic_status": critic.get("status"),
                    },
                )
            )

    def _observe_rag(self, payload: dict[str, Any]) -> None:
        metadata = dict(payload.get("metadata") or {})
        quality = dict(metadata.get("quality") or {})
        chunks = list(metadata.get("chunks") or [])
        citations = list(metadata.get("citations") or payload.get("citations") or [])
        if quality.get("answerable") is False:
            self.failures.append(
                {
                    "source": "rag",
                    "status": "insufficient_evidence",
                    "error": str(quality.get("answerability_state") or "not_answerable"),
                }
            )
            return
        if not chunks and not citations and not quality.get("answerable"):
            return
        for index, raw in enumerate(citations or chunks[:12], start=1):
            item = raw if isinstance(raw, dict) else {"title": str(raw)}
            evidence_id = str(
                item.get("evidence_id") or item.get("chunk_id") or item.get("id") or f"rag:{index}"
            )
            self.add(
                EvidenceLedgerEntry(
                    source=InformationSource.RAG,
                    evidence_id=evidence_id,
                    evidence_type="published_retrieval",
                    title=str(
                        item.get("title")
                        or item.get("document_name")
                        or item.get("source")
                        or f"知识证据 {index}"
                    ),
                    authority=str(item.get("authority") or "access_controlled_document"),
                    version=str(item.get("version") or "") or None,
                    citation=str(item.get("citation") or item.get("url") or "") or None,
                    requirements={EvidenceRequirement.PUBLISHED_CITATIONS},
                    metadata={
                        "score": item.get("score") or item.get("relevance_score"),
                        "source_type": item.get("source_type"),
                    },
                )
            )

    def _observe_data_draft(self, payload: dict[str, Any]) -> None:
        metadata = dict(payload.get("metadata") or {})
        draft = dict(metadata.get("draft") or {})
        draft_id = str(metadata.get("draft_id") or draft.get("id") or "").strip()
        data_agent_run_id = str(
            metadata.get("data_agent_run_id") or draft.get("data_agent_run_id") or ""
        ).strip()
        query_plan = dict(metadata.get("query_plan") or draft.get("query_plan") or {})
        source_decision = dict(
            metadata.get("source_decision") or draft.get("source_decision") or {}
        )
        candidates = list(metadata.get("candidates") or draft.get("candidates") or [])
        requirements: set[EvidenceRequirement] = set()
        if query_plan.get("metric_contracts") or query_plan.get("metrics"):
            requirements.add(EvidenceRequirement.METRIC_DEFINITION)
        if source_decision or draft.get("data_source_id"):
            requirements.add(EvidenceRequirement.TRUSTED_DATA_SOURCE)
        if (
            query_plan.get("filters")
            or query_plan.get("business_rules")
            or query_plan.get("metric_contracts")
        ):
            requirements.add(EvidenceRequirement.BUSINESS_RULES)
        if any(
            isinstance(item, dict)
            and item.get("sql")
            and not dict(item.get("validation_report") or {}).get("errors")
            for item in candidates
        ):
            requirements.add(EvidenceRequirement.VALIDATED_SQL)
        if not draft_id:
            return
        self.add(
            EvidenceLedgerEntry(
                source=InformationSource.DATA,
                evidence_id=f"data-draft:{draft_id}",
                evidence_type="governed_sql_draft",
                title="DataAgent 受治理 SQL 草案",
                authority="governed_data_asset",
                citation=f"data-agent://draft/{draft_id}",
                requirements=requirements,
                metadata={
                    "draft_id": draft_id,
                    "data_agent_run_id": data_agent_run_id or None,
                    "candidate_count": len(candidates),
                    "executed": False,
                    "source_decision": source_decision,
                },
            )
        )

    def _observe_data_execution(self, payload: dict[str, Any]) -> None:
        summary = dict(payload.get("execution_summary") or {})
        if not summary:
            return
        run_id = str(summary.get("data_agent_run_id") or "").strip()
        state = str(summary.get("state") or "")
        validation = dict(summary.get("result_validation") or {})
        answer_metadata = dict(summary.get("answer_metadata") or {})
        citations = list(summary.get("answer_citations") or [])
        snapshot_id = str(answer_metadata.get("snapshot_id") or "").strip()
        passed = state == "completed" and validation.get("status") in {"pass", "warn"}
        requirements: set[EvidenceRequirement] = set()
        metrics = [item for item in answer_metadata.get("metrics") or [] if isinstance(item, dict)]
        coverage = dict(answer_metadata.get("evidence_requirements") or {})
        citation_types = {
            str(item.get("evidence_type") or "") for item in citations if isinstance(item, dict)
        }
        source = dict(answer_metadata.get("data_source") or {})
        source_decision = dict(source.get("decision") or {})
        sql_validation = dict(answer_metadata.get("sql_validation") or {})
        has_governance_coverage = bool(coverage)
        if coverage.get("metric_definition") or (
            not has_governance_coverage
            and metrics
            and all(item.get("evidence_id") for item in metrics)
        ):
            requirements.add(EvidenceRequirement.METRIC_DEFINITION)
        if coverage.get("trusted_data_source") or (
            not has_governance_coverage
            and source.get("id")
            and (not source_decision or source_decision.get("status") == "selected")
        ):
            requirements.add(EvidenceRequirement.TRUSTED_DATA_SOURCE)
        if coverage.get("business_rules") or (
            not has_governance_coverage
            and (
                citation_types.intersection({"business_rule", "policy", "source_policy"})
                or any(item.get("required_filters") for item in metrics)
            )
        ):
            requirements.add(EvidenceRequirement.BUSINESS_RULES)
        if coverage.get("validated_sql") or (
            not has_governance_coverage
            and answer_metadata.get("sql")
            and not [
                item
                for item in sql_validation.get("issues") or []
                if isinstance(item, dict) and item.get("severity") == "error"
            ]
        ):
            requirements.add(EvidenceRequirement.VALIDATED_SQL)
        if passed and (
            coverage.get("executed_result")
            or (not has_governance_coverage and bool(snapshot_id or citations))
        ):
            requirements.add(EvidenceRequirement.EXECUTED_RESULT)
        evidence_id = snapshot_id or (f"execution-result:{run_id}" if run_id else "")
        if not evidence_id:
            return
        self.add(
            EvidenceLedgerEntry(
                source=InformationSource.DATA,
                evidence_id=evidence_id,
                evidence_type="verified_query_result",
                title="DataAgent 已执行并校验的查询结果",
                authority="executed_result",
                citation=(f"data-agent://snapshot/{snapshot_id}" if snapshot_id else None),
                requirements=requirements,
                metadata={
                    "data_agent_run_id": run_id,
                    "state": state,
                    "validation_status": validation.get("status"),
                    "snapshot_id": snapshot_id or None,
                    "citation_labels": [
                        item.get("label") for item in citations if isinstance(item, dict)
                    ],
                },
            )
        )

    def assessment(self) -> dict[str, Any]:
        required = list(dict.fromkeys(self.intent.evidence_requirements))
        satisfied = {
            requirement for entry in self.entries.values() for requirement in entry.requirements
        }
        satisfied.update(self.satisfied_overrides)
        missing = [item for item in required if item not in satisfied]
        blocking: list[EvidenceRequirement | str] = list(missing)
        critic_failures = [
            item for item in self.failures if item.get("status") == "evidence_critic_blocked"
        ]
        if critic_failures:
            blocking.append("evidence_critic_blocked")
        return {
            "status": "pass" if not blocking else "blocked",
            "required": [item.value for item in required],
            "satisfied": [item.value for item in required if item in satisfied],
            "missing": [item.value for item in missing],
            "blocking": [
                item.value if isinstance(item, EvidenceRequirement) else item for item in blocking
            ],
            "critic_failures": critic_failures,
        }

    def govern_answer(self, content: str) -> tuple[str, dict[str, Any]]:
        assessment = self.assessment()
        missing = set(assessment["missing"])
        if assessment.get("critic_failures"):
            gaps = [
                str(gap)
                for failure in assessment["critic_failures"]
                for gap in failure.get("gaps") or []
            ]
            governed = (
                "## 结论\n当前生产证据存在冲突、环境不一致或关键缺口，不能给出可靠结论。\n\n"
                "## 证据\n已取得的证据保留在本次 Response 证据账本中，但未通过 Critic。\n\n"
                "## 置信度\n低（证据门禁阻断）\n\n"
                "## 影响\n未执行任何生产或配置写入。\n\n"
                "## 建议\n补齐或核对：" + ("；".join(dict.fromkeys(gaps)) or "冲突证据")
            )
        elif not missing:
            governed = content
        elif missing.intersection(
            {
                EvidenceRequirement.ASSET_CONTEXT.value,
                EvidenceRequirement.LIVE_OBSERVATION.value,
                EvidenceRequirement.CROSS_SOURCE_CORROBORATION.value,
            }
        ):
            governed = (
                "## 结论\n当前没有足够的生产资产或实时观测证据，不能确认生产状态或根因。\n\n"
                "## 证据\n缺少：" + "、".join(sorted(missing)) + "。\n\n"
                "## 置信度\n低（证据门禁阻断）\n\n"
                "## 影响\n未执行任何生产写入。\n\n"
                "## 建议\n检查资产映射、Connector 权限、目标环境和证据时效后重试。"
            )
        elif missing.intersection(
            {
                EvidenceRequirement.CONFIG_VALIDATION.value,
                EvidenceRequirement.CONFIG_SCHEMA.value,
                EvidenceRequirement.CONFIG_REFERENCES.value,
                EvidenceRequirement.CONFIG_BUSINESS_RULES.value,
                EvidenceRequirement.CONFIG_HISTORY.value,
                EvidenceRequirement.CONFIG_CAPACITY.value,
                EvidenceRequirement.CONFIG_CONFLICTS.value,
                EvidenceRequirement.CONFIG_DRY_RUN.value,
            }
        ):
            governed = (
                "## 结论\n配置尚未通过完整的确定性验证，不能判断其可安全发布。\n\n"
                "## 证据\n缺少：" + "、".join(sorted(missing)) + "。\n\n"
                "## 置信度\n低（配置证据门禁阻断）\n\n"
                "## 影响\n未向配置中心写入或发布配置。\n\n"
                "## 建议\n发布配置策略、记录可信快照并完成 dry-run 后重新验证。"
            )
        elif EvidenceRequirement.EXECUTED_RESULT.value in missing:
            governed = (
                "当前没有取得经过实际执行和结果校验的数据证据，因此不能给出或确认业务数字。"
                "请先选择已生成的 SQL 草案候选并完成受治理只读执行；系统会在 Schema、语义、"
                "SQL、EXPLAIN 与结果校验全部通过后返回带证据答案。"
            )
        elif EvidenceRequirement.PUBLISHED_CITATIONS.value in missing:
            governed = (
                "当前没有检索到足以支持结论的已发布知识或文档证据，因此不能可靠回答该事实问题。"
                "请检查知识空间权限、资料是否已入库，或补充更明确的检索范围。"
            )
        elif EvidenceRequirement.ENTERPRISE_CONTEXT.value in missing:
            governed = (
                "当前企业大脑和已发布企业认知中没有找到足以支持结论的内容。"
                "我不会用通用常识补全公司制度、流程或业务口径；请补充或发布对应企业资料。"
            )
        elif EvidenceRequirement.COMPANY_SKILL_CONTEXT.value in missing:
            governed = (
                "当前没有命中能支持结论的已发布企业内 Skill。"
                "我不会用模型常识伪造企业流程、字段语义或业务规则；"
                "请由管理员上传并发布对应的企业 Skill。"
            )
        elif EvidenceRequirement.PERSONAL_CONTEXT.value in missing:
            governed = (
                "当前用户、租户和工作区范围内没有找到可确认的个人记忆证据。"
                "请补充相关信息，或先启用并确认个人记忆。"
            )
        elif self.intent.data_stage == DataIntentStage.EXECUTE_AND_VERIFY and missing.intersection(
            {
                EvidenceRequirement.METRIC_DEFINITION.value,
                EvidenceRequirement.TRUSTED_DATA_SOURCE.value,
                EvidenceRequirement.BUSINESS_RULES.value,
                EvidenceRequirement.VALIDATED_SQL.value,
            }
        ):
            labels = "、".join(sorted(missing))
            governed = (
                "本次查询虽然可能已经执行，但企业治理证据仍不完整，因此不能把结果作为可靠的"
                f"业务结论。缺少：{labels}。请先补齐或发布对应指标口径、业务规则、可信数据源"
                "或 SQL 校验证据，再重新生成并执行。"
            )
        elif self.intent.data_stage == DataIntentStage.RESEARCH_AND_DRAFT:
            governed = content
            assessment["status"] = "incomplete"
            assessment["blocking"] = []
        else:
            governed = content
            assessment["status"] = "incomplete"
            assessment["blocking"] = []
        assessment["answer_replaced"] = governed != content
        assessment["evaluated_at"] = datetime.now(UTC).isoformat()
        self.gate = assessment
        return governed, assessment

    def to_dict(self) -> dict[str, Any]:
        assessment = self.gate or self.assessment()
        counts = {source.value: 0 for source in InformationSource}
        for entry in self.entries.values():
            counts[entry.source.value] += 1
        return {
            "schema_version": self.schema_version,
            "sources": [source.value for source in self.intent.information_sources],
            "source_counts": counts,
            "entries": [entry.to_dict() for entry in self.entries.values()],
            "failures": list(self.failures),
            "gate": dict(assessment),
        }
