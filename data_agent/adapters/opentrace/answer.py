"""受结果事实约束的答案合成器。"""

from __future__ import annotations

import json
import re

from data_agent.contracts import (
    AnswerCitation,
    EvidenceBundle,
    ExecutionResult,
    LogicalQueryPlan,
    QueryRequest,
    ResultValidationReport,
)
from data_agent.ports import NullAnswerSynthesizer
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

_CITATION_PATTERN = re.compile(r"\[\s*([A-Za-z]+)\s*(\d+)\s*\]")


def sanitize_answer_citations(text: str, citations: list[AnswerCitation]) -> str:
    """只保留证据包声明的引用，并确保结果数字绑定本次执行。"""

    allowed = {item.label for item in citations}

    def replace(match: re.Match[str]) -> str:
        label = f"{match.group(1).upper()}{match.group(2)}"
        return f"[{label}]" if label in allowed else ""

    sanitized = _CITATION_PATTERN.sub(replace, str(text or "")).strip()
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    if "R1" in allowed and "[R1]" not in sanitized:
        sanitized = f"{sanitized}\n\n结果证据：[R1]".strip()
    if not any(f"[{label}]" in sanitized for label in allowed):
        labels = " ".join(f"[{item.label}]" for item in citations[:6])
        sanitized = f"{sanitized}\n\n证据：{labels}".strip()
    return sanitized


class OpenTraceAnswerSynthesizer(NullAnswerSynthesizer):
    async def synthesize(
        self,
        request: QueryRequest,
        plan: LogicalQueryPlan,
        result: ExecutionResult,
        *,
        evidence: EvidenceBundle,
        citations: list[AnswerCitation],
        result_validation: ResultValidationReport,
    ) -> str:
        fallback = await super().synthesize(
            request,
            plan,
            result,
            evidence=evidence,
            citations=citations,
            result_validation=result_validation,
        )
        if not result.rows:
            return fallback
        try:
            response = await get_model_gateway().complete(
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "你是企业数据问答结果整理器。只能根据给定 rows 回答，不能补造任何数字。"
                            "必须说明返回行数；如果 truncated=true，必须明确说明结果不完整。"
                            "每个核心数字、指标定义或业务规则后必须引用提供的 [R1]/[E1] 标签。"
                            "禁止生成未提供的引用标签，也不要把 SQL 猜测描述成业务事实。"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "question": request.question,
                                "logical_plan": plan.model_dump(mode="json"),
                                "result": result.model_dump(mode="json"),
                                "result_validation": result_validation.model_dump(mode="json"),
                                "citations": [item.model_dump(mode="json") for item in citations],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                role=LLMRole.QUERY,
                temperature=0.0,
                max_tokens=1200,
            )
            text = str(response.content or "").strip()
            if not text:
                return fallback
            return sanitize_answer_citations(text, citations)
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            return fallback
