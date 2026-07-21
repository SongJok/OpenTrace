from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import settings
from infra.storage.models import ResponseItem, ResponseRecord
from kernel.token_counter import get_token_counter
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


class ConversationSummarizer:
    """Persist a versioned, source-bounded summary for long active branches."""

    def __init__(
        self,
        *,
        minimum_chars: int = 40_000,
        minimum_new_responses: int = 8,
        minimum_tokens: int | None = None,
    ):
        self.minimum_chars = minimum_chars
        self.minimum_new_responses = minimum_new_responses
        self.minimum_tokens = minimum_tokens or int(
            getattr(settings, "responses_summary_trigger_tokens", 48_000)
        )

    async def summarize(self, db: AsyncSession, *, response: ResponseRecord) -> str | None:
        chain = await self._chain(db, response)
        if not chain:
            return None
        ids = [row.id for row in chain]
        items = (
            (
                await db.execute(
                    select(ResponseItem)
                    .where(
                        ResponseItem.response_id.in_(ids),
                        ResponseItem.item_type.in_(
                            ["input_message", "message", "conversation_summary"]
                        ),
                    )
                    .order_by(ResponseItem.created_at, ResponseItem.sequence_number)
                )
            )
            .scalars()
            .all()
        )
        latest_summary = next(
            (item for item in reversed(items) if item.item_type == "conversation_summary"),
            None,
        )
        previous_source_ids: list[str] = []
        if latest_summary:
            previous_source_ids = list(
                (latest_summary.payload or {}).get("source_response_ids") or []
            )
            last_source = (
                previous_source_ids[-1] if previous_source_ids else latest_summary.response_id
            )
            try:
                start = ids.index(last_source) + 1
                new_ids = set(ids[start:])
            except ValueError:
                new_ids = set(ids)
            if len(new_ids) < self.minimum_new_responses:
                return None
            candidate_items = [
                item
                for item in items
                if item.response_id in new_ids and item.item_type != "conversation_summary"
            ]
            version = int((latest_summary.payload or {}).get("version") or 1) + 1
        else:
            candidate_items = [item for item in items if item.item_type != "conversation_summary"]
            version = 1
        total_chars = sum(len(item.content or "") for item in candidate_items)
        total_tokens = sum(
            get_token_counter().count(item.content or "") for item in candidate_items
        )
        if total_chars < self.minimum_chars and total_tokens < self.minimum_tokens:
            return None
        transcript_parts: list[str] = []
        if latest_summary:
            transcript_parts.append(
                "[上一版持久摘要，必须继续保留仍然有效的目标、约束、决定与未完成事项]\n"
                + (latest_summary.content or "")[:16_000]
            )
        transcript_parts.extend(
            f"[{item.response_id}] {item.role}: {(item.content or '')[:5000]}"
            for item in candidate_items[-80:]
        )
        transcript = "\n".join(transcript_parts)[-100_000:]
        result = await get_model_gateway().complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "将对话压缩为可继续工作的事实摘要。保留用户目标、约束、决定、"
                        "未完成事项、工具证据与引用；不要加入原文没有的事实，也不要输出隐藏思维链。"
                    ),
                ),
                LLMMessage(role="user", content=transcript),
            ],
            role=LLMRole.COMPRESS,
            fallback_roles=[LLMRole.QUERY],
            max_output_tokens=3000,
            store=False,
        )
        summary = str(result.content or "").strip()
        if not summary:
            return None
        source_response_ids = list(
            dict.fromkeys([*previous_source_ids, *(item.response_id for item in candidate_items)])
        )
        sequence = await db.scalar(
            select(func.max(ResponseItem.sequence_number)).where(
                ResponseItem.response_id == response.id
            )
        )
        item = ResponseItem(
            id=f"item_{uuid.uuid4().hex}",
            response_id=response.id,
            sequence_number=int(sequence if sequence is not None else -1) + 1,
            item_type="conversation_summary",
            role="system",
            content=summary,
            payload={
                "version": version,
                "source_response_ids": source_response_ids,
                "source_checksum": hashlib.sha256(transcript.encode()).hexdigest(),
                "source_tokens": total_tokens,
            },
        )
        db.add(item)
        await db.commit()
        return item.id

    @staticmethod
    async def _chain(db: AsyncSession, response: ResponseRecord) -> list[ResponseRecord]:
        rows: list[ResponseRecord] = []
        seen: set[str] = set()
        current: ResponseRecord | None = response
        while current and current.id not in seen and len(rows) < 200:
            seen.add(current.id)
            rows.append(current)
            current = (
                await db.get(ResponseRecord, current.parent_response_id)
                if current.parent_response_id
                else None
            )
        return list(reversed(rows))
