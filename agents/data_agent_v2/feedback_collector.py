"""
FeedbackCollectorAgent — 学习层入口。

采集用户反馈（纠正、评分、点赞、补充查询），分类为可执行类型，
写入 feedback 表，供 PatternExtractor、KnowledgeUpdater、MetricRefiner 使用。

反馈类型：
  - like / dislike：结果质量二元情感
  - rating (1-5)：数值质量评分
  - correction_sql：用户纠正生成的 SQL
  - correction_metric：用户纠正指标公式/定义
  - correction_entity：用户纠正实体映射
  - correction_time：用户纠正时间窗
  - supplement：用户补充上下文以细化查询
"""
from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    CognitiveContext,
    pack_cognitive_result,
    unpack_cognitive_context,
)


class FeedbackCollectorAgent(BaseAgent):
    """采集并分类用户反馈，用于学习闭环。

    观察最终答案 + 用户交互，分类反馈类型，
    存储到反馈表，并返回分类信号供下游学习 Agent 使用。
    """

    def __init__(self) -> None:
        super().__init__("data_feedback_collector")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        feedback_payload = task.params.get("feedback", {})
        if not feedback_payload:
            return self._empty_result(task, ctx, "no feedback provided")

        try:
            classification = self._classify(feedback_payload, ctx)

            # 若会话可用，存储到数据库
            db = task.params.get("_db_session")
            if db:
                await self._store_feedback(db, task, feedback_payload, classification)

            # 将分类结果附加到上下文，供下游学习使用
            ctx.learning_signals = (ctx.learning_signals or {}) | {
                "feedback_type": classification["type"],
                "feedback_action": classification["action"],
                "confidence_impact": classification["confidence_impact"],
                "corrected_sql": classification.get("corrected_sql"),
                "corrected_metric_id": classification.get("corrected_metric_id"),
            }

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"feedback collected: {classification['type']} → {classification['action']}",
                confidence=0.95,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="feedback_collector",
                    source_type="learning",
                    payload={
                        "feedback_type": classification["type"],
                        "action": classification["action"],
                    },
                    credibility=0.90,
                    relevance=0.80,
                )],
                agent_trace={"feedback_classification": classification},
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="feedback collection skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    def _classify(
        self, feedback: dict, ctx: CognitiveContext
    ) -> dict[str, Any]:
        """将反馈分类为可执行类型和策略。"""
        fb_type = feedback.get("type", "")
        rating = feedback.get("rating")
        correction = feedback.get("correction", "")
        corrected_sql = feedback.get("corrected_sql", "")
        corrected_metric = feedback.get("corrected_metric", {})

        classification: dict[str, Any] = {
            "type": "unknown",
            "action": "none",
            "confidence_impact": 0.0,
            "details": {},
        }

        if fb_type == "like":
            classification.update({
                "type": "like",
                "action": "reinforce_pattern",
                "confidence_impact": +0.05,
                "details": {"reinforce": "query_patterns.success_count"},
            })

        elif fb_type == "dislike":
            classification.update({
                "type": "dislike",
                "action": "mark_for_review",
                "confidence_impact": -0.05,
                "details": {"action": "decrease_pattern_confidence"},
            })

        elif fb_type == "rating" and isinstance(rating, (int, float)):
            if rating >= 4:
                classification.update({
                    "type": "high_rating",
                    "action": "reinforce_pattern",
                    "confidence_impact": +0.05,
                })
            elif rating <= 2:
                classification.update({
                    "type": "low_rating",
                    "action": "mark_for_review",
                    "confidence_impact": -0.05,
                })
            else:
                classification.update({
                    "type": "medium_rating",
                    "action": "store_for_analysis",
                    "confidence_impact": 0.0,
                })

        elif fb_type == "correction" or correction:
            classification.update(self._classify_correction(
                correction or fb_type, corrected_sql, corrected_metric, ctx
            ))

        elif fb_type == "supplement":
            classification.update({
                "type": "supplement",
                "action": "enrich_pattern",
                "confidence_impact": +0.02,
                "details": {"context": feedback.get("context", "")},
            })

        return classification

    def _classify_correction(
        self,
        correction: str,
        corrected_sql: str,
        corrected_metric: dict,
        ctx: CognitiveContext,
    ) -> dict[str, Any]:
        """分类用户做出的纠正类型。"""
        if corrected_sql:
            return {
                "type": "correction_sql",
                "action": "update_query_pattern",
                "confidence_impact": -0.10,
                "corrected_sql": corrected_sql,
                "details": {
                    "original_sql": ctx.compiled_sql,
                    "correction": correction,
                },
            }

        if corrected_metric:
            return {
                "type": "correction_metric",
                "action": "refine_metric_definition",
                "confidence_impact": -0.08,
                "corrected_metric_id": corrected_metric.get("id"),
                "details": {
                    "original_metrics": [m.get("name") for m in (ctx.metrics or [])],
                    "corrected_metric": corrected_metric,
                    "correction": correction,
                },
            }

        # 基于纠正文本的启发式分类
        lower = correction.lower()
        if any(kw in lower for kw in ("指标", "metric", "公式", "formula", "计算", "口径")):
            return {
                "type": "correction_metric",
                "action": "refine_metric_definition",
                "confidence_impact": -0.08,
                "details": {"correction": correction},
            }
        if any(kw in lower for kw in ("sql", "查询", "select", "join", "表", "table")):
            return {
                "type": "correction_sql",
                "action": "update_query_pattern",
                "confidence_impact": -0.10,
                "details": {"correction": correction},
            }
        if any(kw in lower for kw in ("时间", "日期", "范围", "time")):
            return {
                "type": "correction_time",
                "action": "update_time_window",
                "confidence_impact": -0.05,
                "details": {"correction": correction},
            }
        if any(kw in lower for kw in ("实体", "对象", "entity", "维度")):
            return {
                "type": "correction_entity",
                "action": "update_entity_mapping",
                "confidence_impact": -0.05,
                "details": {"correction": correction},
            }

        return {
            "type": "correction_general",
            "action": "store_for_review",
            "confidence_impact": -0.03,
            "details": {"correction": correction},
        }

    async def _store_feedback(
        self,
        db,
        task: TaskMessage,
        payload: dict,
        classification: dict,
    ) -> None:
        """将反馈持久化到反馈表。"""
        from infra.storage.models import Feedback

        feedback = Feedback(
            session_id=task.session_id or "",
            query=task.query or "",
            response=payload.get("response", ""),
            feedback_type=classification["type"],
            score=payload.get("rating"),
            correction=payload.get("correction", ""),
            feedback_metadata=str({
                "classification": classification,
                "agent_trace_id": task.task_id,
            }),
            agent_trace_id=task.task_id,
            corrected_metric_id=classification.get("corrected_metric_id"),
            corrected_sql=classification.get("corrected_sql"),
        )
        db.add(feedback)
        await db.commit()

    def _empty_result(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"feedback collection skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"warning": reason},
        )
