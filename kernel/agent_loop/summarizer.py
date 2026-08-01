from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

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
                            [
                                "input_message",
                                "message",
                                "function_call",
                                "function_call_output",
                                "conversation_summary",
                            ]
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
            candidate_items = [
                item
                for item in items
                if item.response_id in new_ids and item.item_type != "conversation_summary"
            ]
            version = int((latest_summary.payload or {}).get("version") or 1) + 1
        else:
            candidate_items = [item for item in items if item.item_type != "conversation_summary"]
            version = 1
        candidate_lines = [self._transcript_line(item) for item in candidate_items]
        total_chars = sum(len(line) for line in candidate_lines)
        total_tokens = sum(get_token_counter().count(line) for line in candidate_lines)
        candidate_response_count = len({item.response_id for item in candidate_items})
        if not self._summary_due(
            total_chars=total_chars,
            total_tokens=total_tokens,
            response_count=candidate_response_count,
        ):
            return None
        transcript_parts: list[str] = []
        if latest_summary:
            transcript_parts.append(
                "[上一版持久摘要，必须继续保留仍然有效的目标、约束、决定与未完成事项]\n"
                + (latest_summary.content or "")[:16_000]
            )
        transcript_parts.extend(candidate_lines[-100:])
        transcript = "\n".join(transcript_parts)[-100_000:]
        structured_state: dict[str, Any] | None = None
        summary_origin = "model"
        try:
            result = await get_model_gateway().complete(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "将对话压缩为可继续工作的结构化检查点，只输出 JSON 对象。字段必须为："
                            "current_goal（字符串）、constraints、decisions、open_items、confirmed_facts、"
                            "tool_evidence、recent_turns（均为字符串数组）。保留仍然有效的用户目标、"
                            "输出约束、明确决定、未完成事项、工具执行结果和最近三轮关键内容。"
                            "用户后来的更正覆盖旧说法；相对日期必须保留原文并尽可能附带已知绝对日期。"
                            "工具调用与工具结果要区分已提议、待审批、成功、失败和结果未知。"
                            "不要加入原文没有的事实，不要输出隐藏思维链，也不要输出 Markdown 围栏。"
                        ),
                    ),
                    LLMMessage(role="user", content=transcript),
                ],
                role=LLMRole.COMPRESS,
                fallback_roles=[LLMRole.QUERY],
                max_output_tokens=3000,
                store=False,
            )
            structured_state = self._parse_structured_state(str(result.content or ""))
        except Exception:  # 模型压缩失败时仍必须生成可恢复检查点。
            structured_state = None
        if structured_state is None:
            previous_state = (
                dict((latest_summary.payload or {}).get("structured_state") or {})
                if latest_summary
                else {}
            )
            structured_state = self._deterministic_state(
                candidate_items,
                previous_state=previous_state,
            )
            summary_origin = "deterministic_fallback"
        summary = self._render_structured_state(structured_state)
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
                "summary_format": "structured_v2",
                "summary_origin": summary_origin,
                "structured_state": structured_state,
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
            parent = (
                await db.get(ResponseRecord, current.parent_response_id)
                if current.parent_response_id
                else None
            )
            current = parent if ConversationSummarizer._same_scope(parent, response) else None
        return list(reversed(rows))

    @staticmethod
    def _same_scope(candidate: ResponseRecord | None, response: ResponseRecord) -> bool:
        if candidate is None:
            return False
        return all(
            getattr(candidate, field, None) == getattr(response, field, None)
            for field in ("conversation_id", "user_id", "tenant_id", "workspace_id")
        )

    @staticmethod
    def _transcript_line(item: ResponseItem) -> str:
        payload = dict(item.payload or {})
        detail: Any = item.content or ""
        if item.item_type == "function_call":
            detail = {
                "name": payload.get("name"),
                "call_id": payload.get("call_id"),
                "arguments": payload.get("arguments") or {},
                "status": payload.get("status") or "proposed",
            }
        elif item.item_type == "function_call_output":
            detail = {
                "name": payload.get("name"),
                "call_id": payload.get("call_id"),
                "status": payload.get("status") or "completed",
                "output": item.content or payload.get("output") or payload,
            }
        serialized = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        return f"[{item.response_id}] {item.item_type}/{item.role}: {serialized[:5000]}"

    def _summary_due(
        self,
        *,
        total_chars: int,
        total_tokens: int,
        response_count: int,
    ) -> bool:
        return bool(
            total_chars >= self.minimum_chars
            or total_tokens >= self.minimum_tokens
            or response_count >= self.minimum_new_responses
        )

    @staticmethod
    def _parse_structured_state(raw: str) -> dict[str, Any] | None:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
        try:
            value = json.loads(cleaned)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, dict):
            return None
        fields = (
            "constraints",
            "decisions",
            "open_items",
            "confirmed_facts",
            "tool_evidence",
            "recent_turns",
        )
        state: dict[str, Any] = {
            "current_goal": str(value.get("current_goal") or "").strip()[:2000]
        }
        for field in fields:
            raw_items = value.get(field) or []
            if not isinstance(raw_items, list):
                raw_items = [raw_items]
            state[field] = [
                str(item).strip()[:2000] for item in raw_items[:20] if str(item).strip()
            ]
        if not state["current_goal"] and not any(state[field] for field in fields):
            return None
        return state

    @staticmethod
    def _render_structured_state(state: dict[str, Any]) -> str:
        labels = (
            ("current_goal", "当前目标"),
            ("constraints", "有效约束"),
            ("decisions", "已确认决定"),
            ("open_items", "未完成事项"),
            ("confirmed_facts", "已确认事实"),
            ("tool_evidence", "工具与证据"),
            ("recent_turns", "最近关键回合"),
        )
        sections = ["对话连续性检查点（历史摘要；当前用户消息与后续更正优先）："]
        for key, label in labels:
            value = state.get(key)
            if isinstance(value, list) and value:
                sections.append(f"## {label}\n" + "\n".join(f"- {item}" for item in value))
            elif isinstance(value, str) and value:
                sections.append(f"## {label}\n{value}")
        return "\n\n".join(sections)

    @classmethod
    def _deterministic_state(
        cls,
        items: list[ResponseItem],
        *,
        previous_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """模型不可用时只使用持久 Item 生成保守检查点，不推断新事实。"""

        previous = previous_state or {}

        def previous_list(key: str) -> list[str]:
            value = previous.get(key) or []
            if not isinstance(value, list):
                value = [value]
            return [str(item).strip()[:2000] for item in value if str(item).strip()]

        recent_turns = previous_list("recent_turns")
        tool_evidence = previous_list("tool_evidence")
        current_goal = str(previous.get("current_goal") or "").strip()[:2000]
        for item in items:
            if item.item_type in {"input_message", "message"}:
                content = str(item.content or "").strip()
                if not content:
                    continue
                label = "用户" if item.role == "user" else "助手"
                recent_turns.append(f"{label}：{content[:1800]}")
                if item.item_type == "input_message" and item.role == "user":
                    current_goal = content[:2000]
            elif item.item_type in {"function_call", "function_call_output"}:
                tool_evidence.append(cls._transcript_line(item)[:2000])
        return {
            "current_goal": current_goal,
            "constraints": previous_list("constraints")[-20:],
            "decisions": previous_list("decisions")[-20:],
            "open_items": previous_list("open_items")[-20:],
            "confirmed_facts": previous_list("confirmed_facts")[-20:],
            "tool_evidence": tool_evidence[-12:],
            "recent_turns": recent_turns[-6:],
        }
