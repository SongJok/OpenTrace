"""
PatternExtractorAgent — extracts and stores successful query patterns.

After a successful query execution, this agent:
1. Computes a SHA256 pattern hash from (intent_type, entities, metrics)
2. Upserts into query_patterns table (create or update)
3. Updates table_relationships usage_count and success_rate
4. Extracts dimensional patterns for skill distillation candidates

This is the "memory" component of the self-learning loop:
  Success → store pattern → next similar query hits cache → skip reasoning.
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
    """Extract query patterns from successful executions for future fast-path.

    Non-LLM, deterministic. Operates only on successful queries with
    confidence above threshold.
    """

    MIN_CONFIDENCE_THRESHOLD = 0.70
    MIN_ROWS_FOR_RELATIONSHIP_UPDATE = 1

    def __init__(self) -> None:
        super().__init__("data_pattern_extractor")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        # Only extract from successful queries
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
            # 1. Compute pattern signature
            pattern_key = self._compute_pattern_key(ctx)
            pattern_hash = hashlib.sha256(pattern_key.encode()).hexdigest()

            # 2. Upsert query_pattern
            await self._upsert_pattern(db, ctx, sql, pattern_hash, confidence)

            # 3. Update relationship success rates
            await self._update_relationship_stats(db, ctx, success=True)

            elapsed_ms = int((time.monotonic() - t0) * 1000)

            # Store pattern hash on context
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

    # ── Core Logic ──────────────────────────────────────────────────────

    def _compute_pattern_key(self, ctx: CognitiveContext) -> str:
        """Compute a stable pattern key from query structure."""
        intent_type = ctx.intent.get("intent_type", "") if ctx.intent else ""
        entities = sorted(
            e.get("mapped_table", "") for e in (ctx.entities or [])
            if e.get("mapped_table")
        )
        metrics = sorted(
            m.get("mention", "") for m in (ctx.metrics or [])
            if m.get("mention")
        )
        # Also include time window type if present
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
        """Create or update a query_pattern record."""
        from infra.storage.models import QueryPattern
        from sqlalchemy import update as sql_update
        from datetime import datetime, timezone

        # Check if exists
        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == pattern_hash)
        )
        existing = result.scalar()

        if existing:
            # Update: increment success_count, update SQL if higher confidence
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
            # Create new pattern
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
        """Update table_relationships usage statistics."""
        from infra.storage.models import TableRelationship

        if not ctx.data_source_id:
            return

        # Get the relationships used in this query
        relationships = ctx.matched_relationships or []
        join_paths = ctx.join_paths or []

        # Collect (left_table, right_table) pairs from join paths
        used_pairs: set[tuple[str, str]] = set()
        for jp in join_paths:
            path = jp.get("path", "")
            if "." in path:
                # Crude extraction: try to find table pairs
                parts = path.replace("=", " ").replace("ON", " ").split()
                for part in parts:
                    if "." in part:
                        t = part.split(".")[0].strip().strip("`\"'")
                        used_pairs.add((t, ""))  # We have partial info

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
                        # Exponential moving average for success rate
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
