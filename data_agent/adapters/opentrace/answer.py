"""受结果事实约束的答案合成器。"""

from __future__ import annotations

import json

from data_agent.contracts import ExecutionResult, LogicalQueryPlan, QueryRequest
from data_agent.ports import NullAnswerSynthesizer
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


class OpenTraceAnswerSynthesizer(NullAnswerSynthesizer):
    async def synthesize(
        self, request: QueryRequest, plan: LogicalQueryPlan, result: ExecutionResult
    ) -> str:
        fallback = await super().synthesize(request, plan, result)
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
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "question": request.question,
                                "logical_plan": plan.model_dump(mode="json"),
                                "result": result.model_dump(mode="json"),
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
            return text or fallback
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            return fallback
