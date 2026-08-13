"""Response 级四源证据账本与确定性答案门禁。"""

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
    EvidenceRequirement.PUBLISHED_CITATIONS: InformationSource.RAG,
    EvidenceRequirement.METRIC_DEFINITION: InformationSource.DATA,
    EvidenceRequirement.TRUSTED_DATA_SOURCE: InformationSource.DATA,
    EvidenceRequirement.BUSINESS_RULES: InformationSource.DATA,
    EvidenceRequirement.VALIDATED_SQL: InformationSource.DATA,
    EvidenceRequirement.EXECUTED_RESULT: InformationSource.DATA,
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
                    "error": str(payload.get("error") or result.get("error") or "")[:500],
                }
            )
            return
        if tool_name == "rag":
            self._observe_rag(payload)
        elif tool_name == "data":
            self._observe_data_draft(payload)
        elif tool_name == "execute_sql_draft":
            self._observe_data_execution(payload)

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
        requirements = {
            EvidenceRequirement.METRIC_DEFINITION,
            EvidenceRequirement.TRUSTED_DATA_SOURCE,
            EvidenceRequirement.BUSINESS_RULES,
            EvidenceRequirement.VALIDATED_SQL,
        }
        if passed:
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
        missing = [item for item in required if item not in satisfied]
        blocking = list(missing)
        return {
            "status": "pass" if not missing else "blocked",
            "required": [item.value for item in required],
            "satisfied": [item.value for item in required if item in satisfied],
            "missing": [item.value for item in missing],
            "blocking": [item.value for item in blocking],
        }

    def govern_answer(self, content: str) -> tuple[str, dict[str, Any]]:
        assessment = self.assessment()
        missing = set(assessment["missing"])
        if not missing:
            governed = content
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
        elif EvidenceRequirement.PERSONAL_CONTEXT.value in missing:
            governed = (
                "当前用户、租户和工作区范围内没有找到可确认的个人记忆证据。"
                "请补充相关信息，或先启用并确认个人记忆。"
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
