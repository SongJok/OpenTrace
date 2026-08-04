"""数据洞察、月报与经营简报的模板、提示词和证据产物投影。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import ResponseRecord, ResponseToolExecution, TaskDefinition
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator

ReportType = Literal["data_insight", "monthly_report", "management_brief"]
REPORT_TASK_TYPE = "enterprise_report"


@dataclass(frozen=True, slots=True)
class EnterpriseReportTemplate:
    id: ReportType
    title: str
    description: str
    default_objective: str
    default_rrule: str
    sections: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    knowledge_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "default_objective": self.default_objective,
            "default_rrule": self.default_rrule,
            "sections": list(self.sections),
            "evidence_requirements": list(self.evidence_requirements),
            "knowledge_required": self.knowledge_required,
        }


REPORT_TEMPLATES: dict[ReportType, EnterpriseReportTemplate] = {
    "data_insight": EnterpriseReportTemplate(
        id="data_insight",
        title="数据洞察",
        description="围绕一个经营问题完成指标拆解、异常定位和行动建议。",
        default_objective="分析核心经营指标的变化、异常原因、风险与下一步行动。",
        default_rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
        sections=("结论摘要", "指标与变化", "异常归因", "风险", "行动建议"),
        evidence_requirements=("只读 SQL", "指标口径", "结果校验", "可视化配置"),
        knowledge_required=False,
    ),
    "monthly_report": EnterpriseReportTemplate(
        id="monthly_report",
        title="经营月报",
        description="按月沉淀经营结果、同比环比、目标差距和下月动作。",
        default_objective="复盘上月经营结果，对比目标与历史同期，并形成下月行动计划。",
        default_rrule="FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
        sections=("月度摘要", "核心指标", "同比环比", "目标差距", "下月计划"),
        evidence_requirements=("只读 SQL", "时间范围", "同比环比口径", "结果校验", "图表"),
        knowledge_required=False,
    ),
    "management_brief": EnterpriseReportTemplate(
        id="management_brief",
        title="经营简报",
        description="融合授权数据与已发布知识，形成可追溯的管理决策材料。",
        default_objective="汇总关键经营事实、制度约束、风险和需要管理层决策的事项。",
        default_rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
        sections=("决策摘要", "关键指标", "制度与业务约束", "风险", "待决策事项"),
        evidence_requirements=("只读 SQL", "结果校验", "已发布知识引用", "事实与建议分离", "图表"),
        knowledge_required=True,
    ),
}


def get_report_template(report_type: str) -> EnterpriseReportTemplate:
    try:
        return REPORT_TEMPLATES[report_type]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError("unsupported_report_type") from exc


def build_report_task_config(
    *,
    report_type: str,
    objective: str,
    data_sources: list[dict[str, str]],
    include_knowledge: bool,
    audience: str,
) -> dict[str, Any]:
    template = get_report_template(report_type)
    return {
        "schema_version": 1,
        "report_type": template.id,
        "objective": objective.strip() or template.default_objective,
        "audience": audience.strip() or "经营管理团队",
        "data_source_ids": [item["id"] for item in data_sources],
        "data_sources": [dict(item) for item in data_sources],
        "include_knowledge": bool(include_knowledge or template.knowledge_required),
        "sections": list(template.sections),
        "evidence_requirements": list(template.evidence_requirements),
        "artifact_schema_version": 1,
    }


def build_report_prompt(task_config: dict[str, Any]) -> str:
    template = get_report_template(str(task_config.get("report_type") or ""))
    sources = [
        f"- {item.get('name') or item.get('id')}（data_source_id={item.get('id')}）"
        for item in task_config.get("data_sources") or []
        if isinstance(item, dict) and item.get("id")
    ]
    knowledge_instruction = (
        "必须调用 RAG 检索当前 Project 可访问的已发布企业知识，并为制度或业务约束保留引用。"
        if task_config.get("include_knowledge")
        else "只有在结论需要企业制度或业务背景时才调用 RAG；不得把模型记忆当作公司事实。"
    )
    sections = "、".join(str(item) for item in task_config.get("sections") or template.sections)
    evidence = "、".join(
        str(item)
        for item in task_config.get("evidence_requirements") or template.evidence_requirements
    )
    return (
        f"你正在生成《{template.title}》，面向{task_config.get('audience') or '经营管理团队'}。\n"
        f"业务目标：{task_config.get('objective') or template.default_objective}\n\n"
        "这是受治理的企业报告任务。必须先调用 DataAgent 对下列授权数据源执行只读分析；"
        "涉及多个数据源时逐一使用明确的 data_source_id，不得猜测或写入数据。\n"
        f"{chr(10).join(sources)}\n\n"
        f"{knowledge_instruction}\n"
        "对每个核心数字保留 SQL、数据源、行数、指标口径和 verification_report；证据不足、"
        "口径冲突或校验失败时明确标记，不能补造结论。基于返回 rows 和 visualization_config "
        "生成至少一个适合复核的图表。区分事实、推断与建议。\n"
        f"固定章节：{sections}。\n"
        f"交付证据要求：{evidence}。\n"
        "最终输出使用简洁 Markdown，先结论后证据，并在末尾列出“数据证据”“知识引用”"
        "和“待确认事项”。"
    )


def _metadata_from_execution(execution: ResponseToolExecution) -> dict[str, Any]:
    result = dict(execution.result or {})
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    nested = result.get("result")
    if isinstance(nested, dict) and isinstance(nested.get("metadata"), dict):
        return dict(nested["metadata"])
    return {}


def _is_read_only_sql(sql: str) -> bool:
    try:
        SQLValidator(default_limit=100, max_limit=100).validate(sql)
        return True
    except (SQLValidationError, TypeError, ValueError):
        return False


async def build_report_artifact(
    db: AsyncSession,
    *,
    task: TaskDefinition,
    response: ResponseRecord,
    output: str,
    response_status: str,
) -> dict[str, Any]:
    """从持久化工具账本投影报告，避免把模型正文当作证据来源。"""

    executions = list(
        (
            await db.execute(
                select(ResponseToolExecution)
                .where(ResponseToolExecution.response_id == response.id)
                .order_by(ResponseToolExecution.created_at)
            )
        )
        .scalars()
        .all()
    )
    config = dict(task.task_config or {})
    data_evidence: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []
    for execution in executions:
        metadata = _metadata_from_execution(execution)
        tool_trace.append(
            {
                "tool": execution.tool_name,
                "call_id": execution.call_id,
                "status": execution.status,
                "side_effect": execution.side_effect_level,
            }
        )
        if execution.tool_name == "data" and execution.status == "completed" and metadata:
            verification = dict(metadata.get("verification_report") or {})
            sql = str(metadata.get("sql") or "")
            evidence_item = {
                "data_source_id": metadata.get("data_source_id"),
                "sql": sql,
                "readonly_sql": _is_read_only_sql(sql),
                "row_count": int(metadata.get("row_count") or 0),
                "rows": list(metadata.get("rows") or [])[:100],
                "verification": verification,
                "verification_status": str(
                    metadata.get("verification_status") or verification.get("status") or "unknown"
                ),
                "metrics": list(metadata.get("metrics_used") or []),
                "insights": metadata.get("insights"),
                "result_refs": list(metadata.get("result_refs") or []),
            }
            data_evidence.append(evidence_item)
            chart_config = metadata.get("visualization_config")
            if isinstance(chart_config, dict):
                charts.append(
                    {
                        "config": dict(chart_config),
                        "rows": evidence_item["rows"],
                        "data_source_id": evidence_item["data_source_id"],
                    }
                )
        elif execution.tool_name == "rag" and execution.status == "completed" and metadata:
            citations.extend(
                dict(item) for item in metadata.get("citations") or [] if isinstance(item, dict)
            )

    knowledge_required = bool(config.get("include_knowledge"))
    expected_source_ids = {str(item) for item in config.get("data_source_ids") or [] if str(item)}
    covered_source_ids = {
        str(item["data_source_id"]) for item in data_evidence if item.get("data_source_id")
    }
    missing_source_ids = sorted(expected_source_ids - covered_source_ids)
    readonly_sql = bool(data_evidence) and all(item["readonly_sql"] for item in data_evidence)
    data_verified = (
        bool(data_evidence)
        and not missing_source_ids
        and readonly_sql
        and all(item["sql"] and item["verification_status"] == "pass" for item in data_evidence)
    )
    knowledge_verified = bool(citations) if knowledge_required else True
    chart_verified = bool(charts)
    missing: list[str] = []
    if not data_verified:
        missing.append("verified_data_evidence")
    if data_evidence and not readonly_sql:
        missing.append("readonly_sql")
    if missing_source_ids:
        missing.append("data_source_coverage")
    if not knowledge_verified:
        missing.append("knowledge_citations")
    if not chart_verified:
        missing.append("chart_projection")
    verified = not missing and response_status == "completed"
    return {
        "schema_version": int(config.get("artifact_schema_version") or 1),
        "report_type": config.get("report_type"),
        "title": task.title,
        "objective": config.get("objective"),
        "audience": config.get("audience"),
        "response_id": response.id,
        "status": "verified" if verified else "needs_review",
        "generated_at": datetime.now(UTC).isoformat(),
        "content": output,
        "data_evidence": data_evidence,
        "knowledge_citations": citations[:100],
        "charts": charts[:20],
        "tool_trace": tool_trace,
        "verification": {
            "status": "pass" if verified else "needs_review",
            "data_verified": data_verified,
            "readonly_sql": readonly_sql,
            "data_source_coverage": {
                "expected": sorted(expected_source_ids),
                "covered": sorted(covered_source_ids),
                "missing": missing_source_ids,
            },
            "knowledge_verified": knowledge_verified,
            "chart_verified": chart_verified,
            "missing": missing,
        },
    }
