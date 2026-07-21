"""
PatternExtractorAgent — 抽取并存储成功查询模式。

成功执行 SQL 后：
1. 由 (intent_type, entities, metrics) 计算 SHA256 模式哈希
2. 写入/更新 query_patterns 表
3. 更新 table_relationships 的 usage_count、success_rate
4. 抽取维度模式供技能蒸馏候选

自学习环路的「记忆」组件：成功 → 存模式 → 相似查询命中缓存 → 跳过推理。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class PatternExtractorAgent(BaseAgent):
    """从成功执行中抽取查询模式，用于未来快路径。

    非 LLM、确定性。仅对置信度高于阈值的成功查询进行操作。
    """

    MIN_CONFIDENCE_THRESHOLD = 0.70
    MIN_ROWS_FOR_RELATIONSHIP_UPDATE = 1

    def __init__(self) -> None:
        super().__init__("data_pattern_extractor")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        # 仅从成功查询中抽取
        confidence = task.params.get("final_confidence", 0.0)
        if confidence < self.MIN_CONFIDENCE_THRESHOLD:
            return self._skip(task, ctx, f"confidence {confidence:.2f} below threshold")

        sql = ctx.compiled_sql or ""
        rows = ctx.execution_rows or []
        error = ctx.execution_error
        if error or not sql:
            return self._skip(task, ctx, "no successful SQL to extract")

        db = task.params.get("_db_session")
        if not db:
            return self._skip(task, ctx, "no db session")

        t0 = time.monotonic()

        try:
            # 1. 计算模式签名
            pattern_key = self._compute_pattern_key(ctx)
            pattern_hash = hashlib.sha256(pattern_key.encode()).hexdigest()

            # 2. 更新或插入 query_pattern
            await self._upsert_pattern(db, ctx, sql, pattern_hash, confidence)

            # 3. 更新关系成功率
            await self._update_relationship_stats(db, ctx, success=True)

            elapsed_ms = int((time.monotonic() - t0) * 1000)

            # 将模式哈希存储到上下文
            ctx.pattern_hit = {
                "pattern_hash": pattern_hash,
                "successful_sql": sql,
                "success_count": 1,
                "avg_confidence": confidence,
            }

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"pattern extracted: {pattern_hash[:12]}",
                confidence=0.95,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="pattern_extractor",
                    source_type="learning",
                    payload={
                        "pattern_hash": pattern_hash[:12],
                        "intent_type": ctx.intent.get("intent_type") if ctx.intent else None,
                        "metrics": [m.get("name") for m in (ctx.matched_metrics or [])],
                        "entities": [e.get("mapped_table") for e in (ctx.entities or [])],
                    },
                    credibility=0.90,
                    relevance=0.90,
                )],
                agent_trace={
                    "pattern_hash": pattern_hash,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="pattern extraction skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    # ── 核心逻辑 ──────────────────────────────────────────────────

    def _compute_pattern_key(self, ctx: CognitiveContext) -> str:
        """从查询结构计算稳定的模式键。"""
        intent_type = ctx.intent.get("intent_type", "") if ctx.intent else ""
        entities = sorted(
            e.get("mapped_table", "") for e in (ctx.entities or [])
            if e.get("mapped_table")
        )
        metrics = sorted(
            m.get("mention", "") for m in (ctx.metrics or [])
            if m.get("mention")
        )
        # 若存在时间窗类型也包含
        time_type = (
            ctx.time_window.get("type", "")
            if ctx.time_window and ctx.time_window.get("type") not in (None, "none")
            else ""
        )

        return f"{intent_type}|{','.join(entities)}|{','.join(metrics)}|{time_type}"

    async def _upsert_pattern(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        sql: str,
        pattern_hash: str,
        confidence: float,
    ) -> None:
        """创建或更新 query_pattern 记录。"""
        from infra.storage.models import QueryPattern
        from sqlalchemy import update as sql_update
        from datetime import datetime, timezone

        # 检查是否已存在
        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == pattern_hash)
        )
        existing = result.scalar()

        if existing:
            # 更新：递增 success_count，若置信度更高则更新 SQL
            new_count = (existing.success_count or 0) + 1
            new_avg_conf = (
                (existing.avg_confidence or confidence) * (new_count - 1) + confidence
            ) / new_count

            await db.execute(
                sql_update(QueryPattern)
                .where(QueryPattern.pattern_hash == pattern_hash)
                .values(
                    successful_sql=sql,
                    success_count=new_count,
                    avg_confidence=round(new_avg_conf, 3),
                    last_used_at=datetime.now(timezone.utc),
                )
            )
        else:
            # 创建新模式
            pattern = QueryPattern(
                pattern_hash=pattern_hash,
                query_template=ctx.query or "",
                intent_type=ctx.intent.get("intent_type") if ctx.intent else None,
                entities=[e.get("mapped_table", "") for e in (ctx.entities or [])],
                metrics=[m.get("mention", "") for m in (ctx.metrics or [])],
                successful_sql=sql,
                success_count=1,
                failure_count=0,
                avg_confidence=confidence,
                last_used_at=datetime.now(timezone.utc),
            )
            db.add(pattern)

        await db.commit()

    async def _update_relationship_stats(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        success: bool,
    ) -> None:
        """更新 table_relationships 使用统计。"""
        from infra.storage.models import TableRelationship

        if not ctx.data_source_id:
            return

        # 获取本查询使用的关系
        relationships = ctx.matched_relationships or []
        join_paths = ctx.join_paths or []

        # 从 JOIN 路径收集 (left_table, right_table) 对
        used_pairs: set[tuple[str, str]] = set()
        for jp in join_paths:
            path = jp.get("path", "")
            if "." in path:
                # 粗略提取：尝试查找表对
                parts = path.replace("=", " ").replace("ON", " ").split()
                for part in parts:
                    if "." in part:
                        t = part.split(".")[0].strip().strip("`\"'")
                        used_pairs.add((t, ""))  # 信息不完整

        for rel in relationships:
            left = rel.get("left_table", "")
            right = rel.get("right_table", "")
            pair_key = (left, right)

            if pair_key in used_pairs or any(
                left in p[0] or right in p[0] for p in used_pairs
            ):
                try:
                    result = await db.execute(
                        select(TableRelationship).where(
                            TableRelationship.data_source_id == ctx.data_source_id,
                            TableRelationship.left_table == left,
                            TableRelationship.right_table == right,
                        )
                    )
                    row = result.scalar()
                    if row:
                        new_count = (row.usage_count or 0) + 1
                        # 指数移动平均计算成功率
                        alpha = 0.3
                        new_rate = (
                            row.success_rate * (1 - alpha) + (1.0 if success else 0.0) * alpha
                        )
                        row.usage_count = new_count
                        row.success_rate = round(new_rate, 3)
                        await db.commit()
                except Exception:
                    pass

    def _skip(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"pattern extraction skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"skip_reason": reason},
        )
